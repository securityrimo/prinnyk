from pathlib import Path
import json

def build_inventory(root):

    result = []

    root = Path(root)

    for f in root.rglob("*"):

        if not f.is_file():
            continue

        result.append({
            "path": str(f.relative_to(root)),
            "size": f.stat().st_size,
            "extension": f.suffix.lower()
        })

    return result


def save_inventory(data, outfile):

    with open(outfile, "w", encoding="utf8") as fp:
        json.dump(data, fp, indent=4, ensure_ascii=False)
