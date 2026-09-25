# Holes and depths

The drill-hole view needs, for each spectrum, a hole and a depth (`hole_id`, `depth_from`,
`depth_to` metadata). When the files do not carry them, SWIRL reads them for you — GUI:
**Spectra panel → Holes & depths** (map-marker button), or the button in the empty
drill-hole view. Nothing is applied before *Apply*; the files are never touched — only the
loaded spectra's metadata change, and each change is recorded in their history.

## From the names, by example (no regular expressions)

1. Pick an example name, e.g. `SYN_02_354`. It is cut into parts: `SYN` `_` `02` `_` `354`.
2. Choose **Hole ID** and click the first and last part of the hole (`SYN` … `02`), then
   **Depth** and click `354`. Or press **Suggest** (depth = the last number, hole = what
   precedes it) and check.
3. The preview shows every name read: holes found with their sample counts and depth
   ranges, names not read, and warnings (holes with a single sample — often a misread
   name —, several samples at the same depth).
4. If some names are not read, **add another example** on one of them; SWIRL finds a rule
   that satisfies all the examples (or one rule per example when their structures differ).
5. **Apply.**

SWIRL keeps the *structure* of the example, not its values: `SYN_02_354` teaches it to read
`SYN_01_357` as hole `SYN_01`, depth 357, and `SYN_02_301.5` as 301.5. Depths are integers
or decimals (`354`, `354.5`, `354,5`). The rule is shown in words, e.g. *"hole = shaped like
letters_digits, then '_', depth = a number, optionally anything after a separator"*.

The names can be the spectrum names (the ASD file names, or the column headers of a text
export) or the names of the files they were read from.

## From a sample table

Choose a CSV / TSV exported from your sample sheet (one row per sample). The delimiter, a
decimal comma and the columns are detected (`SampleID`, `Hole ID`/`BHID`, `From`/`Depth`,
`To`…); change them if needed. Samples are matched by name, ignoring case and file
extensions (`.asd`) by default. The preview reports spectra not in the table and table rows
with no spectrum.

## Trying it on synthetic data

* GUI: flask menu → *Synthetic files, hole & depth in the names* (122 spectra: SYN_01 and
  SYN_03 with integer depths, SYN_02 every 1.5 m, a replicate `SYN_03_110_rep` and a
  `WHITE_REF`).
* Files on disk: `swirl synth-names some_folder/` writes the same 122 files (hole and depth
  only in their names) and `samples.csv`; drop them in the GUI.

## From Python

```python
from swirl.naming import NamingExample, infer_rules, apply_rules

ex = NamingExample(name="SYN_02_354", hole=(0, 6), depth=(7, 10))
rules = infer_rules([ex], names).rules
apply_rules(rules, ["SYN_01_357"])        # [("SYN_01", 357.0)]
```
