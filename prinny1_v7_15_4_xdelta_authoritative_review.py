#!/usr/bin/env python3
"""Independent review of the xdelta-authoritative single-fallback plan."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/forced_redecode_20260801.iso"
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_plan"
PLAN = PLAN_DIR / "all_report.json"
MANIFEST = PLAN_DIR / "xdelta_authoritative_selection.csv"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
BOOT = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative_resources/BOOT.BIN"
EBOOT = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative_resources/EBOOT.BIN"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_review"
EXPECTED = {
    BASE_ISO: "8bc47f189a41309dcca5ef6c61bd5e1368909da8c9b0fc032e2498368d095b65",
    PLAN: "ec53d4a49127bba60f5ca0316f1e3543b21fe3617b9101a4ebffccdd72eef72a",
    MANIFEST: "6e2080e1e2fe62dc5cef6e504880defa2753a69fcd12355b9f6699bc1f383a15",
    WRITES: "05fa2f672bd5ec3738ba4a86b196cc59840d8f4c726a8f40361383286070ed3c",
    BOOT: "67d63f8c122c252fc8062f97425c1a57ad7bf1cb298683d09dcdcacfbe92df65",
    EBOOT: "67d63f8c122c252fc8062f97425c1a57ad7bf1cb298683d09dcdcacfbe92df65",
}
FALLBACK_ID = "P1-V7.15.2-BOOT-0345"
EXPECTED_TEXT = "데이터 송신 완료"
CODEBOOK = {
    b"\xF1\x47": "데", b"\xF3\x62": "이", b"\xF4\x50": "터",
    b"\xF2\x9B": "송", b"\xF2\xB4": "신", b"\xF3\x42": "완",
    b"\xF1\xB7": "료",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def decode(payload: bytes) -> str:
    output = []
    cursor = 0
    while cursor < len(payload) and payload[cursor] != 0:
        if payload[cursor] == 0x20:
            output.append(" "); cursor += 1
        else:
            pair = payload[cursor:cursor + 2]
            if pair not in CODEBOOK:
                raise ValueError(f"fallback 미확인 코드: {pair.hex().upper()}")
            output.append(CODEBOOK[pair]); cursor += 2
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.4 독립 검토 입력 해시 불일치: {path}")
    if OUTPUT_ISO.exists():
        raise ValueError("사전 검토 전에 V7.15.4 ISO가 이미 존재합니다.")
    manifest = rows(MANIFEST)
    writes = rows(WRITES)
    if len(manifest) != 542 or len(writes) != 1:
        raise ValueError("manifest/Expected Write 수 불일치")
    decisions = {kind: sum(row["decision"] == kind for row in manifest) for kind in {row["decision"] for row in manifest}}
    if decisions != {"xdelta_unchanged": 541, "user_fallback_xdelta_missing": 1}:
        raise ValueError(f"V7.15.4 선택 수 불일치: {decisions}")
    fallback = [row for row in manifest if row["decision"] != "xdelta_unchanged"]
    if len(fallback) != 1 or fallback[0]["id"] != FALLBACK_ID or fallback[0]["final_translation_korean"] != EXPECTED_TEXT:
        raise ValueError("사용자 fallback 대상/문구 불일치")
    replay = next(row for row in manifest if row["id"] == "P1-V7.15.2-BOOT-0002")
    if replay["decision"] != "xdelta_unchanged" or "다시" not in replay["final_translation_korean"]:
        raise ValueError("xdelta 우선 규칙이 0002에 적용되지 않았습니다.")

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    sealed = BOOT.read_bytes()
    write = writes[0]
    offset = int(write["offset_hex"], 0)
    before, after = bytes.fromhex(write["expected_before_hex"]), bytes.fromhex(write["write_after_hex"])
    if base_boot != base_eboot or base_boot[offset:offset + len(before)] != before:
        raise ValueError("xdelta 기준 BOOT/EBOOT 또는 before 불일치")
    rebuilt = bytearray(base_boot)
    rebuilt[offset:offset + len(after)] = after
    if bytes(rebuilt) != sealed or EBOOT.read_bytes() != sealed:
        raise ValueError("봉인 BOOT/EBOOT가 단일 Expected Write와 다릅니다.")
    actual_changes = {i for i, pair in enumerate(zip(base_boot, sealed)) if pair[0] != pair[1]}
    declared_changes = {offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}
    if actual_changes != declared_changes or not actual_changes:
        raise ValueError("BOOT 실제 변경 범위 불일치")
    if decode(sealed[offset:offset + len(after) + 1]) != EXPECTED_TEXT or sealed[offset + len(after)] != 0:
        raise ValueError("fallback 재디코딩 또는 NUL 경계 실패")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    report = {
        "format": "prinny1_v7_15_4_xdelta_authoritative_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "manifest_rows": len(manifest), "xdelta_unchanged_rows": 541,
            "user_fallback_rows": 1, "expected_writes": 1,
            "boot_changed_bytes": len(actual_changes), "fallback_redecoded": EXPECTED_TEXT,
        },
        "checks": {
            "xdelta_is_authoritative": True, "xdelta_korean_kept_even_when_user_wording_differs": True,
            "only_untranslated_xdelta_row_uses_user_text": True,
            "sealed_boot_is_exact_single_expected_write": True,
            "boot_eboot_mirror_exact": True, "fallback_nul_boundary_preserved": True,
            "xdelta_other_data_not_in_write_plan": True, "output_iso_absent": True,
            "declared_official_xdelta_hash_mismatch_acknowledged": not plan["baseline"]["declared_official_source_hash_match"],
        },
        "status": "pass_v7_15_4_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("xdelta unchanged: 541, user fallback: 1, Expected Writes: 1")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
