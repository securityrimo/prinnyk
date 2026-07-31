# PSP Localization Studio V7.5 Alpha

## Scope

V7.5 integrates the current Prinny 1 repair track and Prinny 2 localization
track into one offline browser application.

### Implemented

- project dashboard;
- translation editing, filtering, import, and export;
- preliminary byte-capacity checks;
- font preview gallery and provisional layout selection;
- QA and build gates;
- internal candidate classification;
- safety rules and primary references.

### Not implemented

- direct ISO modification in the browser;
- font injection before renderer and code-map evidence is confirmed;
- patches without source hashes and Expected Write evidence;
- automatic rewriting of translator-defined character voice.

## Reference priority

1. https://github.com/mcpads/create-kr-patch-template
2. https://font.emulog.app/#fonts
3. https://github.com/yazzang-homelab/hancharacter/blob/master/GUIDE.ko.md
4. https://github.com/yazzang-homelab/hanpatch
5. The supplied SRWF_F_CUE_BIN_Translation_Editor_v5_2.html for UI and workflow
   reference only. Its SRW-F-specific image and executable logic is not reused.

## Prinny 1 policy

The user's translation wording and character voice are locked. The remaining
runtime corruption, black-square glyphs, residual kanji, truncation, and UI
issues require resource/offset/runtime evidence before another patch is built.

## Prinny 2 policy

Prinny 2 uses a dedicated profile. Prinny 1 translations and fixed offsets are
not copied automatically. Font/layout selection in V7.5 is provisional until
runtime renderer references are confirmed.
