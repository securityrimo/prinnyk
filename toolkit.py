#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path
from core.analyzer import analyze_directory
from config import *
from core.extractor import extract_iso
from core.inventory import build_inventory, save_inventory
from core.utils import sha1


# -----------------------------
# extract
# -----------------------------
def cmd_extract(args):

    print("DEBUG 1")

    iso = Path(args.iso)

    print("DEBUG 2")

    if not iso.exists():
        print("ISO 없음")
        return

    print("DEBUG 3")

    WORKSPACE.mkdir(exist_ok=True)

    print("DEBUG 4")

    print("SHA1 계산")

    print(sha1(iso))

    print("DEBUG 5")

    extract_iso(iso, ISO_DIR)

    print("DEBUG 6")

    print("Building inventory...")

    inv = build_inventory(ISO_DIR)

    print(f"{len(inv)} files")

    save_inventory(inv, INVENTORY)

    print("Done")
# -----------------------------
# analyze
# -----------------------------
from core.analyzer import analyze_directory
import json

def cmd_analyze(args):

    print("=" * 60)
    print("Analyze")
    print("=" * 60)

    report = analyze_directory(ISO_DIR)

    output = WORKSPACE / "analysis.json"

    with open(output, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=4, ensure_ascii=False)

    print()
    print(f"분석 완료 : {len(report)}개 파일")
    print(f"저장 위치 : {output}")

# -----------------------------
# strings
# -----------------------------
def cmd_strings(args):
    print("=" * 60)
    print("Strings")
    print("=" * 60)
    print("STEP3에서 구현 예정")


# -----------------------------
# patch
# -----------------------------
def cmd_patch(args):
    print("=" * 60)
    print("Patch")
    print("=" * 60)
    print("STEP8에서 구현 예정")


# -----------------------------
# main
# -----------------------------
def main():

    parser = argparse.ArgumentParser(
        prog="toolkit.py",
        description="Prinny Reverse Toolkit"
    )

    sub = parser.add_subparsers(dest="command")

    # extract
    p = sub.add_parser("extract", help="Extract ISO")
    p.add_argument("iso", help="ISO file")
    p.set_defaults(func=cmd_extract)

    # analyze
    p = sub.add_parser("analyze", help="Analyze files")
    p.set_defaults(func=cmd_analyze)

    # strings
    p = sub.add_parser("strings", help="Extract strings")
    p.set_defaults(func=cmd_strings)

    # patch
    p = sub.add_parser("patch", help="Build patch")
    p.set_defaults(func=cmd_patch)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
