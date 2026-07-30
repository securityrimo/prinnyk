#!/usr/bin/env python3

from pathlib import Path

import dump_boot_font_functions as mips
import find_charset_global_xrefs as xrefs


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/exact_font_field_xrefs.txt"
)

TARGETS = {
    0x08A54188: "font object base",
    0x08A54208: "font entry count field (+0x80)",
    0x08A5420C: "font table pointer field (+0x84)",
    0x08A54210: "font.fnt resource field (+0x88)",
}


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF 파일이 아닙니다."
        )

    sections = mips.parse_sections(data)

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as report:
        print(
            "EXACT FONT RUNTIME FIELD XREFS",
            file=report,
        )
        print(
            "==============================",
            file=report,
        )
        print(
            "FONT OBJECT BASE: 0x08A54188",
            file=report,
        )

        for target_address, label in TARGETS.items():
            hits = xrefs.find_xrefs(
                data,
                sections,
                target_address,
            )

            print(file=report)
            print("=" * 96, file=report)
            print(
                f"{label}: 0x{target_address:08X}",
                file=report,
            )
            print("=" * 96, file=report)
            print(
                f"XREF COUNT: {len(hits)}",
                file=report,
            )

            for index, hit in enumerate(
                hits,
                start=1,
            ):
                print(file=report)
                print(
                    f"[{index}] "
                    f"XREF=0x{hit['xref_address']:08X} "
                    f"LUI=0x{hit['lui_address']:08X} "
                    f"OP={hit['operation']} "
                    f"DISTANCE={hit['distance']} "
                    f"SECTION={hit['section']['name']}",
                    file=report,
                )

                xrefs.print_context(
                    report,
                    data,
                    sections,
                    hit,
                    before=24,
                    after=32,
                )

    output = REPORT_PATH.read_text(
        encoding="utf-8",
    )

    print(output, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
