from __future__ import annotations

import struct
from pathlib import Path

import pytest

from core.nsf_string import NSFStringExtractor
from profiles.prinny.probe import compare_prinny_profiles
from profiles.prinny.qa import encode_text, visual_width
from psp_localization.compare import compare_disc_analyses
from psp_localization.iso import PSPImageError, find_disc_root
from psp_localization.sfo import SFOError, parse_sfo_bytes
from psp_localization.string_scan import scan_sjis_candidates


def build_sfo(values: dict[str, tuple[int, bytes]]) -> bytes:
    keys = bytearray()
    value_blob = bytearray()
    entries = bytearray()
    key_offsets: dict[str, int] = {}

    for key in values:
        key_offsets[key] = len(keys)
        keys.extend(key.encode("utf-8") + b"\0")

    entry_count = len(values)
    key_table_offset = 0x14 + entry_count * 0x10
    data_table_offset = (key_table_offset + len(keys) + 3) & ~3

    for key, (value_format, raw) in values.items():
        value_offset = len(value_blob)
        capacity = (len(raw) + 3) & ~3
        value_blob.extend(raw)
        value_blob.extend(b"\0" * (capacity - len(raw)))
        entries.extend(
            struct.pack(
                "<HHIII",
                key_offsets[key],
                value_format,
                len(raw),
                capacity,
                value_offset,
            )
        )

    header = bytearray(0x14)
    header[:4] = b"\x00PSF"
    struct.pack_into("<I", header, 4, 0x00000101)
    struct.pack_into("<III", header, 8, key_table_offset, data_table_offset, entry_count)
    padding = b"\0" * (data_table_offset - key_table_offset - len(keys))
    return bytes(header + entries + keys + padding + value_blob)


def test_parse_sfo_string_and_integer() -> None:
    data = build_sfo(
        {
            "DISC_ID": (0x0204, b"ULUS-00001\0"),
            "TITLE": (0x0204, "테스트".encode("utf-8") + b"\0"),
            "PARENTAL_LEVEL": (0x0404, struct.pack("<I", 5)),
        }
    )
    parsed = parse_sfo_bytes(data)
    assert parsed["DISC_ID"] == "ULUS-00001"
    assert parsed["TITLE"] == "테스트"
    assert parsed["PARENTAL_LEVEL"] == 5


def test_parse_sfo_rejects_invalid_magic() -> None:
    with pytest.raises(SFOError):
        parse_sfo_bytes(b"not a psf")


def test_find_disc_root_accepts_root_and_psp_game(tmp_path: Path) -> None:
    root = tmp_path / "disc"
    psp_game = root / "PSP_GAME"
    psp_game.mkdir(parents=True)
    assert find_disc_root(root) == root
    assert find_disc_root(psp_game) == root
    with pytest.raises(PSPImageError):
        find_disc_root(tmp_path / "missing")


def test_compare_disc_analyses() -> None:
    left = {
        "game": {"disc_id": "A"},
        "files": [
            {"path": "PSP_GAME/USRDIR/A.DAT", "size": 10, "hash": "x", "hash_kind": "sha1", "important": True, "suffix": ".dat"},
            {"path": "PSP_GAME/USRDIR/B.BIN", "size": 20, "hash": "y", "hash_kind": "sha1", "important": True, "suffix": ".bin"},
        ],
    }
    right = {
        "game": {"disc_id": "B"},
        "files": [
            {"path": "PSP_GAME/USRDIR/A.DAT", "size": 10, "hash": "x", "hash_kind": "sha1", "important": True, "suffix": ".dat"},
            {"path": "PSP_GAME/USRDIR/C.BIN", "size": 30, "hash": "z", "hash_kind": "sha1", "important": True, "suffix": ".bin"},
        ],
    }
    result = compare_disc_analyses(left, right)
    assert result["common_file_count"] == 1
    assert result["same_content_count"] == 1
    assert result["only_left"] == ["PSP_GAME/USRDIR/B.BIN"]
    assert result["only_right"] == ["PSP_GAME/USRDIR/C.BIN"]


def _profile(*, system_names: list[str], resources: list[str], script_names: list[str], glyphs: int = 100) -> dict:
    return {
        "system": {"entries": [{"name": name} for name in system_names]},
        "start": {"resources": [{"name": name} for name in resources]},
        "font": {
            "status": "pass",
            "table_entries": glyphs,
            "txp": {"width": 20, "glyph_height": 14, "pixel_format": 4},
        },
        "script": {"entries": [{"name": name} for name in script_names]},
    }


def test_prinny_profile_grade_a_and_c() -> None:
    base = _profile(
        system_names=["start.lzs", "foo.dat"],
        resources=["font.fnt", "font.txp", "Demo00.dat", "StageInfo00.dat"],
        script_names=["G9DL000.nsf", "G9system.nsf"],
    )
    same = _profile(
        system_names=["start.lzs", "foo.dat"],
        resources=["font.fnt", "font.txp", "Demo00.dat", "StageInfo00.dat"],
        script_names=["G9DL000.nsf", "G9system.nsf"],
    )
    assert compare_prinny_profiles(base, same)["grade"] == "A"

    different = _profile(
        system_names=["different.bin"],
        resources=["other.dat"],
        script_names=["new.nsf"],
        glyphs=999,
    )
    assert compare_prinny_profiles(base, different)["grade"] == "C"


def test_prinny_encoding_width_and_legacy_nsf_cleaner() -> None:
    encoded, unsupported = encode_text("한A", {"한": b"\x81\x40"})
    assert encoded == b"\x81\x40A"
    assert unsupported == []
    width, lines = visual_width("한A\\n글")
    assert width == 30
    assert lines == 2
    assert NSFStringExtractor.clean_text(b"XYZ\x00QQ") == "XYZ"


def test_conservative_sjis_scan_finds_null_terminated_menu_text() -> None:
    text = "タイトルへ".encode("shift_jis")
    data = b"\x00" + text + b"\x00\x01\x02"
    rows = scan_sjis_candidates(data, source_name="BOOT.BIN")
    assert len(rows) == 1
    assert rows[0]["text"] == "タイトルへ"
    assert rows[0]["offset"] == 1


def test_prepare_disc_minimal_and_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from psp_localization import iso as iso_module

    image = tmp_path / "game.iso"
    image.write_bytes(b"fake-iso")
    output = tmp_path / "run" / "game1"
    calls: list[list[str]] = []

    def fake_extract(image_path: Path, extract_dir: Path, *, members=None):
        calls.append(list(members or []))
        (extract_dir / "PSP_GAME/USRDIR").mkdir(parents=True)
        (extract_dir / "PSP_GAME/USRDIR/SYSTEM.DAT").write_bytes(b"system")
        (extract_dir / "PSP_GAME/PARAM.SFO").write_bytes(b"bad-sfo")
        return {"command": ["fake"], "returncode": 0, "requested_members": calls[-1]}

    monkeypatch.setattr(iso_module, "_run_7z_extract", fake_extract)
    root, manifest = iso_module.prepare_disc(image, output, extraction_mode="minimal")
    assert root == output / "iso"
    assert manifest["extraction_mode"] == "minimal"
    assert "PSP_GAME/USRDIR/SYSTEM.DAT" in calls[0]
    result = iso_module.cleanup_prepared_disc(output)
    assert result["status"] == "removed"
    assert not (output / "iso").exists()
    assert (output / "extract_manifest.json").is_file()


def test_safe_cleanup_only_allowlisted_paths(tmp_path: Path) -> None:
    from psp_localization.maintenance import safe_cleanup

    root = tmp_path / "project"
    (root / "core").mkdir(parents=True)
    (root / "workspace/strings").mkdir(parents=True)
    (root / "workspace/strings/large.json").write_bytes(b"x" * 100)
    (root / "workspace/translations/export").mkdir(parents=True)
    protected = root / "workspace/translations/export/translation_master.csv"
    protected.write_text("keep", encoding="utf-8")

    dry = safe_cleanup(root, apply=False)
    assert dry["freed_bytes"] == 0
    assert (root / "workspace/strings/large.json").is_file()

    applied = safe_cleanup(root, apply=True)
    assert applied["freed_bytes"] >= 100
    assert not (root / "workspace/strings").exists()
    assert protected.read_text(encoding="utf-8") == "keep"


def test_prepare_external_storage_moves_and_links_game2(tmp_path: Path) -> None:
    from psp_localization.storage import prepare_external_storage

    project = tmp_path / "project"
    (project / "core").mkdir(parents=True)
    original = project / "game2.iso"
    original.write_bytes(b"prinny2-test-image")
    external_mount = tmp_path / "D"
    external_mount.mkdir()

    config = prepare_external_storage(
        project,
        requested=external_mount,
        migrate_game2=True,
    )
    destination = Path(config["game2_iso"])
    assert destination.read_bytes() == b"prinny2-test-image"
    assert original.is_symlink()
    assert original.resolve() == destination.resolve()
    assert Path(config["run_dir"]).is_dir()
    assert Path(config["report_dir"]).is_dir()
    assert (project / ".psp_toolkit_storage.json").is_file()
