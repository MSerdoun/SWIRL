import json
import math

import numpy as np
import pytest
from pydantic import ValidationError

import swirl
from swirl import Quantity, Spectrum
from swirl.features import BandDefinition, BandParams, band_table, extract_bands, write_band_table
from swirl.preprocess import ProcessingError, Recipe, apply
from swirl.synthetic import (
    Band,
    EndMember,
    NoiseModel,
    add_noise,
    generative_bands,
    load_end_members,
    synthesize,
    truth_in_window,
)

WL = np.arange(350.0, 2501.0)
ONE_BAND = [BandDefinition(name="B", center=2200, lo=2150, hi=2260)]


def cr_band(center, fwhm, depth, wl=WL):
    g = np.exp(-4 * math.log(2) * (wl - center) ** 2 / fwhm**2)
    return Spectrum(wavelength=wl, values=1 - depth * g, name="b", quantity="continuum_removed")


def measure(spectrum, **kw):
    (r,) = extract_bands(spectrum, BandParams(bands=ONE_BAND, ratios=[], **kw))
    return r.bands["B"]


@pytest.mark.parametrize("method", ["parabola", "gaussian"])
def test_isolated_band_on_grid_point(method):
    m = measure(cr_band(2203, 40, 0.3), position_method=method)
    assert m.status == "minimum"
    assert m.position == pytest.approx(2203, abs=1e-3)
    assert m.depth == pytest.approx(0.3, abs=1e-9)
    assert m.width == pytest.approx(40, abs=0.05)
    assert m.asymmetry == pytest.approx(0, abs=1e-3)


def test_off_grid_band_position():
    s = cr_band(2203.4, 40, 0.3)
    assert measure(s, position_method="minimum").position == 2203
    assert measure(s, position_method="parabola").position == pytest.approx(2203.4, abs=0.01)
    assert measure(s, position_method="gaussian").position == pytest.approx(2203.4, abs=1e-4)


def test_fitted_depth_and_min_depth():
    s = cr_band(2203.4, 40, 0.3)
    assert measure(s, depth_at="fitted", position_method="gaussian").depth == pytest.approx(0.3)
    m = measure(s, min_depth=0.5)
    assert m.status == "absent" and math.isnan(m.position)


def test_asymmetric_band_sign():
    left = cr_band(2200, 30, 0.3)
    right = cr_band(2215, 30, 0.15)
    s = Spectrum(
        wavelength=WL, values=left.values * right.values, name="a", quantity="continuum_removed"
    )
    assert measure(s).asymmetry > 0.05


def test_shoulder_detection():
    # A shallow band on the wing of a deep one: no local minimum in its window.
    main = cr_band(2210, 40, 0.4)
    shoulder = cr_band(2165, 20, 0.05)
    s = Spectrum(
        wavelength=WL, values=main.values * shoulder.values, name="s", quantity="continuum_removed"
    )
    bands = [BandDefinition(name="B", center=2165, lo=2150, hi=2180)]
    (r,) = extract_bands(s, BandParams(bands=bands, ratios=[]))
    assert r.bands["B"].status == "shoulder"
    assert r.bands["B"].position == pytest.approx(2165, abs=4)
    (r,) = extract_bands(s, BandParams(bands=bands, ratios=[], shoulder_detection=False))
    assert r.bands["B"].status == "absent"


def test_window_without_data():
    s = apply("crop", cr_band(2200, 40, 0.3), start=350, stop=2100)
    assert measure(s).status == "no_data"


def test_local_continuum_on_reflectance():
    em = EndMember("t", "t", ((350.0, 0.3), (2500.0, 0.6)), (Band(2203.0, 30.0, 0.25),))
    refl = synthesize(em)
    m = measure(refl, continuum="local")
    assert m.position == pytest.approx(2203, abs=0.05)
    assert m.continuum == "local"
    auto = measure(refl)  # auto -> local for reflectance
    assert auto.continuum == "local"
    with pytest.raises(ProcessingError, match="continuum_removal"):
        measure(refl, continuum="input")


def test_ratios():
    s = Spectrum(
        wavelength=WL,
        values=cr_band(2200, 30, 0.4).values * cr_band(2350, 30, 0.1).values,
        name="r",
        quantity="continuum_removed",
    )
    bands = [
        BandDefinition(name="A", center=2200, lo=2170, hi=2230),
        BandDefinition(name="M", center=2350, lo=2320, hi=2380),
    ]
    (r,) = extract_bands(s, BandParams(bands=bands, ratios=[("M", "A")], ratio_epsilon=0))
    assert r.ratios["log(M/A)"] == pytest.approx(math.log(0.1 / 0.4), abs=1e-3)
    (r,) = extract_bands(s, BandParams(bands=bands, ratios=[("M", "A")], ratio_scale="linear"))
    assert r.ratios["ratio(M/A)"] == pytest.approx(0.25, abs=1e-3)


def test_param_validation():
    with pytest.raises(ValidationError):
        BandDefinition(name="x", center=2300, lo=2100, hi=2200)
    with pytest.raises(ValidationError):
        BandParams(ratios=[("nope", "AlOH")])
    with pytest.raises(ValidationError):
        BandParams(fit_points=4)
    with pytest.raises(ValidationError):
        BandParams(bands=[ONE_BAND[0], ONE_BAND[0]], ratios=[])
    with pytest.raises(ValidationError):
        BandParams(windw=3)


def test_synthetic_truth_helpers(synthetic_dir):
    s = swirl.read(synthetic_dir / "illite_noisy.txt")[0]
    assert len(generative_bands(s)) == 5
    assert truth_in_window(s, 2185, 2225).center == 2205
    assert truth_in_window(s, 1460, 1500) is None


RECIPE = Recipe.from_dict(
    {
        "steps": [
            {"op": "splice_correction"},
            {"op": "smooth", "window": 11},
            {"op": "continuum_removal", "start": 1300, "stop": 2500},
        ]
    }
)
MAIN_BANDS = [
    ("white_mica", "OH1400"),
    ("white_mica", "AlOH"),
    ("white_mica", "MgOH"),
    ("illite", "OH1400"),
    ("illite", "AlOH"),
    ("chlorite", "OH1400"),
    ("chlorite", "FeOH"),
    ("chlorite", "MgOH"),
]


@pytest.mark.parametrize(("mineral", "band"), MAIN_BANDS)
def test_clean_synthetic_positions_match_truth(mineral, band, synthetic_dir):
    s = swirl.read(synthetic_dir / f"{mineral}.txt")[0]
    p = BandParams()
    (r,) = extract_bands(RECIPE.run([s]), p)
    d = next(b for b in p.bands if b.name == band)
    assert r.bands[band].position == pytest.approx(truth_in_window(s, d.lo, d.hi).center, abs=0.1)


def test_noisy_positions_gaussian_beats_parabola3():
    """Measured over 20 noise draws: see docs/science/band_parameters.md for the full table."""
    em = load_end_members()["illite"]
    clean = synthesize(em)
    errs = {"parabola": [], "gaussian": []}
    for seed in range(20):
        noisy = add_noise(clean, np.random.default_rng(seed), NoiseModel())
        out = RECIPE.run([noisy])
        for method in errs:
            (r,) = extract_bands(out, BandParams(position_method=method))
            errs[method].append(r.bands["AlOH"].position - 2205)
    rms = {k: float(np.sqrt(np.mean(np.square(v)))) for k, v in errs.items()}
    assert rms["gaussian"] < 0.2
    assert rms["parabola"] < 1.0
    assert rms["gaussian"] < rms["parabola"]


def test_table_and_csv(tmp_path, synthetic_dir):
    spectra = [swirl.read(synthetic_dir / f"{m}.txt")[0] for m in ("illite", "chlorite")]
    p = BandParams()
    results = extract_bands(RECIPE.run(spectra), p)
    columns, rows = band_table(results, p)
    assert columns[0] == "spectrum" and "AlOH_position" in columns and "log(MgOH/AlOH)" in columns
    assert len(rows) == 2
    write_band_table(results, p, tmp_path / "b.csv")
    lines = (tmp_path / "b.csv").read_text().splitlines()
    assert lines[0] == "# swirl band parameters"
    assert json.loads(lines[1].split(": ", 1)[1])["position_method"] == "parabola"
    assert lines[2].startswith("spectrum,OH1400_position")
    assert results[0].history[-1].name == "band_parameters"


def test_raw_quantity_rejected():
    raw = Spectrum(wavelength=WL, values=np.ones(WL.size), name="r", quantity=Quantity.RAW)
    with pytest.raises(ProcessingError):
        extract_bands(raw)
