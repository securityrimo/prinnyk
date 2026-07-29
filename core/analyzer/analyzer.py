from pathlib import Path
import hashlib
import math
import json
from collections import Counter


MAGIC = {
    b"\x1f\x8b": "gzip",
    b"\x78\x9c": "zlib",
    b"\x78\xda": "zlib",
    b"BZh": "bzip2",
    b"\xfd7zXZ": "lzma",
    b"PK\x03\x04": "zip",
}


def sha1(path):

    h = hashlib.sha1()

    with open(path, "rb") as f:

        while True:

            data = f.read(1024 * 1024)

            if not data:
                break

            h.update(data)

    return h.hexdigest()



def entropy(data):

    if not data:
        return 0

    counter = Counter(data)

    size = len(data)

    result = 0

    for count in counter.values():

        p = count / size

        result -= p * math.log2(p)

    return round(result, 3)



def detect_magic(data):

    for magic, name in MAGIC.items():

        if data.startswith(magic):
            return name

    return "unknown"



def ascii_count(data):

    count = 0
    buf = 0

    for b in data:

        if 32 <= b <= 126:

            buf += 1

        else:

            if buf >= 4:
                count += 1

            buf = 0

    return count



def analyze_file(path):

    data = path.read_bytes()

    return {

        "file": str(path),

        "size": len(data),

        "sha1": sha1(path),

        "entropy": entropy(data),

        "ascii": ascii_count(data),

        "magic": detect_magic(data)

    }



def analyze_directory(root):

    root = Path(root)

    files = [
        f for f in root.rglob("*")
        if f.is_file()
    ]

    result = []

    total = len(files)

    for i, f in enumerate(files, 1):

        print(
            f"[{i}/{total}] {f.name}"
        )

        result.append(
            analyze_file(f)
        )


    return result
