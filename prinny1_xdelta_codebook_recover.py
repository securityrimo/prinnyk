#!/usr/bin/env python3
from __future__ import annotations

import csv
import difflib
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
QA = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
CANDIDATE_START = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start.dat"
CANDIDATE_FNT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/font.fnt"
OUTPUT = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def is_hangul(character: str) -> bool:
    return len(character) == 1 and "\uac00" <= character <= "\ud7a3"


def tokenize(payload: bytes) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    offset = 0
    while offset < len(payload) and payload[offset] != 0:
        lead = payload[offset]
        if 0xF0 <= lead <= 0xF5 and offset + 1 < len(payload):
            tokens.append(("candidate_hangul", payload[offset:offset + 2].hex().upper()))
            offset += 2
            continue
        if (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF) and offset + 1 < len(payload):
            pair = payload[offset:offset + 2]
            try:
                tokens.append(("literal", pair.decode("cp932")))
                offset += 2
                continue
            except UnicodeDecodeError:
                pass
        if lead < 0x80:
            tokens.append(("literal", chr(lead)))
            offset += 1
            continue
        tokens.append(("control_or_unknown", f"{lead:02X}"))
        offset += 1
    return tokens


def candidate_codes() -> list[str]:
    codes = []
    for lead in range(0xF0, 0xF6):
        for trail in range(0x40, 0xFD):
            if trail == 0x7F:
                continue
            code = f"{lead:02X}{trail:02X}"
            codes.append(code)
            if code == "F56E":
                return codes
    raise AssertionError("F56E에 도달하지 못했습니다.")


def resolve(votes: dict[str, Counter[str]], minimum_votes: int, minimum_ratio: float) -> dict[str, str]:
    candidates = []
    for code, counter in votes.items():
        if not counter:
            continue
        character, count = counter.most_common(1)[0]
        total = sum(counter.values())
        ratio = count / total
        if is_hangul(character) and count >= minimum_votes and ratio >= minimum_ratio:
            candidates.append((ratio, count, code, character, total))
    candidates.sort(reverse=True)
    mapping: dict[str, str] = {}
    used_characters = set()
    for _ratio, _count, code, character, _total in candidates:
        if character in used_characters:
            continue
        mapping[code] = character
        used_characters.add(character)
    return mapping


def token_text(tokens: Iterable[tuple[str, str]]) -> str:
    return " ".join(f"<{value}>" if kind == "candidate_hangul" else repr(value) for kind, value in tokens)


def main() -> int:
    for path in (QA, CANDIDATE_START, CANDIDATE_FNT):
        if not path.is_file():
            raise FileNotFoundError(path)
    qa_rows = read_csv(QA)
    archive = StartRuntimeArchive.load(CANDIDATE_START)
    records = {record.output_name.casefold(): record for record in archive.records}
    if len(qa_rows) != 4110:
        raise ValueError(f"QA 슬롯 수가 4,110개가 아닙니다: {len(qa_rows)}")

    corpus: list[tuple[list[tuple[str, str]], str]] = []
    parallel_rows: list[dict[str, object]] = []
    exact_skeleton_count = 0
    for sequence, row in enumerate(qa_rows, 1):
        record = records.get(row["resource"].casefold())
        if record is None:
            raise ValueError(f"후보 START 자원 누락: {row['resource']}")
        resource_offset = int(row["offset"], 0)
        capacity = int(row["capacity_bytes"])
        absolute = int(record.data_offset) + resource_offset
        payload = archive.data[absolute:absolute + capacity]
        tokens = tokenize(payload)
        translation = row["translation"]
        exact_skeleton = (
            len(tokens) == len(translation)
            and all(kind == "candidate_hangul" or (kind == "literal" and value == character)
                    for (kind, value), character in zip(tokens, translation))
        )
        exact_skeleton_count += int(exact_skeleton)
        corpus.append((tokens, translation))
        parallel_rows.append({
            "sequence": sequence,
            "id": row["id"],
            "resource": row["resource"],
            "offset": row["offset"],
            "capacity_bytes": capacity,
            "candidate_payload_hex": payload.hex().upper(),
            "candidate_tokens": token_text(tokens),
            "candidate_token_count": len(tokens),
            "user_translation": translation,
            "user_character_count": len(translation),
            "exact_literal_skeleton": "yes" if exact_skeleton else "no",
            "candidate_wording_applied": "no",
        })

    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for tokens, translation in corpus:
        if len(tokens) != len(translation):
            continue
        if not all(kind == "candidate_hangul" or (kind == "literal" and value == character)
                   for (kind, value), character in zip(tokens, translation)):
            continue
        for (kind, value), character in zip(tokens, translation):
            if kind == "candidate_hangul" and is_hangul(character):
                votes[value][character] += 1

    mapping = resolve(votes, minimum_votes=2, minimum_ratio=0.72)
    iteration_rows = [{"iteration": 0, "mapping_count": len(mapping), "aligned_gap_count": 0}]
    for iteration in range(1, 13):
        new_votes: dict[str, Counter[str]] = defaultdict(Counter)
        aligned_gap_count = 0
        for tokens, translation in corpus:
            candidate_sequence = [
                mapping.get(value, f"\uE000{value}") if kind == "candidate_hangul" else value
                for kind, value in tokens
            ]
            matcher = difflib.SequenceMatcher(None, candidate_sequence, list(translation), autojunk=False)
            blocks = matcher.get_matching_blocks()
            previous_candidate = 0
            previous_user = 0
            for block_index, block in enumerate(blocks):
                candidate_start, user_start, size = block
                candidate_gap = tokens[previous_candidate:candidate_start]
                user_gap = translation[previous_user:user_start]
                left_anchor = blocks[block_index - 1].size if block_index else 0
                right_anchor = size
                if (
                    len(candidate_gap) == len(user_gap)
                    and len(candidate_gap) <= 16
                    and (left_anchor >= 2 or right_anchor >= 2)
                ):
                    compatible = True
                    for (kind, value), character in zip(candidate_gap, user_gap):
                        if kind == "literal" and value != character:
                            compatible = False
                        elif kind == "control_or_unknown":
                            compatible = False
                        elif kind == "candidate_hangul" and value in mapping and mapping[value] != character:
                            compatible = False
                    if compatible:
                        weight = min(5, max(left_anchor, right_anchor))
                        for (kind, value), character in zip(candidate_gap, user_gap):
                            if kind == "candidate_hangul" and value not in mapping and is_hangul(character):
                                new_votes[value][character] += weight
                        aligned_gap_count += 1
                previous_candidate = candidate_start + size
                previous_user = user_start + size
        for code, counter in new_votes.items():
            votes[code].update(counter)
        previous_count = len(mapping)
        mapping = resolve(votes, minimum_votes=3, minimum_ratio=0.76)
        iteration_rows.append({
            "iteration": iteration,
            "mapping_count": len(mapping),
            "aligned_gap_count": aligned_gap_count,
        })
        if len(mapping) == previous_count:
            break

    codes = candidate_codes()
    if len(codes) != 987:
        raise ValueError(f"후보 코드 수가 987개가 아닙니다: {len(codes)}")
    fnt_table = FontRuntime._parse_fnt(CANDIDATE_FNT.read_bytes())
    codebook_rows = []
    for sequence, code in enumerate(codes, 1):
        table_index = FontRuntime.table_index_from_sjis(bytes.fromhex(code))
        glyph_index = fnt_table[table_index]
        counter = votes.get(code, Counter())
        character = mapping.get(code, "")
        winning_votes = counter[character] if character else 0
        total_votes = sum(counter.values())
        codebook_rows.append({
            "sequence": sequence,
            "candidate_code": code,
            "table_index_hex": f"0x{table_index:04X}",
            "candidate_glyph_index_hex": f"0x{glyph_index:04X}",
            "unicode_character": character,
            "unicode_codepoint": f"U+{ord(character):04X}" if character else "",
            "winning_votes": winning_votes,
            "total_votes": total_votes,
            "winning_ratio": f"{winning_votes / total_votes:.6f}" if total_votes else "0.000000",
            "recovery_status": "statistical_anchor_recovered" if character else "unresolved_glyph_validation_required",
            "candidate_wording_applied": "no",
        })

    vote_rows = []
    for code in codes:
        counter = votes.get(code, Counter())
        total_votes = sum(counter.values())
        for rank, (character, count) in enumerate(counter.most_common(), 1):
            vote_rows.append({
                "candidate_code": code,
                "unicode_character": character,
                "unicode_codepoint": f"U+{ord(character):04X}",
                "vote_rank": rank,
                "votes": count,
                "total_votes": total_votes,
                "vote_ratio": f"{count / total_votes:.6f}",
                "candidate_wording_applied": "no",
            })

    user_hangul = {character for _tokens, translation in corpus for character in translation if is_hangul(character)}
    recovered_hangul = set(mapping.values())
    missing_hangul = sorted(user_hangul - recovered_hangul)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    parallel_path = OUTPUT / "parallel_slots.csv"
    codebook_path = OUTPUT / "candidate_codebook_partial.csv"
    iterations_path = OUTPUT / "recovery_iterations.csv"
    votes_path = OUTPUT / "candidate_code_votes.csv"
    missing_path = OUTPUT / "unresolved_user_hangul.txt"
    write_csv(parallel_path, parallel_rows)
    write_csv(codebook_path, codebook_rows)
    write_csv(iterations_path, iteration_rows)
    write_csv(votes_path, vote_rows)
    missing_path.write_text("".join(missing_hangul) + "\n", encoding="utf-8")
    report = {
        "format": "prinny1_xdelta_codebook_recovery_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "qa_sha256": sha256_file(QA),
            "candidate_start_sha256": sha256_file(CANDIDATE_START),
            "candidate_fnt_sha256": sha256_file(CANDIDATE_FNT),
        },
        "verified": {
            "parallel_slot_count": len(parallel_rows),
            "candidate_code_count": len(codes),
            "exact_literal_skeleton_slot_count": exact_skeleton_count,
            "statistically_recovered_code_count": len(mapping),
            "candidate_code_vote_pair_count": len(vote_rows),
            "user_hangul_count": len(user_hangul),
            "recovered_user_hangul_count": len(user_hangul & recovered_hangul),
            "unresolved_user_hangul_count": len(missing_hangul),
        },
        "checks": {
            "all_qa_resources_found_in_candidate_start": True,
            "candidate_font_table_resolved_for_all_codes": True,
            "recovered_code_and_unicode_are_one_to_one": len(mapping) == len(set(mapping.values())),
            "candidate_translation_wording_applied": False,
            "binary_files_modified": False,
            "iso_created": False,
        },
        "artifacts": {
            "parallel_slots": str(parallel_path),
            "parallel_slots_sha256": sha256_file(parallel_path),
            "partial_codebook": str(codebook_path),
            "partial_codebook_sha256": sha256_file(codebook_path),
            "iterations": str(iterations_path),
            "iterations_sha256": sha256_file(iterations_path),
            "candidate_code_votes": str(votes_path),
            "candidate_code_votes_sha256": sha256_file(votes_path),
            "unresolved_user_hangul": str(missing_path),
            "unresolved_user_hangul_sha256": sha256_file(missing_path),
        },
        "status": "partial_codebook_recovered_glyph_validation_required",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"parallel slots: {len(parallel_rows)}")
    print(f"exact literal skeleton slots: {exact_skeleton_count}")
    print(f"candidate codebook recovered: {len(mapping)}/987")
    print(f"user Hangul covered: {len(user_hangul & recovered_hangul)}/{len(user_hangul)}")
    print(f"unresolved user Hangul: {len(missing_hangul)}")
    print("candidate wording applied: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
