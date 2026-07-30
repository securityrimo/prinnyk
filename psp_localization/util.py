from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


_CHUNK_SIZE = 1024 * 1024


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path, chunk_size: int = _CHUNK_SIZE) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sampled_sha1(path: Path, sample_size: int = 1024 * 1024) -> str:
    """대용량 파일의 앞/가운데/뒤 구간을 이용한 비교용 해시."""
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(size.to_bytes(8, "little", signed=False))
    with path.open("rb") as handle:
        offsets = [0]
        if size > sample_size:
            offsets.append(max(0, size // 2 - sample_size // 2))
            offsets.append(max(0, size - sample_size))
        seen: set[int] = set()
        for offset in offsets:
            if offset in seen:
                continue
            seen.add(offset)
            handle.seek(offset)
            block = handle.read(sample_size)
            digest.update(offset.to_bytes(8, "little", signed=False))
            digest.update(block)
    return digest.hexdigest()


def file_fingerprint(
    path: Path,
    *,
    full_hash_limit: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    size = path.stat().st_size
    if size <= full_hash_limit:
        digest = sha1_file(path)
        hash_kind = "sha1"
    else:
        digest = sampled_sha1(path)
        hash_kind = "sampled_sha1"

    with path.open("rb") as handle:
        head = handle.read(32)

    return {
        "size": size,
        "size_hex": f"0x{size:X}",
        "hash": digest,
        "hash_kind": hash_kind,
        "head_hex": head.hex(" ").upper(),
    }


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = handle.name
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(path: Path, payload: Any) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, encoded)


def relative_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path.relative_to(root)
