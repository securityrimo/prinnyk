# Prinny parallel plan V7.1

## Meaning of grade C

Grade C does not mean that Prinny 2 cannot be localized. It means the game-level
Prinny 1 profile—including resource lists, offsets, executable locations, and
translation assets—must not be reused unchanged.

V7.1 therefore separates:

- shared PSP/NISPACK/LZS/START/font engines;
- Prinny 1 runtime repair evidence;
- Prinny 2 resources, translation catalog, and Expected Write data.

## Translation protection

Prinny 1 dialogue wording and character voice are locked. Automated operations
may report byte capacity, unsupported glyphs, pointer/control-code faults, and
Japanese residue, but do not rewrite the translator's style.

Prinny 2 begins from its own untranslated catalog. Identical-looking Japanese
strings are not automatically assigned Prinny 1 translations without a verified
context match.

## Reference priority

1. https://github.com/mcpads/create-kr-patch-template
2. https://font.emulog.app/#fonts
3. https://github.com/yazzang-homelab/hancharacter/blob/master/GUIDE.ko.md
4. https://github.com/yazzang-homelab/hanpatch
5. The supplied SRWF editor HTML for UI/workflow reference only
