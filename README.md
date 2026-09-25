# SWIRL

**Open-source processing, interpretation and visualisation of VNIR-SWIR point spectra
for exploration geology.**

SWIRL aims to be an open, scriptable tool for the workflow exploration geologists run on
point spectrometer data (ASD, TerraSpec, SVC…): import, quality control, pre-processing,
absorption-feature extraction, mineral interpretation, down-hole visualisation and export.

> **Status: pre-alpha (v0.1 in development).** The data model, the delimited-text and ASD
> readers and a synthetic end-member generator exist. Pre-processing, interpretation and the graphical
> interface are next — see [docs/ROADMAP.md](docs/ROADMAP.md).

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

```bash
swirl info examples/data/synthetic/*.txt     # summarise files
swirl synth my_synthetic_set/                # regenerate the synthetic sample set
```

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
