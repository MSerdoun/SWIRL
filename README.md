# SWIRL

**Open-source processing, interpretation and visualisation of VNIR-SWIR point spectra
for exploration geology.**

SWIRL aims to be an open, scriptable tool for the workflow exploration geologists run on
point spectrometer data (ASD, TerraSpec, SVC…): import, quality control, pre-processing,
absorption-feature extraction, mineral interpretation, down-hole visualisation and export.

> **Status: pre-alpha (v0.1 in development).** Data model, text and ASD readers, synthetic
> end-members, pre-processing (recipes), QC, absorption-band parameters and a first
> graphical interface exist. Library matching and mineral rules are next — see [docs/ROADMAP.md](docs/ROADMAP.md).

## Install (development)

```bash
git clone https://github.com/MSerdoun/SWIRL.git
cd SWIRL
python -m venv .venv
.venv/bin/pip install -e ".[dev,plot]"
```

Python ≥ 3.11.

## Quick start

```python
import swirl

spectra = swirl.read("examples/data/synthetic/illite_noisy.txt")
s = spectra[0]
print(s)                 # Spectrum(name='illite_noisy', quantity=reflectance, bands=2151, ...)
print(s.history)         # every step that produced this spectrum
```

```python
from swirl.preprocess import apply, load_recipe

s2 = apply("splice_correction", s, reference_segment=1, fit_bands=20)
s3 = apply("smooth", s2, window=11, polyorder=2)
cr = apply("continuum_removal", s3, start=1300, stop=2500)

recipe = load_recipe("examples/recipes/swir_basic.toml")   # the same chain as a file
out = recipe.run(spectra)
```

```bash
swirl info examples/data/synthetic/*.txt     # summarise files
swirl ops                                    # every operation, parameter, default
swirl process examples/recipes/swir_basic.toml data/*.asd --outdir processed/
swirl qc data/*.asd --config examples/recipes/qc.toml
swirl bands data/*.asd --recipe examples/recipes/swir_basic.toml --out bands.csv
swirl synth my_synthetic_set/                # regenerate the synthetic sample set
```

## Graphical interface

```bash
.venv/bin/pip install -e ".[app]"
cd frontend && npm install && npm run build && cd ..   # once, and after frontend changes
swirl app                                               # opens http://127.0.0.1:8765
```

Open ASD / text files (or drop them), tick the spectra to plot, build a recipe on the right —
every parameter form is generated from the operation's parameter model and the plot updates
live — check the quality-control table, inspect each spectrum's metadata and history, and
export the processed spectra as CSV. Recipes load from / save to the same TOML/JSON files
the command line uses.

## Supported formats

| Format | Read | Write | Notes |
|---|---|---|---|
| Delimited text (`.txt`, `.csv`, `.tsv`, `.dat`) | ✓ | ✓ | tab / `;` / `,` / whitespace, decimal point or comma, µm or nm, fraction or percent — every conversion is recorded in the spectrum history |
| ASD binary (`.asd`, file versions 1–8) | ✓ | — | reflectance = target DN / white-reference DN (or the stored reflectance), raw DN or the white reference on request; header metadata kept. **Not yet validated on real instrument files.** |
| `.sco` | ✓ (text reader) | — | read as delimited text |
| `.sed`, `.sig` | planned | — | |

## Principles

* **The library is the product; the GUI is one of its clients.** Everything the GUI does can
  be done from Python or the command line.
* **Nothing is silent.** Unit conversions, rescaling and processing are recorded as
  provenance on every spectrum, and written into exported files.
* **Every algorithm is validated against a reference case** before it is trusted —
  see [docs/science/](docs/science/).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## License

MIT — see [LICENSE](LICENSE).
