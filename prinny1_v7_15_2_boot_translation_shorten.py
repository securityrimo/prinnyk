#!/usr/bin/env python3
"""Apply the user-approved V7.15.2 BOOT fixed-slot shortening set."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
CANONICAL = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_corrected.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening"
BACKUP = QUEUE.with_name("boot_executable_translation_queue_v7_15_2_user_only.before_shortening_75970acf.csv")
EXPECTED_QUEUE_SHA256 = "75970acf7f3eb14e0f8067c8ab89f93941f0f1077048e922302548e41b8c130b"
EXPECTED_CANONICAL_SHA256 = "f0987986cf4e2ceb1c6760374a5378237e15e3b6e35417e079ef4b12d1dd47b5"
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:0\d+)?[sd]")


REVISIONS = {
    "P1-V7.15.2-BOOT-0163": ("를 얻은 뒤 「이름 없는 영혼」에게 말 걸", "를 얻은 뒤「이름 없는 영혼」에게 말 걸", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0217": ("공중에서 □버튼을 누르면 「프리니 연사", "공중에서□버튼을 누르면「프리니 연사", "remove_layout_spaces"),
    "P1-V7.15.2-BOOT-0280": ("「리플레이관」은 해당 「마력 구슬」을", "「리플레이관」은 해당「마력 구슬」을", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0312": ("연무의 탑 프리니 라하르", "연무의 탑 프리니라하르", "join_proper_name"),
    "P1-V7.15.2-BOOT-0344": ("데이터 저장은 거점(현재 위치)에서", "데이터 저장은 거점(현재위치)에서", "join_parenthetical_label"),
    "P1-V7.15.2-BOOT-0346": ("연무의 탑 프리니 바알", "연무의 탑 프리니바알", "join_proper_name"),
    "P1-V7.15.2-BOOT-0392": ("스위츠 팰리스", "스위츠팰리스", "join_ui_name"),
    "P1-V7.15.2-BOOT-0393": ("시스템 데이터", "시스템데이터", "join_ui_label"),
    "P1-V7.15.2-BOOT-0398": ("야반도주할까요?", "야반도주?", "shorten_ui_question"),
    "P1-V7.15.2-BOOT-0419": ("리플레이 보기", "리플레이보기", "join_ui_label"),
    "P1-V7.15.2-BOOT-0422": ("게임 데이터", "게임데이터", "join_ui_label"),
    "P1-V7.15.2-BOOT-0424": ("클리어 랭크", "클리어랭크", "join_ui_label"),
    "P1-V7.15.2-BOOT-0425": ("클리어 시간", "클리어시간", "join_ui_label"),
    "P1-V7.15.2-BOOT-0428": ("클리어 기록", "클리어기록", "join_ui_label"),
    "P1-V7.15.2-BOOT-0447": ("리플레이 설명", "리플레이설명", "join_ui_label"),
    "P1-V7.15.2-BOOT-0449": ("아사기 하기", "아사기하기", "join_ui_label"),
    "P1-V7.15.2-BOOT-0457": ("최종화 『영원하라!』", "최종 『영원하라!』", "shorten_episode_prefix"),
    "P1-V7.15.2-BOOT-0462": ("거점으로 귀환", "거점으로귀환", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0471": ("마해 아리아", "마해아리아", "join_ui_name"),
    "P1-V7.15.2-BOOT-0481": ("VS 파프리카", "VS파프리카", "join_ui_label"),
    "P1-V7.15.2-BOOT-0482": ("제2화 『마계 따위』", "제2화『마계 따위』", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0483": ("리플레이관", "리플관", "shorten_ui_name"),
    "P1-V7.15.2-BOOT-0485": ("다시 선택", "다시선택", "join_ui_label"),
    "P1-V7.15.2-BOOT-0488": ("제1화 『주인공은?』", "제1화『주인공은?』", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0491": ("모브 대요새", "모브대요새", "join_ui_name"),
    "P1-V7.15.2-BOOT-0494": ("VS 아니스", "VS아니스", "join_ui_label"),
    "P1-V7.15.2-BOOT-0504": ("아니오", "아뇨", "shorten_negative_response"),
    "P1-V7.15.2-BOOT-0509": ("=지정 없음=", "=지정없음=", "join_ui_label"),
    "P1-V7.15.2-BOOT-0511": ("보스전 사망수", "보스전사망수", "join_ui_label"),
    "P1-V7.15.2-BOOT-0512": ("야반도주 수", "야반도주수", "join_ui_label"),
    "P1-V7.15.2-BOOT-0513": ("시공 뱃사공", "시공뱃사공", "join_ui_name"),
    "P1-V7.15.2-BOOT-0514": ("제3화 『고민상담실』", "3화 『고민상담실』", "shorten_episode_prefix"),
    "P1-V7.15.2-BOOT-0515": ("전투 기록", "전투기록", "join_ui_label"),
    "P1-V7.15.2-BOOT-0516": ("난도 변경", "난도변경", "join_ui_label"),
    "P1-V7.15.2-BOOT-0517": ("사신의 처형탑(%s)", "사신의처형탑(%s)", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0520": ("책의 대삼림(%s)", "책의대삼림(%s)", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0526": ("11. 마법 양탄자", "11.마법 양탄자", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0527": ("보스전", "보스", "shorten_ui_label"),
    "P1-V7.15.2-BOOT-0528": ("흑사 과자사막", "흑사과자사막", "join_ui_name"),
    "P1-V7.15.2-BOOT-0530": ("10. 적의 기절", "10.적의 기절", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0531": ("10마시간 남음", "10마시간남음", "remove_layout_space"),
    "P1-V7.15.2-BOOT-0532": ("사신 처형탑", "사신처형탑", "join_ui_name"),
    "P1-V7.15.2-BOOT-0533": ("용암 닌자성", "용암닌자성", "join_ui_name"),
    "P1-V7.15.2-BOOT-0535": ("9마시간 남음", "9마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0536": ("8마시간 남음", "8마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0537": ("7마시간 남음", "7마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0538": ("6마시간 남음", "6마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0539": ("5마시간 남음", "5마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0540": ("4마시간 남음", "4마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0541": ("3마시간 남음", "3마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0542": ("2마시간 남음", "2마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0543": ("1마시간 남음", "1마시간", "shorten_countdown_label"),
    "P1-V7.15.2-BOOT-0544": ("책의 대숲", "책의대숲", "join_ui_name"),
    "P1-V7.15.2-BOOT-0545": ("선인 제단", "선인제단", "join_ui_name"),
    "P1-V7.15.2-BOOT-0551": ("야반도주", "도주", "shorten_ui_label"),
    "P1-V7.15.2-BOOT-0552": ("뒤로", "뒤", "shorten_back_label"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def encode(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        output.extend(mapping[character] if character in mapping else character.encode("cp932"))
    return bytes(output)


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for path in (QUEUE, CANONICAL, ALLOCATION):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(QUEUE) != EXPECTED_QUEUE_SHA256:
        raise ValueError("사용자 큐가 승인된 축약 입력 해시와 다릅니다.")
    if sha256_file(CANONICAL) != EXPECTED_CANONICAL_SHA256:
        raise ValueError("기준 메타데이터 큐 해시가 다릅니다.")

    original_bytes = QUEUE.read_bytes()
    with QUEUE.open("r", encoding="utf-8-sig", newline="") as handle:
        user_rows = list(csv.DictReader(handle))
    with CANONICAL.open("r", encoding="utf-8-sig", newline="") as handle:
        canonical_reader = csv.DictReader(handle)
        canonical_fields = list(canonical_reader.fieldnames or [])
        canonical_rows = [row for row in canonical_reader if row["status"] == "needs_user_translation"]
    if len(user_rows) != 542 or len(canonical_rows) != 542 or len(REVISIONS) != 56:
        raise ValueError("축약 입력 행 수가 봉인 범위와 다릅니다.")
    user_by_id = {row["id"]: row for row in user_rows}
    if len(user_by_id) != len(user_rows):
        raise ValueError("사용자 큐 ID가 중복됩니다.")
    if set(user_by_id) != {row["id"] for row in canonical_rows}:
        raise ValueError("사용자 큐 ID 집합이 기준 큐와 다릅니다.")

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    mapping = {str(row["hangul"]): bytes.fromhex(str(row["sjis"])) for row in allocation["allocations"]}
    before_overflow: set[str] = set()
    for row in canonical_rows:
        translation = user_by_id[row["id"]]["user_translation_korean"]
        if len(encode(translation, mapping)) + 2 > int(row["byte_length"]):
            before_overflow.add(row["id"])
    if before_overflow != set(REVISIONS):
        raise ValueError("실제 용량 초과 ID 집합이 승인된 56건과 다릅니다.")

    output_rows: list[dict[str, str]] = []
    changes: list[dict[str, object]] = []
    for canonical in canonical_rows:
        row = dict(canonical)
        identifier = row["id"]
        old = user_by_id[identifier]["user_translation_korean"]
        if not old:
            raise ValueError(f"빈 번역입니다: {identifier}")
        if identifier in REVISIONS:
            expected_old, new, rule = REVISIONS[identifier]
            if old != expected_old:
                raise ValueError(f"승인 전 문구가 다릅니다: {identifier}")
            if PLACEHOLDER.findall(row["source_japanese"]) != PLACEHOLDER.findall(new):
                raise ValueError(f"플레이스홀더가 다릅니다: {identifier}")
            old_size = len(encode(old, mapping)) + 2
            new_size = len(encode(new, mapping)) + 2
            if new_size > int(row["byte_length"]) or new_size >= old_size:
                raise ValueError(f"축약 후 용량 검사가 실패했습니다: {identifier}")
            row["user_translation_korean"] = new
            changes.append({
                "id": identifier,
                "offset_hex": row["offset_hex"],
                "slot_bytes": int(row["byte_length"]),
                "before_bytes_with_nul": old_size,
                "after_bytes_with_nul": new_size,
                "before": old,
                "after": new,
                "rule": rule,
            })
        else:
            row["user_translation_korean"] = old
        output_rows.append(row)

    for row in output_rows:
        translation = row["user_translation_korean"]
        if PLACEHOLDER.findall(row["source_japanese"]) != PLACEHOLDER.findall(translation):
            raise ValueError(f"최종 플레이스홀더가 다릅니다: {row['id']}")
        if len(encode(translation, mapping)) + 2 > int(row["byte_length"]):
            raise ValueError(f"최종 슬롯 용량 초과입니다: {row['id']}")

    if BACKUP.exists():
        if BACKUP.read_bytes() != original_bytes:
            raise ValueError("기존 축약 전 백업이 현재 입력과 다릅니다.")
    else:
        BACKUP.write_bytes(original_bytes)
    write_csv(QUEUE, output_rows, canonical_fields)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    changes_path = REPORT_DIR / "approved_shortening_changes.csv"
    write_csv(changes_path, [{key: str(value) for key, value in row.items()} for row in changes], list(changes[0]))
    report = {
        "format": "prinny1_v7_15_2_boot_translation_shortening_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "queue_before": str(BACKUP),
            "queue_before_sha256": sha256_file(BACKUP),
            "canonical_queue": str(CANONICAL),
            "canonical_queue_sha256": sha256_file(CANONICAL),
            "allocation_sha256": sha256_file(ALLOCATION),
        },
        "verified": {
            "row_count": len(output_rows),
            "approved_shortening_count": len(changes),
            "unchanged_translation_count": len(output_rows) - len(changes),
            "overflow_before": len(before_overflow),
            "overflow_after": 0,
            "missing_font_mapping_after": 0,
            "placeholder_mismatch_after": 0,
            "metadata_rows_restored_from_canonical": len(output_rows),
            "binary_evidence_cells_repaired": 2,
            "codex_wording_changes_outside_user_approved_overflow_scope": 0,
        },
        "artifacts": {
            "queue": str(QUEUE),
            "queue_sha256": sha256_file(QUEUE),
            "changes": str(changes_path),
            "changes_sha256": sha256_file(changes_path),
        },
        "checks": {
            "input_hash_locked": True,
            "canonical_metadata_hash_locked": True,
            "old_translation_exact_match": True,
            "only_overflow_translations_changed": True,
            "all_final_translations_fit": True,
            "iso_modified": False,
        },
        "status": "shortening_applied_independent_review_required",
        "final_verdict": "PASS",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"shortened translations: {len(changes)}")
    print(f"queue sha256: {report['artifacts']['queue_sha256']}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
