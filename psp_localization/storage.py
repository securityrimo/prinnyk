from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psp_localization.util import atomic_write_json, sha1_file


CONFIG_NAME = ".psp_toolkit_storage.json"
WORK_DIR_NAME = "PSP_Localization_Work"
MIN_FREE_BYTES = 1024 * 1024 * 1024


class StorageError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expand(path: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".psp_write_test_{os.getpid()}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_root_from_candidate(candidate: Path) -> Path:
    candidate = _expand(candidate)
    if candidate.name.casefold() == WORK_DIR_NAME.casefold():
        return candidate
    return candidate / WORK_DIR_NAME


def _hard_candidates() -> list[Path]:
    user = os.environ.get("USER") or Path.home().name
    values = [
        os.environ.get("PSP_TOOLKIT_DATA_ROOT", ""),
        os.environ.get("PSP_D_ROOT", ""),
        f"/media/{user}/D",
        f"/media/{user}/D_DRIVE",
        f"/run/media/{user}/D",
        f"/run/media/{user}/D_DRIVE",
        "/mnt/D",
        "/mnt/d",
        "/D",
    ]
    return [_expand(value) for value in values if value]


def _lsblk_candidates() -> list[Path]:
    command = shutil.which("lsblk")
    if not command:
        return []
    try:
        process = subprocess.run(
            [command, "-J", "-o", "LABEL,MOUNTPOINTS,MOUNTPOINT,NAME"],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            return []
        payload = json.loads(process.stdout)
    except (OSError, json.JSONDecodeError):
        return []

    found: list[Path] = []

    def visit(node: dict[str, Any]) -> None:
        label = str(node.get("label") or "").strip().rstrip(":").casefold()
        mountpoints = node.get("mountpoints") or []
        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        fallback = node.get("mountpoint")
        if fallback:
            mountpoints = list(mountpoints) + [fallback]
        if label in {"d", "d_drive", "data", "games"}:
            for item in mountpoints:
                if item:
                    found.append(_expand(item))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for device in payload.get("blockdevices") or []:
        if isinstance(device, dict):
            visit(device)
    return found


def load_storage_config(project_root: Path) -> dict[str, Any] | None:
    path = project_root / CONFIG_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data_root = payload.get("data_root")
    if not data_root:
        return None
    root = _expand(data_root)
    if not root.is_dir() or not _is_writable_directory(root):
        return None
    return payload


def detect_external_data_root(
    project_root: Path,
    *,
    requested: Path | None = None,
    minimum_free_bytes: int = MIN_FREE_BYTES,
) -> tuple[Path, str]:
    candidates: list[tuple[Path, str]] = []
    if requested is not None:
        candidates.append((_expand(requested), "requested"))

    existing = load_storage_config(project_root)
    if existing:
        candidates.append((_expand(existing["data_root"]), "config"))

    candidates.extend((path, "candidate") for path in _hard_candidates())
    candidates.extend((path, "lsblk") for path in _lsblk_candidates())

    seen: set[Path] = set()
    failures: list[str] = []
    for candidate, source in candidates:
        data_root = _data_root_from_candidate(candidate)
        if data_root in seen:
            continue
        seen.add(data_root)
        parent = data_root if data_root.exists() else data_root.parent
        if not parent.exists():
            failures.append(f"없음: {candidate}")
            continue
        if not _is_writable_directory(data_root):
            failures.append(f"쓰기 불가: {data_root}")
            continue
        try:
            free = shutil.disk_usage(data_root).free
        except OSError:
            failures.append(f"용량 확인 실패: {data_root}")
            continue
        if free < minimum_free_bytes:
            failures.append(f"여유 공간 부족: {data_root} ({free} bytes)")
            continue
        return data_root, source

    detail = "\n  - ".join(failures[:12]) if failures else "후보를 찾지 못했습니다."
    raise StorageError(
        "D: 드라이브의 Linux 마운트 경로를 자동으로 찾지 못했습니다.\n"
        "PSP_D_ROOT=/media/$USER/D 처럼 지정할 수 있습니다.\n"
        f"확인 내용:\n  - {detail}"
    )


def _copy_verified_then_remove(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return {"status": "already_external", "source": str(source), "destination": str(destination)}

    if destination.exists():
        if destination.stat().st_size != source.stat().st_size:
            raise StorageError(f"대상 파일이 이미 있지만 크기가 다릅니다: {destination}")
        if sha1_file(destination) != sha1_file(source):
            raise StorageError(f"대상 파일이 이미 있지만 내용이 다릅니다: {destination}")
        source.unlink()
        return {"status": "deduplicated", "source": str(source), "destination": str(destination)}

    temporary = destination.with_name(destination.name + ".moving")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    if temporary.stat().st_size != source.stat().st_size:
        temporary.unlink(missing_ok=True)
        raise StorageError("game2.iso 복사 후 크기 검증에 실패했습니다.")
    source_hash = sha1_file(source)
    copied_hash = sha1_file(temporary)
    if source_hash != copied_hash:
        temporary.unlink(missing_ok=True)
        raise StorageError("game2.iso 복사 후 SHA-1 검증에 실패했습니다.")
    os.replace(temporary, destination)
    source.unlink()
    return {
        "status": "moved_verified",
        "source": str(source),
        "destination": str(destination),
        "sha1": source_hash,
        "size": destination.stat().st_size,
    }


def _link_game2(project_root: Path, destination: Path) -> dict[str, Any]:
    link = project_root / "game2.iso"
    if link.is_symlink():
        current = link.resolve(strict=False)
        if current == destination.resolve():
            return {"status": "already_linked", "path": str(link), "target": str(destination)}
        link.unlink()
    elif link.exists():
        raise StorageError(f"game2.iso가 일반 파일로 남아 있어 링크를 만들 수 없습니다: {link}")
    relative = os.path.relpath(destination, start=project_root)
    link.symlink_to(relative)
    return {"status": "linked", "path": str(link), "target": str(destination)}


def prepare_external_storage(
    project_root: Path,
    *,
    requested: Path | None = None,
    migrate_game2: bool = True,
) -> dict[str, Any]:
    project_root = project_root.expanduser().resolve()
    data_root, detected_by = detect_external_data_root(project_root, requested=requested)

    inputs = data_root / "inputs"
    run_dir = data_root / "workspace" / "psp_toolkit"
    report_dir = data_root / "reports" / "psp_toolkit"
    qa_report_dir = data_root / "reports" / "prinny_qa"
    temp_dir = data_root / "tmp"
    for path in (inputs, run_dir, report_dir, qa_report_dir, temp_dir):
        path.mkdir(parents=True, exist_ok=True)

    game2_destination = inputs / "game2.iso"
    migration: dict[str, Any] = {"status": "not_requested"}
    source = project_root / "game2.iso"
    if migrate_game2:
        if source.is_symlink():
            resolved = source.resolve(strict=False)
            if resolved.is_file() and resolved != game2_destination.resolve():
                migration = _copy_verified_then_remove(resolved, game2_destination)
                source.unlink(missing_ok=True)
            elif resolved == game2_destination.resolve():
                migration = {"status": "already_external", "destination": str(game2_destination)}
            else:
                source.unlink(missing_ok=True)
                migration = {"status": "broken_link_removed"}
        elif source.is_file():
            migration = _copy_verified_then_remove(source, game2_destination)
        elif game2_destination.is_file():
            migration = {"status": "already_external", "destination": str(game2_destination)}
        else:
            migration = {"status": "game2_missing", "expected": str(game2_destination)}

    link_result: dict[str, Any] = {"status": "not_created"}
    if game2_destination.is_file():
        link_result = _link_game2(project_root, game2_destination)

    config = {
        "format": "psp_toolkit_storage_v3",
        "updated_at": _now(),
        "project_root": str(project_root),
        "detected_by": detected_by,
        "data_root": str(data_root),
        "inputs_dir": str(inputs),
        "run_dir": str(run_dir),
        "report_dir": str(report_dir),
        "qa_report_dir": str(qa_report_dir),
        "temp_dir": str(temp_dir),
        "game2_iso": str(game2_destination),
        "free_bytes": shutil.disk_usage(data_root).free,
        "migration": migration,
        "link": link_result,
    }
    atomic_write_json(project_root / CONFIG_NAME, config)
    atomic_write_json(report_dir / "storage.json", config)
    return config


def runtime_paths(project_root: Path) -> dict[str, Path]:
    config = load_storage_config(project_root)
    if not config:
        return {
            "data_root": project_root / "workspace",
            "run_dir": project_root / "workspace" / "psp_toolkit",
            "report_dir": project_root / "workspace" / "reports" / "psp_toolkit",
            "qa_report_dir": project_root / "workspace" / "reports" / "prinny_qa",
            "game2_iso": project_root / "game2.iso",
        }
    return {
        "data_root": _expand(config["data_root"]),
        "run_dir": _expand(config["run_dir"]),
        "report_dir": _expand(config["report_dir"]),
        "qa_report_dir": _expand(config["qa_report_dir"]),
        "game2_iso": _expand(config["game2_iso"]),
    }
