# Prinny 1 — Consolidated Repatch Plan v2 (977)

## Result

**PASS**

| Item | Count |
|---|---:|
| Changed translation IDs | 1,236 |
| Logical occurrences | 1,423 |
| Physical patch records | 1,401 |
| Ordinary patches | 1,204 |
| Direct exact-offset patches | 96 |
| Demo reflow parent patches | 101 |
| Protected external terminators | 553 |
| Modified resources | 9 |

## Ordinary terminator layouts

| Layout | Count |
|---|---:|
| Internal NUL | 651 |
| External NUL | 553 |

## Validation

- Ordinary errors: 0
- Direct-offset errors: 0
- Reflow errors: 0
- Duplicate physical regions: 0
- Physical overlaps: 0
- Protected-region overlaps: 0
- Duplicate logical coverage: 0
- Missing logical coverage: 0
- Extra logical coverage: 0
- No-op patches: 0

## Safety model

The plan applies the expected-write and fail-closed model:

- Every write records its expected current bytes.
- Input resources are treated as immutable.
- External terminators are registered as protected regions.
- Unregistered final differences are forbidden.
- Any mismatch must stop application before a product build is accepted.

## Provenance

- Source Git checkpoint: `75354e4c5fa1fa2cdfa9b30963d97699918bbb54`
- Plan SHA1: `1ac290c44ed18eed251dcee1076c4a690cada2c5`
- Plan size: `1949582` bytes
- Report SHA1: `32560997162b9c91e1caca1a618de2b7461d5ea1`
- Report size: `1150` bytes

The full plan remains under `workspace/` because it contains translated
game text. Git stores this hash-bound checkpoint and its reproducibility
metadata instead.

## Required references

- `hancharacter`: character voice and human-review gates
- `emucap`: PPSSPP runtime evidence and regression capture
- `create-kr-patch-template`: expected writes, registered diffs,
  deterministic builds, and fail-closed application

## Next gate

Apply all 1,401 physical records to a new output directory without
modifying the verified source build. The application stage must recheck
every expected region, preserve file sizes, and reject every
unregistered byte difference.
