# Prinny 1 — Ordinary Terminator Layout Audit (977)

## Result

**PASS**

| Layout | Count |
|---|---:|
| Internal NUL | 651 |
| External NUL | 553 |
| Total | 1204 |

## Reconciliation

The original consolidated-plan builder reserved one byte inside every
patch span for a NUL terminator. The audit proved that the ordinary
records use two layouts:

- `internal_nul`: the terminator is inside the patch span.
- `external_nul`: the entire span is text capacity and the next byte is
  the terminator.

All 489 records rejected by the first builder are verified
external-NUL records. Another 64 external-NUL
records had sufficient spare capacity and therefore did not appear in
the original failure list.

## Validation

- Ordinary records: 1204/1204
- Missing plan records: 0
- Duplicate plan records: 0
- Unknown layouts: 0
- Ambiguous layouts: 0
- Terminator errors: 0
- Existing-text layout errors: 0
- Revised-text capacity overflows: 0

## Provenance

- Source audit SHA1: `cfb0a2964cc48b9a952b5b8870e88495b2c2ad7f`
- Corrected audit SHA1: `5f710e150ae746d92a24e9bbb47c057c01cc25c3`
- Failed-plan report SHA1: `ee7f17df34b571dd4d4aae9396de1e7d0448c785`

## Next gate

Rebuild the consolidated repatch plan with the verified layout recorded
for every ordinary patch. This checkpoint does not modify game data.
