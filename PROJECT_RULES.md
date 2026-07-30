# Korean Patch Project Rules

## Primary references

Every Korean game-patch project must consult these sources first, in this order:

1. https://github.com/mcpads/create-kr-patch-template
2. https://font.emulog.app/#fonts
3. https://github.com/yazzang-homelab/hancharacter/blob/master/GUIDE.ko.md
4. https://github.com/yazzang-homelab/hanpatch

They are mandatory starting references, not the only allowable references.

## Build and binary safety

- Preserve source lineage: record the exact source image/file hash and the parent build used.
- Use Expected Write checks before every binary modification.
- A patch must fail closed when expected bytes, offsets, sizes, or hashes differ.
- Separate original assets, translation assets, generated artifacts, reports, and distributable patches.
- Do not commit copyrighted game images, extracted game files, or generated ISO/CSO images.
- A successful build is not sufficient: retain runtime evidence and tester observations.
- A no-op build must not be reported as a successful repair.

## Translation preservation

- Existing translator-written character voice is `translator_declared` authority.
- Do not automatically flatten, rewrite, polish, or normalize character-specific speech.
- Treat both LOSS (removing established voice) and INVENTION (adding unsupported voice) as defects.
- Automatic edits are limited to mechanically proven defects:
  - encoding or glyph-map failure
  - invalid control code, terminator, pointer, or padding
  - verified byte/slot overflow
  - confirmed untranslated residue where the intended replacement is approved
- Wording changes require translator approval.
- Review-only candidates must remain separate from automatically applied fixes.

## Font policy

- Search Font Share first for a technically compatible and redistributable font.
- Record tile width, tile height, bpp, glyph count, encoding, mapping, source, version, and license.
- Keep original font input, conversion settings, glyph map, encoding map, and generated font hashes.
- Never assume visual compatibility from the font name alone; verify the target renderer and runtime output.

## GitHub checkpoint policy

- Save a source checkpoint whenever the project version reaches a multiple of 0.5:
  `0.5`, `1.0`, `1.5`, `2.0`, ..., `6.5`, `7.0`, and so on.
- Each checkpoint must:
  1. run available source/validation checks;
  2. exclude game images and generated workspaces;
  3. commit source, documentation, configuration, and reproducibility metadata;
  4. create an annotated `vX.Y` tag;
  5. push the current branch and the tag to the configured `origin`.
- If authentication or network push fails, retain the local commit/tag and report the failure honestly.
