# Prinny 2 dedicated profile

V7.0 compatibility grade C means that the Prinny 1 game profile cannot be
applied unchanged. It does not mean that the shared PSP/NISPACK/LZS/font
engines are unusable.

## Reused only after verification

- PSP image extraction
- NISPACK parser
- LZS decompressor
- START archive parser
- Shift-JIS candidate scanner
- font.fnt/font.txp inspector
- Expected Write and source-hash validation

## Always separate from Prinny 1

- translation catalog and translator wording
- resource names and offsets
- BOOT.BIN/EBOOT.BIN locations
- control-code rules
- font allocation output
- patch and build manifests

No Prinny 1 translation or fixed offset is copied automatically.
