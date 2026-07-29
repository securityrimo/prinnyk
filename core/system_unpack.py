#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.lzs import NISLZSError, decompress_buffer
from core.nispack import NISPack
from core.start_runtime import REQUIRED_RESOURCES, StartRuntimeArchive


DEFAULT_SYSTEM = Path(
    "workspace/iso/PSP_GAME/USRDIR/SYSTEM.DAT"
)
DEFAULT_OUTPUT = Path(
    "workspace/unpack/SYSTEM_fixed"
)
DEFAULT_MANIFEST = Path(
    "workspace/reports/system_unpack_manifest.json"
)
START_LZS_NAME = "start.lzs"
START_DAT_NAME = "start.dat"


class SystemUnpackError(ValueError):
    """SYSTEM.DAT → start.lzs → start.dat 파이프라인 오류."""


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _artifact(path: Path, data: bytes, write_status: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": len(data),
        "size_hex": f"0x{len(data):X}",
        "sha1": sha1_bytes(data),
        "write_status": write_status,
    }


def _atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    force: bool,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        if not path.is_file():
            raise SystemUnpackError(
                f"출력 경로가 일반 파일이 아닙니다: {path}"
            )

        current = path.read_bytes()
        if current == data:
            return "unchanged"

        if not force:
            raise SystemUnpackError(
                "기존 출력이 새 결과와 다릅니다. "
                f"덮어쓰려면 --force를 사용하세요: {path}"
            )

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name

        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass

    return "overwritten" if force else "created"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    # manifest는 실행 결과 보고서이므로 항상 최신 내용으로 갱신한다.
    _atomic_write_bytes(path, encoded, force=True)


def _find_start_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        entry
        for entry in entries
        if str(entry.get("name", "")).casefold()
        == START_LZS_NAME.casefold()
    ]

    if not matches:
        raise SystemUnpackError(
            f"SYSTEM.DAT 목차에서 {START_LZS_NAME}를 찾지 못했습니다."
        )

    if len(matches) != 1:
        raise SystemUnpackError(
            f"{START_LZS_NAME} 엔트리가 {len(matches)}개입니다. "
            "자동 선택을 중단합니다."
        )

    entry = matches[0]
    if not entry.get("plausible", False):
        raise SystemUnpackError(
            f"{START_LZS_NAME} 엔트리 유효성 검사에 실패했습니다: "
            f"index={entry.get('index')}"
        )

    return entry


def unpack_system(
    system_path: Path | str = DEFAULT_SYSTEM,
    output_directory: Path | str = DEFAULT_OUTPUT,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    *,
    force: bool = False,
) -> dict[str, Any]:
    system_path = Path(system_path)
    output_directory = Path(output_directory)
    manifest_path = Path(manifest_path)

    if not system_path.is_file():
        raise FileNotFoundError(
            f"SYSTEM.DAT 없음: {system_path}"
        )

    pack = NISPack(system_path)
    entries = pack.parse(verbose=False)
    start_entry = _find_start_entry(entries)

    start_offset = int(start_entry["offset"])
    start_end = int(start_entry["end"])
    start_size = int(start_entry["size"])
    start_lzs = pack.data[start_offset:start_end]

    if len(start_lzs) != start_size:
        raise SystemUnpackError(
            "start.lzs 추출 크기가 목차와 일치하지 않습니다: "
            f"actual=0x{len(start_lzs):X}, "
            f"expected=0x{start_size:X}"
        )

    try:
        start_dat, lzs_header = decompress_buffer(start_lzs)
    except NISLZSError as error:
        raise SystemUnpackError(
            f"start.lzs 압축 해제 실패: {error}"
        ) from error

    extension = str(lzs_header.get("extension", "")).casefold()
    if extension != "dat":
        raise SystemUnpackError(
            "start.lzs 출력 확장자가 예상과 다릅니다: "
            f"{lzs_header.get('extension')!r}"
        )

    start_lzs_path = output_directory / START_LZS_NAME
    start_dat_path = output_directory / START_DAT_NAME

    lzs_status = _atomic_write_bytes(
        start_lzs_path,
        start_lzs,
        force=force,
    )
    dat_status = _atomic_write_bytes(
        start_dat_path,
        start_dat,
        force=force,
    )

    archive = StartRuntimeArchive.load(start_dat_path)
    required_resources = {
        name: archive.find_record(name) is not None
        for name in sorted(REQUIRED_RESOURCES)
    }
    missing_resources = [
        name
        for name, present in required_resources.items()
        if not present
    ]

    if missing_resources:
        raise SystemUnpackError(
            "생성된 start.dat에서 필수 런타임 자원을 "
            "찾지 못했습니다: "
            + ", ".join(missing_resources)
        )

    manifest: dict[str, Any] = {
        "pipeline": "SYSTEM.DAT -> start.lzs -> start.dat",
        "format": "prinny_system_unpack_v1",
        "source": {
            "path": str(system_path),
            "size": len(pack.data),
            "size_hex": f"0x{len(pack.data):X}",
            "sha1": sha1_bytes(pack.data),
        },
        "nispack": {
            "entry_count": len(entries),
            "start_entry": {
                "index": int(start_entry["index"]),
                "name": str(start_entry["name"]),
                "offset": start_offset,
                "offset_hex": f"0x{start_offset:X}",
                "size": start_size,
                "size_hex": f"0x{start_size:X}",
                "end": start_end,
                "end_hex": f"0x{start_end:X}",
                "metadata": int(start_entry["metadata"]),
                "metadata_hex": str(start_entry["metadata_hex"]),
            },
        },
        "lzs": {
            "extension": lzs_header["extension"],
            "decompressed_size": int(
                lzs_header["decompressed_size"]
            ),
            "compressed_size_field": int(
                lzs_header["compressed_size"]
            ),
            "compressed_end": int(
                lzs_header["compressed_end"]
            ),
            "flag": int(lzs_header["flag"]),
            "flag_hex": f"0x{int(lzs_header['flag']):02X}",
        },
        "outputs": {
            "start_lzs": _artifact(
                start_lzs_path,
                start_lzs,
                lzs_status,
            ),
            "start_dat": _artifact(
                start_dat_path,
                start_dat,
                dat_status,
            ),
        },
        "start_archive": {
            "record_count": len(archive.records),
            "table_end": archive.table_end,
            "table_end_hex": f"0x{archive.table_end:X}",
            "first_data_offset": archive.records[0].data_offset,
            "first_data_offset_hex": (
                f"0x{archive.records[0].data_offset:X}"
            ),
            "required_resources": required_resources,
        },
        "status": "pass",
    }

    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = str(manifest_path)
    return manifest


def run_unpack(args: argparse.Namespace) -> int:
    manifest = unpack_system(
        system_path=args.system,
        output_directory=args.output,
        manifest_path=args.manifest,
        force=args.force,
    )

    source = manifest["source"]
    entry = manifest["nispack"]["start_entry"]
    lzs = manifest["lzs"]
    outputs = manifest["outputs"]
    start_archive = manifest["start_archive"]

    print("SYSTEM.DAT UNPACK")
    print("=================")
    print("SOURCE       :", source["path"])
    print("SOURCE SIZE  :", source["size_hex"])
    print("SOURCE SHA1  :", source["sha1"])
    print("ENTRY COUNT  :", manifest["nispack"]["entry_count"])
    print(
        "START ENTRY  :",
        f"index={entry['index']}",
        f"offset={entry['offset_hex']}",
        f"size={entry['size_hex']}",
    )
    print("LZS FLAG     :", lzs["flag_hex"])
    print(
        "LZS -> DAT   :",
        f"0x{lzs['compressed_end']:X}",
        "->",
        f"0x{lzs['decompressed_size']:X}",
    )
    print(
        "START.LZS   :",
        outputs["start_lzs"]["path"],
        f"[{outputs['start_lzs']['write_status']}]",
    )
    print(
        "START.DAT   :",
        outputs["start_dat"]["path"],
        f"[{outputs['start_dat']['write_status']}]",
    )
    print("RECORD COUNT :", start_archive["record_count"])
    print("TABLE END    :", start_archive["table_end_hex"])
    print("REQUIRED     : PASS")
    print("MANIFEST     :", manifest["manifest"])
    print("SELF TEST    : PASS")

    return 0
