#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import shutil
import struct
import subprocess

import core.font_builder as builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent

GALMURI = (
    Path.home()
    / ".local/share/fonts/Galmuri14.ttf"
)

ALLOCATION = (
    ROOT
    / "workspace/font/audited_allocation_977/"
    / "hangul_allocation.json"
)

FONT_PATCHES = (
    ROOT
    / "workspace/translations/"
    / "font_build_test.json"
)

V4_START = (
    ROOT
    / "workspace/build/"
    / "final_system_csv_revision_977_v4/"
    / "start.dat"
)

V4_SYSTEM = (
    ROOT
    / "workspace/build/"
    / "final_system_csv_revision_977_v4/"
    / "SYSTEM.DAT"
)

V4_ISO = (
    ROOT
    / "workspace/build/"
    / "prinny_korean_v4_977.iso"
)

V4_ISO_REPORT = (
    ROOT
    / "workspace/reports/"
    / "csv_revision_v4_iso_injection_977.json"
)

FONT_SOURCE_DIR = (
    ROOT
    / "workspace/build/"
    / "galmuri14_font_source_977_v5"
)

OUTPUT_DIR = (
    ROOT
    / "workspace/build/"
    / "final_system_galmuri14_977_v5"
)

OUTPUT_START = OUTPUT_DIR / "start.dat"
OUTPUT_LZS = OUTPUT_DIR / "start.lzs"
OUTPUT_SYSTEM = OUTPUT_DIR / "SYSTEM.DAT"
OUTPUT_TXP = OUTPUT_DIR / "font.txp"
OUTPUT_PREVIEW = OUTPUT_DIR / "preview.png"

OUTPUT_ISO = (
    ROOT
    / "workspace/build/"
    / "prinny_korean_galmuri14_v5_977.iso"
)

OUTPUT_REPORT = (
    ROOT
    / "workspace/reports/"
    / "galmuri14_v5_build_977.json"
)

EXPECTED = {
    V4_START:
        "e5fc0593d0e6a13111e19cbb269489fa2c9db797",
    V4_SYSTEM:
        "c234429e1374e67ee839b3565fd51559f687ef05",
    V4_ISO:
        "e361967aa6f125d02f5b31e2a14c993e1ab3874f",
    ALLOCATION:
        "3e69f5f3d4fa8a9d7e196539d70dec3d38218713",
}

OLD_NOTO_TXP_SHA1 = (
    "1dc85fda2a335c7ac7704f1814de7e7dc69300ef"
)


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def hash_range(
    path: Path,
    start: int,
    end: int,
) -> str:
    digest = hashlib.sha1()
    remaining = end - start

    with path.open("rb") as file:
        file.seek(start)

        while remaining:
            block = file.read(
                min(1024 * 1024, remaining)
            )

            if not block:
                raise ValueError(
                    f"범위 읽기 실패: {path}"
                )

            digest.update(block)
            remaining -= len(block)

    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"필수 파일 없음: {path}"
        )


def resource_map(data: bytes):
    records = builder.parse_start_records(data)

    return (
        records,
        {
            str(record["name"]).casefold():
                record
            for record in records
        },
    )


def resource_blob(
    data: bytes,
    record,
) -> bytes:
    return builder.resource_blob(
        data,
        record,
    )


def verify_expected_hashes() -> None:
    for path, expected in EXPECTED.items():
        require_file(path)
        actual = sha1_file(path)

        print(
            f"VERIFY {path.relative_to(ROOT)}\n"
            f"  sha1: {actual}"
        )

        if actual != expected:
            raise ValueError(
                "보호된 입력의 SHA1 불일치: "
                f"{path}\n"
                f"expected={expected}\n"
                f"actual={actual}"
            )


def build_galmuri_font_texture() -> bytes:
    """Render only the font texture from the already-translated START.

    V6.2 called ``core.font_builder.build_font_patch`` with the translated
    V4 START.  That helper also reapplies every Japanese->Korean text patch,
    so it correctly rejected Demo00.dat+0x1C because the V4 resource already
    contained mapped Korean bytes.  This V6.2 path deliberately performs a
    font-only Expected Write: it reads font.fnt/font.txp, replaces exactly the
    allocated glyph slots, and never touches a dialogue resource.
    """
    require_file(V4_START)
    require_file(ALLOCATION)
    require_file(GALMURI)

    allocation = json.loads(
        ALLOCATION.read_text(encoding="utf-8-sig")
    )
    if allocation.get("status") != "pass":
        raise ValueError("한글 배정표 상태가 pass가 아닙니다.")
    allocations = allocation.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        raise ValueError("한글 배정표에 allocations가 없습니다.")

    if FONT_SOURCE_DIR.exists():
        shutil.rmtree(FONT_SOURCE_DIR)
    FONT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    original_start = V4_START.read_bytes()
    records, record_map = resource_map(original_start)
    fnt_record = record_map.get("font.fnt")
    txp_record = record_map.get("font.txp")
    if fnt_record is None or txp_record is None:
        raise ValueError("START에서 font.fnt/font.txp를 찾지 못했습니다.")

    original_fnt = resource_blob(original_start, fnt_record)
    original_txp = resource_blob(original_start, txp_record)
    table_count = builder.read_u16(original_fnt, 0)
    width = builder.read_u16(original_txp, 0x00)
    height = builder.read_u16(original_txp, 0x02)
    if width != 20:
        raise ValueError(f"예상하지 못한 TXP 너비: {width}")

    patched_txp = bytearray(original_txp)
    seen_glyphs: set[int] = set()
    glyph_results: list[dict] = []
    preview_items = []

    for number, item in enumerate(allocations, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"allocations[{number - 1}]가 객체가 아닙니다.")
        hangul = str(item.get("hangul", ""))
        sjis = bytes.fromhex(str(item.get("sjis", "")))
        table_index = int(item["table_index"])
        glyph_index = int(item["glyph_index"])
        if len(hangul) != 1 or len(sjis) != 2:
            raise ValueError(f"잘못된 한글 배정 항목: {item}")
        calculated_table = builder.table_index_from_sjis(sjis[0], sjis[1])
        if calculated_table != table_index:
            raise ValueError(
                f"{hangul} 테이블 인덱스 불일치: "
                f"map=0x{table_index:04X}, calculated=0x{calculated_table:04X}"
            )
        if not 0 <= table_index < table_count:
            raise ValueError(f"{hangul} 테이블 인덱스가 범위를 벗어났습니다.")
        actual_glyph = builder.read_u16(original_fnt, 2 + table_index * 2)
        if actual_glyph != glyph_index:
            raise ValueError(
                f"{hangul}의 font.fnt 매핑 불일치: "
                f"expected=0x{glyph_index:04X}, actual=0x{actual_glyph:04X}"
            )
        if glyph_index in seen_glyphs:
            raise ValueError(f"중복 글리프 슬롯: 0x{glyph_index:04X}")
        seen_glyphs.add(glyph_index)

        glyph_offset = builder.TXP_PIXEL_OFFSET + glyph_index * builder.BYTES_PER_GLYPH
        glyph_end = glyph_offset + builder.BYTES_PER_GLYPH
        if glyph_end > len(patched_txp):
            raise ValueError(f"{hangul} 글리프 슬롯이 TXP 범위를 벗어났습니다.")

        pixels, preview = builder.render_character(GALMURI, hangul)
        encoded_glyph = builder.encode_4bpp(pixels)
        if len(encoded_glyph) != builder.BYTES_PER_GLYPH:
            raise ValueError(f"{hangul} 글리프 크기 오류: {len(encoded_glyph)}")
        before = bytes(patched_txp[glyph_offset:glyph_end])
        changed_bytes = sum(a != b for a, b in zip(before, encoded_glyph))
        patched_txp[glyph_offset:glyph_end] = encoded_glyph

        # The full 977-glyph preview would be extremely wide.  A deterministic
        # 48-glyph sample is enough for a visual smoke check and saves space.
        if len(preview_items) < 48:
            preview_items.append((hangul, preview))
        glyph_results.append({
            "hangul": hangul,
            "sjis": sjis.hex(" ").upper(),
            "table_index": table_index,
            "glyph_index": glyph_index,
            "glyph_offset": glyph_offset,
            "changed_bytes": changed_bytes,
            "glyph_sha1": sha1_bytes(encoded_glyph),
        })

    if len(patched_txp) != len(original_txp):
        raise ValueError("font.txp 크기가 변경됐습니다.")
    if builder.read_u16(patched_txp, 0x00) != width or builder.read_u16(patched_txp, 0x02) != height:
        raise ValueError("font.txp 헤더가 변경됐습니다.")

    txp = bytes(patched_txp)
    txp_path = FONT_SOURCE_DIR / "font.txp"
    preview_path = FONT_SOURCE_DIR / "preview.png"
    manifest_path = FONT_SOURCE_DIR / "manifest.json"
    txp_path.write_bytes(txp)
    builder.save_preview_sheet(preview_items, preview_path)
    manifest = {
        "format": "prinny_galmuri14_font_only_v1",
        "mode": "font_only_expected_write",
        "font_path": str(GALMURI.resolve()),
        "source_start": str(V4_START),
        "source_start_sha1": sha1_bytes(original_start),
        "source_txp_sha1": sha1_bytes(original_txp),
        "output_txp_sha1": sha1_bytes(txp),
        "glyph_count": len(glyph_results),
        "changed_glyph_count": sum(1 for item in glyph_results if item["changed_bytes"]),
        "dialogue_resources_modified": 0,
        "glyphs": glyph_results,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if sha1_bytes(txp) == OLD_NOTO_TXP_SHA1:
        raise ValueError("Galmuri14 TXP가 기존 Noto TXP와 동일합니다.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if preview_path.is_file():
        shutil.copyfile(preview_path, OUTPUT_PREVIEW)
    return txp

def replace_font_in_v4_start(
    galmuri_txp: bytes,
) -> tuple[bytes, dict]:
    original = V4_START.read_bytes()
    original_records, original_map = (
        resource_map(original)
    )

    original_txp_record = (
        original_map.get("font.txp")
    )

    if original_txp_record is None:
        raise ValueError(
            "V4 START에서 font.txp를 "
            "찾지 못했습니다."
        )

    original_txp = resource_blob(
        original,
        original_txp_record,
    )

    if len(galmuri_txp) != len(original_txp):
        raise ValueError(
            "font.txp 크기 변경: "
            f"old={len(original_txp)}, "
            f"new={len(galmuri_txp)}"
        )

    rebuilt = builder.rebuild_start_archive(
        original,
        original_records,
        {
            "font.txp": galmuri_txp,
        },
    )

    rebuilt_records, rebuilt_map = (
        resource_map(rebuilt)
    )

    if len(rebuilt) != len(original):
        raise ValueError(
            "START 크기가 변경됐습니다."
        )

    if len(rebuilt_records) != len(
        original_records
    ):
        raise ValueError(
            "START 리소스 수가 변경됐습니다."
        )

    changed_resources = []

    for original_record in original_records:
        name = str(
            original_record["name"]
        ).casefold()

        rebuilt_record = rebuilt_map.get(name)

        if rebuilt_record is None:
            raise ValueError(
                f"재구성 후 리소스 누락: {name}"
            )

        before = resource_blob(
            original,
            original_record,
        )
        after = resource_blob(
            rebuilt,
            rebuilt_record,
        )

        if before != after:
            changed_resources.append(name)

    if changed_resources != ["font.txp"]:
        raise ValueError(
            "font.txp 외 리소스가 변경됐습니다: "
            + ", ".join(changed_resources)
        )

    StartRuntimeArchive.load_bytes = None

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_START.write_bytes(rebuilt)
    OUTPUT_TXP.write_bytes(galmuri_txp)

    StartRuntimeArchive.load(
        OUTPUT_START
    )

    return rebuilt, {
        "original_txp_sha1":
            sha1_bytes(original_txp),
        "galmuri_txp_sha1":
            sha1_bytes(galmuri_txp),
        "changed_resources":
            changed_resources,
    }


def repack_system(
    rebuilt_start: bytes,
) -> tuple[bytes, dict]:
    original = V4_SYSTEM.read_bytes()
    entry = builder.parse_nispack_start_entry(
        original
    )

    entry_offset = int(
        entry["entry_offset"]
    )
    old_offset = int(
        entry["data_offset"]
    )
    old_size = int(
        entry["size"]
    )

    old_lzs = original[
        old_offset:
        old_offset + old_size
    ]

    extension = old_lzs[0:4]
    flag = (
        builder.read_u32(
            old_lzs,
            0x0C,
        )
        & 0xFF
    )

    new_lzs = builder.build_literal_lzs(
        rebuilt_start,
        extension,
        flag,
    )

    decoded, _ = decompress_buffer(
        new_lzs
    )

    if decoded != rebuilt_start:
        raise ValueError(
            "새 LZS 왕복 검증 실패"
        )

    print(
        "LZS CAPACITY\n"
        f"  old : {old_size}\n"
        f"  new : {len(new_lzs)}\n"
        f"  free: {old_size - len(new_lzs)}"
    )

    if len(new_lzs) > old_size:
        raise ValueError(
            "Galmuri14 LZS가 기존 V4 영역보다 "
            "큽니다. ISO 확장 없이 주입할 수 "
            "없습니다."
        )

    patched = bytearray(original)

    patched[
        old_offset:
        old_offset + old_size
    ] = (
        new_lzs
        + b"\x00"
        * (old_size - len(new_lzs))
    )

    struct.pack_into(
        "<I",
        patched,
        entry_offset + 0x24,
        len(new_lzs),
    )

    result = bytes(patched)

    if len(result) != len(original):
        raise ValueError(
            "SYSTEM.DAT 크기가 변경됐습니다."
        )

    verified_entry = (
        builder.parse_nispack_start_entry(
            result
        )
    )

    verified_offset = int(
        verified_entry["data_offset"]
    )
    verified_size = int(
        verified_entry["size"]
    )

    if verified_offset != old_offset:
        raise ValueError(
            "start.lzs 오프셋이 변경됐습니다."
        )

    verified_start, _ = decompress_buffer(
        result[
            verified_offset:
            verified_offset + verified_size
        ]
    )

    if verified_start != rebuilt_start:
        raise ValueError(
            "SYSTEM.DAT 내부 START 검증 실패"
        )

    allowed = [
        (
            entry_offset + 0x24,
            entry_offset + 0x28,
        ),
        (
            old_offset,
            old_offset + old_size,
        ),
    ]

    unexpected = 0

    for index, (before, after) in enumerate(
        zip(original, result)
    ):
        if before == after:
            continue

        if not any(
            start <= index < end
            for start, end in allowed
        ):
            unexpected += 1

    if unexpected:
        raise ValueError(
            "SYSTEM.DAT 보호 영역 변경 감지: "
            f"{unexpected}"
        )

    OUTPUT_LZS.write_bytes(new_lzs)
    OUTPUT_SYSTEM.write_bytes(result)

    return result, {
        "entry_offset": entry_offset,
        "lzs_offset": old_offset,
        "old_lzs_size": old_size,
        "new_lzs_size": len(new_lzs),
        "remaining_capacity":
            old_size - len(new_lzs),
        "unexpected_change_count":
            unexpected,
    }


def inject_iso(
    new_system: bytes,
) -> dict:
    report = json.loads(
        V4_ISO_REPORT.read_text(
            encoding="utf-8-sig"
        )
    )

    lba = int(
        report["new_system_lba"]
    )
    sector_size = 2048
    offset = lba * sector_size

    old_system = V4_SYSTEM.read_bytes()

    if len(new_system) != len(old_system):
        raise ValueError(
            "ISO 무수정 목차 주입에는 "
            "SYSTEM.DAT 크기가 같아야 합니다."
        )

    iso_size = V4_ISO.stat().st_size
    region_end = offset + len(old_system)

    if region_end > iso_size:
        raise ValueError(
            "SYSTEM.DAT ISO 영역이 파일 범위를 "
            "벗어납니다."
        )

    with V4_ISO.open("rb") as source:
        source.seek(offset)
        embedded = source.read(
            len(old_system)
        )

    if embedded != old_system:
        raise ValueError(
            "V4 ISO 내부 SYSTEM.DAT가 "
            "검증된 입력과 다릅니다."
        )

    with V4_ISO.open("rb") as source:
        with OUTPUT_ISO.open("wb") as target:
            shutil.copyfileobj(
                source,
                target,
                1024 * 1024,
            )

    with OUTPUT_ISO.open("r+b") as target:
        target.seek(offset)
        target.write(new_system)
        target.flush()

    if OUTPUT_ISO.stat().st_size != iso_size:
        raise ValueError(
            "ISO 크기가 변경됐습니다."
        )

    with OUTPUT_ISO.open("rb") as file:
        file.seek(offset)
        verified = file.read(
            len(new_system)
        )

    if verified != new_system:
        raise ValueError(
            "ISO 내부 SYSTEM.DAT 검증 실패"
        )

    source_prefix = hash_range(
        V4_ISO,
        0,
        offset,
    )
    output_prefix = hash_range(
        OUTPUT_ISO,
        0,
        offset,
    )

    source_suffix = hash_range(
        V4_ISO,
        region_end,
        iso_size,
    )
    output_suffix = hash_range(
        OUTPUT_ISO,
        region_end,
        iso_size,
    )

    if source_prefix != output_prefix:
        raise ValueError(
            "ISO의 SYSTEM 이전 영역이 "
            "변경됐습니다."
        )

    if source_suffix != output_suffix:
        raise ValueError(
            "ISO의 SYSTEM 이후 영역이 "
            "변경됐습니다."
        )

    archive_test = subprocess.run(
        [
            "7z",
            "t",
            str(OUTPUT_ISO),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if archive_test.returncode != 0:
        raise RuntimeError(
            "7z ISO 검사 실패:\n"
            + archive_test.stdout[-2000:]
            + archive_test.stderr[-2000:]
        )

    return {
        "system_lba": lba,
        "system_offset": offset,
        "system_size": len(new_system),
        "iso_size": iso_size,
        "prefix_unchanged": True,
        "suffix_unchanged": True,
        "archive_test_returncode":
            archive_test.returncode,
    }


def launch_ppsspp() -> int:
    command = [
        "flatpak",
        "run",
        f"--filesystem={ROOT}:ro",
        "org.ppsspp.PPSSPP",
        "--graphics=software",
        "--windowed",
        "--escape-exit",
        "--xres",
        "960",
        "--yres",
        "544",
        str(OUTPUT_ISO),
    ]

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return process.pid


def main() -> int:
    print("PRINNY GALMURI14 V5 BUILD")
    print("=" * 100)

    for path in (
        GALMURI,
        FONT_PATCHES,
        V4_ISO_REPORT,
    ):
        require_file(path)

    verify_expected_hashes()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_REPORT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("1/5 Galmuri14 TXP 생성")
    galmuri_txp = (
        build_galmuri_font_texture()
    )

    print()
    print("2/5 V4 START 폰트 교체")
    rebuilt_start, font_result = (
        replace_font_in_v4_start(
            galmuri_txp
        )
    )

    print()
    print("3/5 V4 SYSTEM.DAT 재패킹")
    new_system, system_result = (
        repack_system(
            rebuilt_start
        )
    )

    print()
    print("4/5 V4 ISO에 SYSTEM.DAT 주입")
    iso_result = inject_iso(
        new_system
    )

    report = {
        "format":
            "prinny_galmuri14_v5_build_977_v1",
        "status": "pass",
        "font": {
            "path": str(GALMURI),
            "size": GALMURI.stat().st_size,
            "sha1": sha1_file(GALMURI),
        },
        "allocation": {
            "path": str(ALLOCATION),
            "sha1": sha1_file(ALLOCATION),
        },
        "font_result": font_result,
        "system_result": system_result,
        "iso_result": iso_result,
        "outputs": {
            "start": str(OUTPUT_START),
            "start_sha1":
                sha1_file(OUTPUT_START),
            "font_txp": str(OUTPUT_TXP),
            "font_txp_sha1":
                sha1_file(OUTPUT_TXP),
            "system": str(OUTPUT_SYSTEM),
            "system_sha1":
                sha1_file(OUTPUT_SYSTEM),
            "iso": str(OUTPUT_ISO),
            "iso_sha1":
                sha1_file(OUTPUT_ISO),
            "preview": str(OUTPUT_PREVIEW),
        },
        "errors": [],
    }

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("5/5 PPSSPP 실행")
    pid = launch_ppsspp()

    print()
    print("=" * 100)
    print("PASS")
    print(f"FONT   : {GALMURI}")
    print(
        f"TXP    : {OUTPUT_TXP}\n"
        f"         {sha1_file(OUTPUT_TXP)}"
    )
    print(
        f"SYSTEM : {OUTPUT_SYSTEM}\n"
        f"         {sha1_file(OUTPUT_SYSTEM)}"
    )
    print(
        f"ISO    : {OUTPUT_ISO}\n"
        f"         {sha1_file(OUTPUT_ISO)}"
    )
    print(f"PREVIEW: {OUTPUT_PREVIEW}")
    print(f"REPORT : {OUTPUT_REPORT}")
    print(f"PPSSPP : PID {pid}")
    print("=" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
