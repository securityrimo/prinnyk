#!/usr/bin/env python3
"""Apply the public Prinny V1.3 DLC xdelta patches to extracted folders.

The xdelta source is a deterministic image made only from validated DLC file
names and bytes. ZIP metadata, parent directory names, mtimes and permissions
therefore cannot affect patch compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


MAGIC = b"PRDLCF01"
PATCH_NAMES = {
    "prinny1": "Prinny1_ULJS00150_DLC_ALL_KO_v1.3.xdelta",
    "prinny2": "Prinny2_NPJH50211_DLC_ALL_KO_v1.3.xdelta",
}
GAME_SPECS: dict[str, dict[str, Any]] = {
    "prinny1": {
        "title": "프리니 1",
        "game_id": "ULJS00150",
        "source": {
            "DL0000.EDAT": "a0209702de5210b2f35c57e7c12bfddbeb691200de06769b615ca50254d48c1b",
            "DL0001.EDAT": "86b48d56b6ba853f09ffb0a524ccebf4f601c78cb0f4937cb885ec8815bdb7a7",
            "DL0002.EDAT": "3fbc26ed99c1b3f474e50dd5290eb0497e61f0a7e8e9268fb82980a426079be9",
        },
        "target": {
            "DL0000.EDAT": "83df3e9271ee95f6c4c7e7a6d3c4f1b48de990d9075ea9b0b18d3d1069ed997a",
            "DL0001.EDAT": "60c3f6884a86f77cdd17e8ef05d5aa2a5c21374e2336148d9352587c887b0aaa",
            "DL0002.EDAT": "09391b63a418a3124a2017e747affffdad0a10e6464d1037d242a6bdcd96314e",
            "PARAM.PBP": "64a9cd0c99deb76efedf25ea8182d4851bc774bbe887fb2876bb23df302d9ef3",
        },
        "known_existing": {
            "DL0000.EDAT": ["a0209702de5210b2f35c57e7c12bfddbeb691200de06769b615ca50254d48c1b"],
            "DL0001.EDAT": ["86b48d56b6ba853f09ffb0a524ccebf4f601c78cb0f4937cb885ec8815bdb7a7"],
            "DL0002.EDAT": ["3fbc26ed99c1b3f474e50dd5290eb0497e61f0a7e8e9268fb82980a426079be9"],
            "PARAM.PBP": ["b4d52c1fd59d46ae9a9f6b0d4a01dbb95f79d51e78fe7901d6a3e8051fb62b16"],
        },
    },
    "prinny2": {
        "title": "프리니 2",
        "game_id": "NPJH50211",
        "source": {
            "JP00.EDAT": "e97a92c0f2749534dd2de41de84901602d78526cbe49e444805c3a2de0e3c643",
            "RADISH.EDAT": "47cc73ff7d1347c06f7849c72b6b9485f1f913bbe7a93dbc974c3812866c67fb",
            "TICKET.EDAT": "c4bbf876ead95ecaaf059f27628b0a2e7c5a6333f63449d9e4274b1f3dc8bc99",
        },
        "target": {
            "JP00.EDAT": "1f4c869edba06cd251a1235fcdc4d70d1d52b41804c6933b370edc223081077d",
            "PARAM.PBP": "9d1c690bba2df13ab5694316ff7d38c0d068538e28cc3de09184564c52f2f5f8",
            "RADISH.EDAT": "47cc73ff7d1347c06f7849c72b6b9485f1f913bbe7a93dbc974c3812866c67fb",
            "TICKET.EDAT": "c4bbf876ead95ecaaf059f27628b0a2e7c5a6333f63449d9e4274b1f3dc8bc99",
        },
        "known_existing": {
            "JP00.EDAT": ["e97a92c0f2749534dd2de41de84901602d78526cbe49e444805c3a2de0e3c643"],
            "PARAM.PBP": [
                "a52068a79b3f2a470d20ff17018b1977d0c9ae31196a759e25f19888fe0abf92",
                "4cd0378a1db670614fb4c0ef78525710992f2c7d740eea831eed2de87cfbd98c",
            ],
            "RADISH.EDAT": ["47cc73ff7d1347c06f7849c72b6b9485f1f913bbe7a93dbc974c3812866c67fb"],
            "TICKET.EDAT": ["c4bbf876ead95ecaaf059f27628b0a2e7c5a6333f63449d9e4274b1f3dc8bc99"],
        },
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pack_image(entries: dict[str, bytes]) -> bytes:
    """Serialize logical files without filesystem or archive metadata."""
    packed = bytearray(MAGIC)
    ordered = sorted(entries.items(), key=lambda item: item[0].encode("utf-8"))
    packed.extend(struct.pack(">H", len(ordered)))
    for name, data in ordered:
        encoded_name = name.encode("utf-8")
        if not encoded_name or len(encoded_name) > 0xFFFF or Path(name).name != name:
            raise ValueError(f"잘못된 논리 파일명: {name!r}")
        packed.extend(struct.pack(">H", len(encoded_name)))
        packed.extend(encoded_name)
        packed.extend(struct.pack(">Q", len(data)))
        packed.extend(hashlib.sha256(data).digest())
        packed.extend(data)
    return bytes(packed)


def unpack_image(image: bytes) -> dict[str, bytes]:
    if not image.startswith(MAGIC) or len(image) < len(MAGIC) + 2:
        raise ValueError("DLC 결과 이미지 형식이 올바르지 않습니다.")
    offset = len(MAGIC)
    count = struct.unpack_from(">H", image, offset)[0]
    offset += 2
    entries: dict[str, bytes] = {}
    for _ in range(count):
        if offset + 2 > len(image):
            raise ValueError("DLC 결과 이미지가 잘렸습니다.")
        name_size = struct.unpack_from(">H", image, offset)[0]
        offset += 2
        if offset + name_size + 40 > len(image):
            raise ValueError("DLC 결과 이미지가 잘렸습니다.")
        name = image[offset : offset + name_size].decode("utf-8")
        offset += name_size
        size = struct.unpack_from(">Q", image, offset)[0]
        offset += 8
        expected = image[offset : offset + 32]
        offset += 32
        if offset + size > len(image):
            raise ValueError("DLC 결과 파일 데이터가 잘렸습니다.")
        data = image[offset : offset + size]
        offset += size
        if Path(name).name != name or name in entries:
            raise ValueError(f"DLC 결과 이미지의 파일명이 올바르지 않습니다: {name!r}")
        if hashlib.sha256(data).digest() != expected:
            raise ValueError(f"DLC 결과 이미지 내부 해시 불일치: {name}")
        entries[name] = data
    if offset != len(image):
        raise ValueError("DLC 결과 이미지 뒤에 알 수 없는 데이터가 있습니다.")
    return entries


def collect_source_entries(source: Path, expected: dict[str, str]) -> tuple[dict[str, bytes], dict[str, str]]:
    if not source.is_dir():
        raise ValueError("원본 DLC ZIP을 먼저 풀고, 압축을 푼 폴더를 지정하십시오.")
    entries: dict[str, bytes] = {}
    paths: dict[str, str] = {}
    all_files = [path for path in source.rglob("*") if path.is_file()]
    for name, expected_hash in expected.items():
        candidates = [path for path in all_files if path.name.casefold() == name.casefold()]
        valid: list[tuple[Path, bytes]] = []
        invalid: list[Path] = []
        for candidate in candidates:
            data = candidate.read_bytes()
            if sha256_bytes(data) == expected_hash:
                valid.append((candidate, data))
            else:
                invalid.append(candidate)
        if not valid:
            raise ValueError(f"{source}: SHA-256이 일치하는 원본 {name}을 찾지 못했습니다.")
        if invalid:
            listed = ", ".join(str(path) for path in invalid)
            raise ValueError(f"{source}: 내용이 다른 {name} 후보가 함께 있습니다: {listed}")
        unique = {sha256_bytes(data) for _, data in valid}
        if len(unique) != 1:
            raise ValueError(f"{source}: 서로 다른 {name} 원본이 함께 있습니다.")
        entries[name] = valid[0][1]
        paths[name] = str(valid[0][0])
    return entries, paths


def xdelta_executable(patch_dir: Path) -> str:
    local_names = ("xdelta3.exe", "xdelta3") if os.name == "nt" else ("xdelta3", "xdelta3.exe")
    for name in local_names:
        candidate = patch_dir / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("xdelta3")
    if found:
        return found
    raise FileNotFoundError(
        "xdelta3를 찾을 수 없습니다. xdelta3 또는 xdelta3.exe를 설치하거나 패치 폴더에 넣으십시오."
    )


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def apply_folder_patch(game: str, source: Path, output_root: Path, patch_dir: Path) -> dict[str, Any]:
    spec = GAME_SPECS[game]
    source = source.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    patch_dir = patch_dir.expanduser().resolve()
    if not source.is_dir():
        raise ValueError("원본 DLC ZIP을 먼저 풀고, 압축을 푼 폴더를 지정하십시오.")
    if is_within(output_root, source):
        raise ValueError("원본 폴더 또는 그 하위에는 출력할 수 없습니다. 별도 출력 폴더를 지정하십시오.")

    source_entries, source_paths = collect_source_entries(source, spec["source"])
    source_image = pack_image(source_entries)
    patch = patch_dir / PATCH_NAMES[game]
    if not patch.is_file():
        raise FileNotFoundError(f"DLC xdelta 파일이 없습니다: {patch}")
    xdelta = xdelta_executable(patch_dir)

    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{game}_dlc_v1_3_", dir=output_root))
    try:
        source_image_path = stage / "source.pfdimg"
        target_image_path = stage / "target.pfdimg"
        source_image_path.write_bytes(source_image)
        process = subprocess.run(
            [xdelta, "-d", "-f", "-s", str(source_image_path), str(patch), str(target_image_path)],
            capture_output=True,
            text=True,
        )
        if process.returncode:
            message = process.stderr.strip() or process.stdout.strip()
            raise RuntimeError(f"DLC xdelta 적용 실패: {message}")
        target_image = target_image_path.read_bytes()
        target_entries = unpack_image(target_image)
        if set(target_entries) != set(spec["target"]):
            raise ValueError("DLC 결과 이미지의 파일 목록이 예상과 다릅니다.")
        for name, expected_hash in spec["target"].items():
            actual = sha256_bytes(target_entries[name])
            if actual != expected_hash:
                raise ValueError(f"{name}: 결과 SHA-256 불일치: {actual} != {expected_hash}")

        install_dir = output_root / "PSP" / "GAME" / spec["game_id"]
        for name, expected_hash in spec["target"].items():
            destination = install_dir / name
            if not destination.exists():
                continue
            actual = sha256_path(destination)
            accepted = set(spec["known_existing"].get(name, [])) | {expected_hash}
            if actual not in accepted:
                raise ValueError(f"기존 출력 파일이 알려진 원본/한국어판과 다릅니다: {destination}: {actual}")

        staged_install = stage / "install"
        staged_install.mkdir()
        for name, data in target_entries.items():
            (staged_install / name).write_bytes(data)
        install_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(target_entries):
            os.replace(staged_install / name, install_dir / name)

        final_hashes = {name: sha256_path(install_dir / name) for name in sorted(spec["target"])}
        report = {
            "format": "prinny_dlc_extracted_folder_apply_v1",
            "status": "PASS",
            "release": "v1.3",
            "game": game,
            "game_id": spec["game_id"],
            "source_folder": str(source),
            "source_files": source_paths,
            "source_image_sha256": sha256_bytes(source_image),
            "patch": patch.name,
            "patch_sha256": sha256_path(patch),
            "install_directory": str(install_dir),
            "output_files": final_hashes,
            "zip_or_filesystem_metadata_used": False,
        }
        (output_root / f"apply_report_{game}_dlc_v1.3.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="프리니 1·2 V1.3 압축 해제 DLC 폴더 패치 적용기")
    parser.add_argument("game", choices=sorted(GAME_SPECS), help="prinny1 또는 prinny2")
    parser.add_argument("source", nargs="?", type=Path, help="압축을 푼 원본 DLC 폴더")
    parser.add_argument("output", nargs="?", type=Path, help="새 PSP/GAME 구조를 만들 출력 폴더")
    parser.add_argument("--patch-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()

    source = args.source
    if source is None:
        source = Path(input("압축을 푼 원본 DLC 폴더 경로: ").strip().strip('"'))
    output = args.output or (Path(__file__).resolve().parent / "patched_output")
    try:
        report = apply_folder_patch(args.game, source, output, args.patch_dir)
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"적용 완료: {report['install_directory']}")
    print("출력 폴더의 PSP 디렉터리를 메모리스틱 루트에 복사하십시오.")


if __name__ == "__main__":
    main()
