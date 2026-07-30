from __future__ import annotations

from pathlib import Path
from typing import Any

from psp_localization.iso import find_disc_root
from psp_localization.string_scan import scan_file, write_scan_report


def scan_prinny_executable_strings(
    disc_root: Path,
    output_directory: Path,
) -> dict[str, Any]:
    root = find_disc_root(disc_root)
    sysdir = root / "PSP_GAME" / "SYSDIR"
    candidates = [sysdir / "BOOT.BIN", sysdir / "EBOOT.BIN"]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError(f"BOOT.BIN/EBOOT.BIN 없음: {sysdir}")
    report = scan_file(source)
    report["profile"] = "prinny"
    report["purpose"] = "START 외 UI/튜토리얼/메뉴 일본어 후보"
    write_scan_report(report, output_directory)
    return report
