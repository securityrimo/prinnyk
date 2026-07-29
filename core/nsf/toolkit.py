import sys
import os
import json

from core.nsf import NSFParser


def run_nsf(path):
    if not os.path.exists(path):
        print("ERROR:", path)
        return

    print("=" * 60)
    print("Prinny Reverse Toolkit")
    print("=" * 60)

    parser = NSFParser(path)

    result = parser.parse()

    outdir = "workspace/nsf"
    os.makedirs(outdir, exist_ok=True)

    name = os.path.basename(path)
    outfile = os.path.join(
        outdir,
        name + "_analysis.json"
    )

    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("Saved:")
    print(outfile)


def main():

    if len(sys.argv) < 2:
        print(
            "usage: python3 toolkit.py <nsf file>"
        )
        sys.exit(1)

    target = sys.argv[1]

    run_nsf(target)


if __name__ == "__main__":
    main()
