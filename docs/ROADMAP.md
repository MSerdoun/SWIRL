# Roadmap to v0.1 (target: end of December 2026)

Each lot lands (tests green, committed) before the next one starts.

| Lot | Weeks | Content | Status |
|---|---|---|---|
| L1 Foundations | 1 | Repo, CI, data model, provenance, synthetic end-members | **done** |
| L2 Readers | 1–2 | Delimited text (L1), ASD binary v1–8; `.sco` read as text | **done** — ASD awaiting real-file validation |
| L3 Pre-processing | 2–3 | Splice correction, smoothing, resampling, continuum removal, QC flags, recipes, CLI | **done** |
| L4 Interpretation | 4–6 | Absorption features (position, depth, width, asymmetry), configurable scalars, USGS library matching, mineral rules | **band parameters done** (synthetic-validated); library matching and mineral rules to do |
| L5 GUI skeleton | 4–5 | FastAPI + Vue, import, spectrum viewer, live recipe editor (schema-generated forms), QC table, details/history, CSV export | **done** (brought forward) |
| L6 GUI complete | 7–9 | Raw / hull-removed overlay, feature markers, tables, down-hole logs, batch | — |
| L7 Robustness | 10–11 | Exports, provenance in outputs, error handling, docs, tutorials | — |
| L8 Release 0.1 | 12 | Installer, demo dataset, public release | — |

If the schedule slips, L6 is trimmed — never validation.
