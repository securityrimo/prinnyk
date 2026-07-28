"""
Hash calculation engine.

- SHA1
- MD5
- CRC32

Reads the file only once.
"""

from pathlib import Path
import hashlib
import zlib


BUFFER_SIZE = 1024 * 1024  # 1 MB


def calculate_hashes(path: Path) -> dict:
    """
    Calculate SHA1, MD5 and CRC32 in one pass.

    Returns:
        {
            "size": int,
            "sha1": "...",
            "md5": "...",
            "crc32": "XXXXXXXX"
        }
    """

    sha1 = hashlib.sha1()
    md5 = hashlib.md5()

    crc = 0
    size = 0

    with path.open("rb") as f:

        while True:

            chunk = f.read(BUFFER_SIZE)

            if not chunk:
                break

            size += len(chunk)

            sha1.update(chunk)
            md5.update(chunk)

            crc = zlib.crc32(chunk, crc)

    return {
        "size": size,
        "sha1": sha1.hexdigest(),
        "md5": md5.hexdigest(),
        "crc32": f"{crc & 0xffffffff:08X}",
    }


if __name__ == "__main__":

    import sys

    if len(sys.argv) != 2:
        print("Usage:")
        print("python3 hashes.py file.bin")
        raise SystemExit

    result = calculate_hashes(Path(sys.argv[1]))

    for k, v in result.items():
        print(f"{k:8}: {v}")
