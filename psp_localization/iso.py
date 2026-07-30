from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from psp_localization.sfo import SFOError, parse_sfo
from psp_localization.util import (
    atomic_write_json,
    file_fingerprint,
    relative_files,
    sha1_file,
)


class PSPImageError(RuntimeError):
    pass


IMPORTANT_SUFFIXES = {
    ".bin", ".dat", ".pak", ".arc", ".nsf", ".prx", ".lzs",
    ".fnt", ".txp", ".gim", ".tm2", ".gmo", ".gm3",
}

# 프리니 계열 구조/폰트 호환성 및 실행 파일 UI 문자열 검사를 위해 필요한 최소 파일.
# 전체 ISO를 풀지 않으므로 저장 공간이 부족한 환경에서도 비교할 수 있다.
MINIMAL_PSP_MEMBERS = (
    "UMD_DATA.BIN",
    "PSP_GAME/PARAM.SFO",
    "PSP_GAME/SYSDIR/BOOT.BIN",
    "PSP_GAME/SYSDIR/EBOOT.BIN",
    "PSP_GAME/USRDIR/SYSTEM.DAT",
    "PSP_GAME/USRDIR/SCRIPT.DAT",
)


def find_disc_root(path: Path) -> Path:
    candidates = [path, path / "PSP_GAME"]
    for candidate in candidates:
        if candidate.name == "PSP_GAME" and candidate.is_dir():
            return candidate.parent
        if (candidate / "PSP_GAME").is_dir():
            return candidate
    for candidate in path.rglob("PSP_GAME") if path.is_dir() else []:
        if candidate.is_dir():
            return candidate.parent
    raise PSPImageError(f"PSP_GAME 디렉터리를 찾지 못했습니다: {path}")


def _run_7z_extract(
    image: Path,
    output: Path,
    *,
    members: Iterable[str] | None = None,
) -> dict[str, Any]:
    executable = shutil.which("7z")
    if executable is None:
        raise PSPImageError("7z 명령을 찾지 못했습니다. p7zip-full을 설치하세요.")
    output.mkdir(parents=True, exist_ok=True)
    requested = list(members or [])
    command = [executable, "x", "-y", f"-o{output}", str(image), *requested]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        tail = (process.stdout + "\n" + process.stderr)[-4000:]
        raise PSPImageError("ISO/CSO 추출 실패:\n" + tail)
    return {
        "command": command,
        "returncode": process.returncode,
        "requested_members": requested,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }


def prepare_disc(
    source: Path,
    output: Path,
    *,
    force: bool = False,
    extraction_mode: str = "full",
) -> tuple[Path, dict[str, Any]]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if extraction_mode not in {"full", "minimal"}:
        raise ValueError(f"지원하지 않는 추출 모드: {extraction_mode}")

    if source.is_dir():
        root = find_disc_root(source)
        return root, {
            "source": str(source),
            "source_type": "directory",
            "disc_root": str(root),
            "reused": True,
            "extraction_mode": "directory",
        }

    if not source.is_file():
        raise FileNotFoundError(f"게임 이미지가 없습니다: {source}")

    source_sha1 = sha1_file(source)
    manifest_path = output / "extract_manifest.json"
    extract_dir = output / "iso"

    if not force and manifest_path.is_file() and extract_dir.is_dir():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if (
            manifest.get("source_sha1") == source_sha1
            and manifest.get("extraction_mode") == extraction_mode
        ):
            try:
                root = find_disc_root(extract_dir)
            except PSPImageError:
                pass
            else:
                manifest["reused"] = True
                return root, manifest

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    members = MINIMAL_PSP_MEMBERS if extraction_mode == "minimal" else None
    command_result = _run_7z_extract(source, extract_dir, members=members)
    root = find_disc_root(extract_dir)

    # minimal 모드에서 핵심 파일이 전혀 없으면 잘못된 이미지/7z 경로로 판단한다.
    if extraction_mode == "minimal":
        system = root / "PSP_GAME" / "USRDIR" / "SYSTEM.DAT"
        if not system.is_file():
            raise PSPImageError(
                "최소 추출 후 SYSTEM.DAT를 찾지 못했습니다. "
                "PSP 이미지가 맞는지 확인하세요."
            )

    manifest = {
        "source": str(source),
        "source_type": source.suffix.lower().lstrip("."),
        "source_size": source.stat().st_size,
        "source_sha1": source_sha1,
        "disc_root": str(root),
        "reused": False,
        "extraction_mode": extraction_mode,
        "extract_command": command_result,
    }
    atomic_write_json(manifest_path, manifest)
    return root, manifest


def cleanup_prepared_disc(output: Path) -> dict[str, Any]:
    """prepare_disc가 만든 실제 추출본만 제거하고 분석/manifest는 남긴다."""
    extract_dir = output.expanduser().resolve() / "iso"
    if not extract_dir.exists():
        return {"status": "skipped", "path": str(extract_dir), "reason": "없음"}
    if extract_dir.name != "iso":
        raise PSPImageError(f"보호되지 않은 추출 경로: {extract_dir}")
    size = sum(path.stat().st_size for path in extract_dir.rglob("*") if path.is_file())
    shutil.rmtree(extract_dir)
    return {"status": "removed", "path": str(extract_dir), "freed_bytes": size}


def analyze_disc(
    disc_root: Path,
    *,
    full_hash_limit: int = 64 * 1024 * 1024,
    analysis_scope: str = "full",
) -> dict[str, Any]:
    disc_root = find_disc_root(disc_root)
    param_path = disc_root / "PSP_GAME" / "PARAM.SFO"
    try:
        sfo = parse_sfo(param_path) if param_path.is_file() else {}
    except (OSError, SFOError) as error:
        sfo = {"_error": str(error)}

    files: list[dict[str, Any]] = []
    candidate_count = 0
    for relative in relative_files(disc_root):
        path = disc_root / relative
        suffix = path.suffix.lower()
        important = suffix in IMPORTANT_SUFFIXES or relative.as_posix().upper().endswith(
            ("EBOOT.BIN", "BOOT.BIN", "PARAM.SFO")
        )
        if important:
            candidate_count += 1
        fingerprint = file_fingerprint(path, full_hash_limit=full_hash_limit)
        files.append(
            {
                "path": relative.as_posix(),
                "suffix": suffix,
                "important": important,
                **fingerprint,
            }
        )

    return {
        "format": "psp_disc_analysis_v2",
        "disc_root": str(disc_root),
        "analysis_scope": analysis_scope,
        "game": {
            "disc_id": sfo.get("DISC_ID", ""),
            "title": sfo.get("TITLE", ""),
            "disc_version": sfo.get("DISC_VERSION", ""),
            "category": sfo.get("CATEGORY", ""),
            "system_version": sfo.get("PSP_SYSTEM_VER", ""),
        },
        "sfo": sfo,
        "file_count": len(files),
        "candidate_file_count": candidate_count,
        "files": files,
        "status": "pass",
    }
