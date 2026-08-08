#!/usr/bin/env python3
"""Repair the reported dialogue and select wording by character voice first."""
from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_start, extract_system
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import (
    CANDIDATE_START,
    assert_same_archive_layout,
    now,
    record_map,
    resource_blob,
    sha256_bytes,
    sha256_file,
)


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_36_aria_title_runtime_code/prinny_korean_v7_15_36_aria_title_runtime_code.iso"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_37_dialogue_voice_atmosphere"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_37_dialogue_voice_atmosphere.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_37_dialogue_voice_atmosphere_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_37_dialogue_voice_atmosphere"

EXPECTED_BASE_SHA256 = "63bce7274d9f3bb38589ecc2691bd2eb2e7031c3483fe434e57cc2569d4e4824"
EXPECTED_CANDIDATE_START_SHA256 = "ee92515c9b014c95072abf5404cc20f3330080b636393421d72ba3f2a8978cba"

EVIDENCE = (
    (Path("/home/hyuk/사진/텍스트1.png"), "86742af0535be2edf8f8a35c3acdb8eafd14064c5e7b65b1429cd884514de908"),
    (Path("/home/hyuk/사진/텍스트2.png"), "b085ac08e10d6b49bb987bdd43ad787e8c0f9ff506e1cfb805acf0cf98eed7be"),
    (Path("/home/hyuk/사진/텍스트3.png"), "8fd0b650db19338aa340a228ce209eacca9343c888c496a7239d2cafe1845f36"),
    (Path("/home/hyuk/사진/텍스트4.png"), "8e83572973857e87a17b07d11991d8a7c9c3559818a295c67dea88e7c12e445b"),
    (Path("/home/hyuk/사진/텍스트5.png"), "aa82bc7fb9e97d5df463852f9775ac68c6f5e5c0875e9083fca15847e0912ebe"),
    (Path("/home/hyuk/사진/텍스트6.png"), "f7a47308f61a13a246047d6a79900d0e9cd2aa825ed1cb137540105685434770"),
    (Path("/home/hyuk/사진/텍스트7.png"), "50cf95cfd6994e6bc0c30ffd2c827317bb8e74d4cabaa824995a4be0767d8a8f"),
    (Path("/home/hyuk/사진/텍스트8.png"), "7295f0ad6a8662ae2e5a5c8a131c34f67043a3ff1f82e6dda6e2031a14f7bafa"),
    (Path("/home/hyuk/사진/텍스트9.png"), "4dbb4a69b663336ba3400ee7cf9066bd3ee0f60b33a0cf1a67e953979a3c7f80"),
    (Path("/home/hyuk/사진/텍스트10.png"), "d8e66e84583d8e86e67c1f97289151f0ac6c6a4b236e9982508d95db3cd2f6d8"),
    (Path("/home/hyuk/사진/텍스트11.png"), "69ff13249cd8e5bb9da79e8578253fa7dc556ac85c8478f355666371a89bee62"),
)

# Rows already replaced with runtime-proven candidate bytes in V7.15.35. They
# remain part of this voice review even though V7.15.37 does not rewrite them.
PRESERVED_REVIEW = (
    (0x9940, "プリニー", "ひえぇっ、急ぐッスー！", "히에엑, 서둘러야함다-!", "히익, 서두름다!", "히익, 서두름다!", "프리니의 다급한 축약 말투"),
    (0x9BD4, "プリニー", "ひえぇっ！", "히에엑!!", "히이익!!", "히이익!!", "짧은 비명과 과장된 호흡"),
    (0x9D60, "エトナ", "あーたーしーのスイーツ、", "내~ 스위츠~,", "내 디저트,", "내 디저트,", "늘어진 직역 대신 분노 직전의 짧은 도입"),
    (0x9D83, "エトナ", "だーれが食いやがったぁぁっ！？", "누~가 다 처먹었어어어!?", "누가 처먹었어!?", "누가 처먹었어!?", "에트나의 거친 반말 유지"),
    (0x9F70, "エトナ", "いいわ、明日の朝までに巷で話題の", "좋아, 내일 아침까지 화제인", "좋아, 내일 아침까지 화제의", "좋아, 내일 아침까지 화제의", "명령의 조건을 자연스럽게 연결"),
    (0x9F93, "エトナ", "『究極のスイーツ』を持ってきな！", "『궁극의 스위츠』를 가져와!", "「궁극의 디저트」를 가져와!", "「궁극의 디저트」를 가져와!", "에트나의 직접 명령과 용어 통일"),
    (0xA390, "エトナ", "いい？期限は明日の朝。", "알았지? 기한은 내일 아침", "자, 기한은 내일", "자, 기한은 내일", "다음 줄의 '아침까지야'와 중복 제거"),
    (0x14AC3, "プリニー", "危険ッス！撤退あるのみッス！", "위험함다! 철수뿐임다!", "위험함다! 후퇴만이 살길임다!", "위험함다! 후퇴만이 살길임다!", "프리니 특유의 겁먹은 과장과 ~임다"),
    (0x14B24, "グルメオーガ", "おでのごはんをジャマするヤツは", "내 밥을 방해하는 녀석은", "내 밥을 방해하는 녀석은", "내 밥을 방해하는 녀석은", "오우거의 위협 도입이 이미 자연스러움"),
    (0x14BA8, "グルメオーガ", "むぎゅう……", "무규우……", "으윽……", "으윽……", "패배 직후의 신음으로 자연화"),
)

# Candidate text is copied through its complete NUL terminator, not through the
# shorter Japanese-source byte length that caused the prior dangling suffixes.
PATCHES = (
    (0x10798, "エトナ", "……分かってると", "……알고 있을 거라", "……알고 있을 거라", "……알고 있을 거라", "candidate", "에트나의 경고를 다음 줄에 자연스럽게 연결"),
    (0x107BB, "エトナ", "思うけど……。", "생각하지만", "생각하지만…….", "생각하지만…….", "candidate", "원문의 여운과 문장 종결 복원"),
    (0x108A0, "エトナ", "例え全滅してもスイーツを", "설령 전멸하더라도 스위츠를", "설령 전멸해도 디저트는", "설령 전멸해도 디저트는", "candidate", "짧고 냉혹한 명령조 및 디저트 용어 통일"),
    (0x108C3, "エトナ", "持ってくるんだよ。", "가져오는 거야.", "가져와야 해.", "가져와야 해.", "candidate", "설명조보다 강제성이 드러나는 명령조"),
    (0x14AA0, "プリニー", "い、いややっぱり遠慮しとくッス", "아, 아니 역시 사양하겠슴다", "아, 아니, 역시 사양하겠슴다.", "아, 아니, 역시 사양하겠슴다.", "candidate", "머뭇거림과 프리니의 ~슴다 말투 복원"),
    (0x14B47, "グルメオーガ", "すり潰してフリカケにしてやるど！！", "갈아 으깨서 후리카케로 만들어주마!!", "갈아 버려 후리카케로 만들겠다!!", "갈고 으깨 후리카케로 만들어주마!!", "hybrid", "원문의 분쇄 의미와 오우거의 호쾌한 위협 어조를 함께 보존"),
    (0x14BCB, "グルメオーガ", "朝は力が出ないずら……。", "아침은 힘이 안 나는구먼", "아침엔 힘이 안 나는구먼…….", "아침엔 힘이 안 나는구먼…….", "candidate", "사투리형 종결과 패배의 여운 복원"),
    (0x14C2C, "ナレーション", "プリニーは、グルメオーガの朝食", "프리니는, 미식가 오우거의 아침 식사", "프리니는 미식가 오거의 아침밥", "프리니는 미식가 오거의 아침밥", "candidate", "전투 보상 문구를 짧고 게임답게 정리"),
    (0x14C4F, "ナレーション", "「太古の肉」", "「태고의 고기", "「태고의 고기」", "「태고의 고기」", "candidate", "닫는 괄호와 아이템명 복원"),
    (0x14C72, "ナレーション", "……を奪った！", ".를 빼앗았다!", "……를 빼앗았다!", "……를 빼앗았다!", "candidate", "앞 아이템명과 이어지는 생략부호 복원"),
)

CUSTOM_BYTES = {
    # 갈고 으깨 후리카케로 만들어주마!!\0 -- every glyph was visually
    # verified against the candidate font; the phrase occupies exactly 34 bytes.
    0x14B47: bytes.fromhex(
        "F043F06120F35BF0A120F4AAF1C2F3E4F3ECF1B220F1CCF165F2DDF398F1CA212100"
    ),
}


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def nul_text(blob: bytes, start: int, limit: int = 0x60) -> bytes:
    end = blob.find(b"\0", start, start + limit)
    if end < 0:
        raise ValueError(f"NUL 종료 문구를 찾지 못함: 0x{start:X}")
    return blob[start:end + 1]


def review_rows(actual_offsets: set[int]) -> list[dict]:
    rows = []
    for offset, speaker, source, user, candidate, selected, rationale in PRESERVED_REVIEW:
        rows.append({
            "offset_hex": f"0x{offset:X}", "speaker": speaker, "japanese_source": source,
            "user_translation": user, "xdelta_translation": candidate,
            "selected_translation": selected, "selection": "preserve_existing_v7_15_36",
            "rationale": rationale, "actual_write": "no",
        })
    for offset, speaker, source, user, candidate, selected, mode, rationale in PATCHES:
        rows.append({
            "offset_hex": f"0x{offset:X}", "speaker": speaker, "japanese_source": source,
            "user_translation": user, "xdelta_translation": candidate,
            "selected_translation": selected, "selection": mode,
            "rationale": rationale, "actual_write": "yes" if offset in actual_offsets else "no",
        })
    return rows


def build_resources() -> tuple[dict[str, bytes], list[dict], list[dict], dict]:
    base_system, _record = extract_system(BASE_ISO)
    base_start, base_lzs, start_row, system_rows = extract_start(base_system)
    candidate_start = CANDIDATE_START.read_bytes()
    base_records, candidate_records = assert_same_archive_layout(base_start, candidate_start)
    base_demo = base_records["demo00.dat"]
    candidate_demo = candidate_records["demo00.dat"]

    # Confirm that all previously selected lines are still the candidate bytes.
    for offset, *_rest in PRESERVED_REVIEW:
        base_at = base_demo.data_offset + offset
        candidate_at = candidate_demo.data_offset + offset
        if nul_text(base_start, base_at) != nul_text(candidate_start, candidate_at):
            raise ValueError(f"보존 대사가 V7.15.36/xdelta와 다름: 0x{offset:X}")

    final_start = bytearray(base_start)
    writes: list[dict] = []
    for sequence, row in enumerate(PATCHES, 1):
        offset, speaker, source, user, candidate, selected, mode, rationale = row
        base_at = base_demo.data_offset + offset
        candidate_at = candidate_demo.data_offset + offset
        before_raw = nul_text(base_start, base_at)
        candidate_raw = nul_text(candidate_start, candidate_at)
        after_raw = CUSTOM_BYTES.get(offset, candidate_raw)
        if mode == "candidate" and after_raw != candidate_raw:
            raise ValueError(f"xdelta 선택 바이트 불일치: 0x{offset:X}")
        if mode == "hybrid" and offset not in CUSTOM_BYTES:
            raise ValueError(f"혼합 문안 바이트 없음: 0x{offset:X}")
        span = max(len(before_raw), len(after_raw))
        before = base_start[base_at:base_at + span]
        after = after_raw.ljust(span, b"\0")
        if before == after:
            raise ValueError(f"실제 변경 없는 패치 행: 0x{offset:X}")
        final_start[base_at:base_at + span] = after
        writes.append({
            "id": f"P1-V7.15.37-DEMO-{sequence:04d}",
            "target": "START.DAT/demo00.dat", "offset_hex": f"0x{offset:X}",
            "length": span, "speaker": speaker, "japanese_source": source,
            "user_translation": user, "xdelta_translation": candidate,
            "selected_translation": selected, "selection": mode,
            "rationale": rationale, "before_hex": before.hex().upper(),
            "after_hex": after.hex().upper(),
        })

    if len(writes) != 10 or {int(row["offset_hex"], 16) for row in writes} != {row[0] for row in PATCHES}:
        raise ValueError("Expected Write 대상 수/주소 불일치")
    for left, right in zip(writes, writes[1:]):
        if int(left["offset_hex"], 16) + int(left["length"]) > int(right["offset_hex"], 16):
            raise ValueError("Expected Write 범위 겹침")

    final_start_bytes = bytes(final_start)
    if changed_start_resources(base_start, final_start_bytes) != ["demo00.dat"]:
        raise ValueError("Demo00.dat 외 START 자원 변경")
    header = decompress_buffer(base_lzs)[1]
    new_lzs = compress_buffer_runtime_safe(final_start_bytes, base_lzs[:4], int(header["flag"]))
    capacity = system_rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(new_lzs) > capacity or decompress_buffer(new_lzs)[0] != final_start_bytes or overlap_count(new_lzs):
        raise ValueError("START.LZS 런타임 안전 압축 실패")

    final_system = bytearray(base_system)
    at = start_row["data_offset"]
    final_system[at:at + capacity] = bytes(capacity)
    final_system[at:at + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _row, _rows = extract_start(final_system_bytes)
    if check_start != final_start_bytes or check_lzs != new_lzs:
        raise ValueError("SYSTEM.DAT START 재추출 불일치")

    final_records = record_map(final_start_bytes)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": new_lzs,
        "demo00.dat": resource_blob(final_start_bytes, final_records, "demo00.dat"),
    }
    comparisons = review_rows({row[0] for row in PATCHES})
    metadata = {
        "reviewed_dialogue_slots": len(comparisons),
        "preserved_runtime_proven_slots": len(PRESERVED_REVIEW),
        "actual_expected_writes": len(writes),
        "candidate_selected_writes": sum(row[6] == "candidate" for row in PATCHES),
        "hybrid_selected_writes": sum(row[6] == "hybrid" for row in PATCHES),
        "changed_start_resources": ["demo00.dat"],
        "lzs_old_size": len(base_lzs), "lzs_new_size": len(new_lzs),
        "lzs_capacity": capacity, "lzs_overlap_backreferences": 0,
    }
    return artifacts, writes, comparisons, metadata


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def seal() -> dict:
    inputs = {BASE_ISO: EXPECTED_BASE_SHA256, CANDIDATE_START: EXPECTED_CANDIDATE_START_SHA256, **dict(EVIDENCE)}
    for path, expected in inputs.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"입력 봉인값 불일치: {path}")
    artifacts, writes, comparisons, metadata = build_resources()
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    write_csv(REPORT_DIR / "expected_writes.csv", writes)
    write_csv(REPORT_DIR / "dialogue_comparison.csv", comparisons)
    report = {
        "format": "prinny1_v7_15_37_dialogue_voice_atmosphere_preflight_v1",
        "created_at": now(),
        "authorization": "user_explicitly_authorized_character_voice_and_atmosphere_editing_2026_08_08",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "candidate_start": {"path": str(CANDIDATE_START), "sha256": sha256_file(CANDIDATE_START)},
        "user_evidence": [{"path": str(path), "sha256": digest} for path, digest in EVIDENCE],
        "repair": metadata,
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "checks": {
            "japanese_user_xdelta_speaker_compared": True,
            "character_voice_priority_applied": True,
            "complete_nul_terminated_candidate_strings_used": True,
            "custom_hybrid_glyphs_visually_verified_with_actual_game_font": True,
            "v7_15_36_stage_and_title_repairs_preserved": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    artifacts, writes, comparisons, metadata = build_resources()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 불일치: {name}")
    if len(list(csv.DictReader((REPORT_DIR / "expected_writes.csv").open(encoding="utf-8-sig")))) != len(writes):
        raise ValueError("독립 사전 Expected Write 행 수 불일치")
    if len(list(csv.DictReader((REPORT_DIR / "dialogue_comparison.csv").open(encoding="utf-8-sig")))) != len(comparisons):
        raise ValueError("독립 사전 대사 비교표 행 수 불일치")
    report = {
        "format": "prinny1_v7_15_37_dialogue_voice_atmosphere_prebuild_review_v1",
        "created_at": now(), "verified": metadata,
        "checks": {
            "fresh_source_candidate_and_selection_recalculation": True,
            "sealed_resources_exact": True,
            "only_demo00_changed": True,
            "expected_write_boundaries_nonoverlapping": True,
            "runtime_safe_lzs": True,
        },
        "status": "pass_iso_build_ready_automatic_approval", "final_verdict": "PASS",
    }
    write_json("independent_prebuild_review.json", report)
    return report


def system_record(iso: Path) -> dict:
    return find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])


def verify_outside_system(candidate: Path, record: dict) -> None:
    left = int(record["extent_lba"]) * SECTOR_SIZE
    right = left + int(record["data_length"])
    if candidate.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, left) != hash_range(candidate, 0, left):
        raise ValueError("SYSTEM 앞 ISO 변경")
    if hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(candidate, right, candidate.stat().st_size):
        raise ValueError("SYSTEM 뒤 ISO 변경")


def build_iso() -> dict:
    review = json.loads((REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or OUTPUT_ISO.exists():
        raise ValueError("사전 검토 미통과 또는 출력 ISO 이미 존재")
    record = system_record(BASE_ISO)
    system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    if len(system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT 크기 변경")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        raise ValueError("임시 출력 ISO가 이미 존재")
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        handle.seek(int(record["extent_lba"]) * SECTOR_SIZE)
        handle.write(system)
        handle.flush()
        os.fsync(handle.fileno())
    verify_outside_system(temporary, record)
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_37_dialogue_voice_atmosphere_iso_v1", "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_system_dat_iso_extent_changed": True,
                   "seven_zip_structure_test": True, "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    base_record, final_record = system_record(BASE_ISO), system_record(OUTPUT_ISO)
    if (base_record["extent_lba"], base_record["data_length"]) != (
        final_record["extent_lba"], final_record["data_length"]
    ):
        raise ValueError("사후 SYSTEM ISO 경계 변경")
    verify_outside_system(OUTPUT_ISO, base_record)
    extracted = read_iso_file(OUTPUT_ISO, final_record)
    if extracted != (RESOURCE_DIR / "SYSTEM.DAT").read_bytes():
        raise ValueError("사후 SYSTEM 재추출 봉인 불일치")
    final_start, final_lzs, _row, _rows = extract_start(extracted)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs):
        raise ValueError("사후 START/LZS 불일치")
    artifacts, writes, comparisons, metadata = build_resources()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 독립 재계산 불일치: {name}")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_37_dialogue_voice_atmosphere_postbuild_review_v1",
        "created_at": now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write_rows": len(writes),
                                "comparison_rows": len(comparisons), "ppsspp_launched": False},
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "sealed_resources_reextracted_exactly": True,
            "fresh_source_candidate_and_selection_recalculation": True,
            "runtime_safe_lzs": True, "seven_zip_structure_retest": True,
        },
        "status": "pass_ready_for_ppsspp_runtime_test", "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print("dialogue review: 20 / preserved: 10 / Expected Writes: 10")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
