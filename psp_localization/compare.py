from __future__ import annotations

from collections import Counter
from typing import Any


def _by_path(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in analysis.get("files", [])}


def compare_disc_analyses(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    left_files = _by_path(left)
    right_files = _by_path(right)
    left_names = set(left_files)
    right_names = set(right_files)
    common = sorted(left_names & right_names)
    only_left = sorted(left_names - right_names)
    only_right = sorted(right_names - left_names)

    same_size = []
    same_content = []
    changed = []
    for name in common:
        a = left_files[name]
        b = right_files[name]
        if int(a.get("size", -1)) == int(b.get("size", -2)):
            same_size.append(name)
        if (
            a.get("hash_kind") == b.get("hash_kind")
            and a.get("hash") == b.get("hash")
        ):
            same_content.append(name)
        else:
            changed.append(name)

    denominator = max(1, len(left_names | right_names))
    path_overlap = len(common) / denominator
    important_common = [
        name for name in common
        if left_files[name].get("important") or right_files[name].get("important")
    ]
    important_changed = [name for name in changed if name in important_common]

    return {
        "format": "psp_disc_compare_v1",
        "left_game": left.get("game", {}),
        "right_game": right.get("game", {}),
        "left_file_count": len(left_names),
        "right_file_count": len(right_names),
        "common_file_count": len(common),
        "path_overlap_ratio": round(path_overlap, 6),
        "same_size_count": len(same_size),
        "same_content_count": len(same_content),
        "changed_file_count": len(changed),
        "important_common_count": len(important_common),
        "important_changed_count": len(important_changed),
        "only_left": only_left,
        "only_right": only_right,
        "changed": changed,
        "same_content": same_content,
        "suffix_counts_left": dict(Counter(item.get("suffix", "") for item in left_files.values())),
        "suffix_counts_right": dict(Counter(item.get("suffix", "") for item in right_files.values())),
        "status": "pass",
    }
