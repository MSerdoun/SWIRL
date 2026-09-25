import json

import numpy as np
import pytest
from pydantic import ValidationError

import swirl
from swirl import Quantity, SpectralSet, Spectrum
from swirl.preprocess import (
    ProcessingError,
    QCParams,
    Recipe,
    apply,
    correct_splices,
    load_recipe,
    operations,
    run_qc,
    save_recipe,
    upper_hull,
)
from swirl.synthetic import (
    Band,
    EndMember,
    NoiseModel,
    SpliceOffsets,
    add_noise,
    apply_splice_offsets,
    synthesize,
)

MINERALS = ["white_mica", "illite", "chlorite", "hematite"]


@pytest.fixture
def truth(synthetic_dir):
    return json.loads((synthetic_dir / "truth.json").read_text())["spectra"]


def load(synthetic_dir, name):
    return swirl.read(synthetic_dir / f"{name}.txt")[0]


def line_spectrum(slope=1e-4, intercept=0.2, wl=None, name="line"):
    wl = np.arange(350.0, 2501.0) if wl is None else wl
    return Spectrum(wavelength=wl, values=intercept + slope * (wl - 350), name=name)


# --- registry -----------------------------------------------------------------------------


def test_operations_registered():
    names = {op.name for op in operations()}
    assert {"crop", "mask", "resample", "splice_correction", "smooth", "continuum_removal"} <= names


def test_every_parameter_has_a_description():
    for op in operations():
        for name, field in op.params.model_fields.items():
            assert field.description, f"{op.name}.{name} has no description"


def test_misspelt_parameter_rejected():
    with pytest.raises(ValidationError):
        apply("smooth", line_spectrum(), windw=11)


def test_unknown_operation():
    with pytest.raises(ProcessingError, match="unknown operation"):
        apply("nope", line_spectrum())


def test_apply_records_step_with_full_params():
    out = apply("smooth", line_spectrum(), window=7)
    assert isinstance(out, Spectrum)
    step = out.history[-1]
    assert step.name == "smooth"
    assert dict(step.params) == {"method": "savgol", "window": 7, "polyorder": 2}


# --- crop / mask / resample --------------------------------------------------------------


def test_crop():
    out = apply("crop", line_spectrum(), start=2000, stop=2400)
    assert out.wavelength[0] == 2000 and out.wavelength[-1] == 2400
    with pytest.raises(ProcessingError):
        apply("crop", line_spectrum(), start=10, stop=20)
    with pytest.raises(ValidationError):
        apply("crop", line_spectrum(), start=2400, stop=2000)


def test_mask():
    out = apply("mask", line_spectrum(), ranges=[(1350, 1450), (1800, 1950)])
    wl = out.wavelength
    assert np.isnan(out.values[(wl >= 1350) & (wl <= 1450)]).all()
    assert np.isfinite(out.values[(wl > 1450) & (wl < 1800)]).all()


def test_resample_linear_is_exact_on_a_line():
    s = line_spectrum()
    out = apply("resample", s, start=400, stop=2400, step=10)
    np.testing.assert_allclose(out.values, 0.2 + 1e-4 * (out.wavelength - 350))
    assert out.wavelength.size == 201


def test_resample_outside_and_gaps_are_nan():
    s = apply("mask", line_spectrum(), ranges=[(1000, 1010)])
    out = apply("resample", s, start=300, stop=1100, step=5, method="pchip")
    assert np.isnan(out.values[out.wavelength < 350]).all()
    assert np.isnan(out.values[(out.wavelength >= 1000) & (out.wavelength <= 1010)]).all()
    assert np.isfinite(out.values[(out.wavelength >= 350) & (out.wavelength < 995)]).all()


# --- splice ------------------------------------------------------------------------------


@pytest.mark.parametrize("mineral", MINERALS)
def test_splice_recovers_known_offsets_without_noise(mineral, truth, synthetic_dir):
    offsets = truth[f"{mineral}_noisy"]["splice_offsets"]
    clean = load(synthetic_dir, mineral)
    stepped = apply_splice_offsets(clean, SpliceOffsets(**offsets))
    out = apply("splice_correction", stepped)
    # Residual = curvature bias of the default linear fit over 20 bands (measured <= 7e-5).
    np.testing.assert_allclose(out.values, clean.values, rtol=1e-4)
    factors = out.meta["splice_corrections"]
    assert factors[0] == pytest.approx(1 / (1 + offsets["vnir"]), rel=1e-4)
    assert factors[1] == 1.0
    assert factors[2] == pytest.approx(1 / (1 + offsets["swir2"]), rel=1e-4)


@pytest.mark.parametrize("mineral", MINERALS)
def test_splice_on_noisy_spectra_within_noise(mineral, truth, synthetic_dir):
    offsets = truth[f"{mineral}_noisy"]["splice_offsets"]
    clean, noisy = load(synthetic_dir, mineral), load(synthetic_dir, f"{mineral}_noisy")
    out = apply("splice_correction", noisy)
    factors = out.meta["splice_corrections"]
    assert factors[0] == pytest.approx(1 / (1 + offsets["vnir"]), abs=0.01)
    assert factors[2] == pytest.approx(1 / (1 + offsets["swir2"]), abs=0.01)
    before = np.abs(noisy.values / clean.values - 1).mean()
    after = np.abs(out.values / clean.values - 1).mean()
    assert after < before


def test_splice_additive_and_other_reference():
    s = line_spectrum()
    wl = s.wavelength
    stepped = s.values + np.where(wl <= 1000, 0.01, 0.0) + np.where(wl > 1800, -0.02, 0.0)
    fixed, corr = correct_splices(wl, stepped, [1000, 1800], method="additive")
    np.testing.assert_allclose(fixed, s.values, atol=1e-10)
    assert corr == pytest.approx([-0.01, 0.0, 0.02])
    # reference = VNIR: VNIR untouched, the others shifted up to it
    fixed0, _ = correct_splices(wl, stepped, [1000, 1800], reference_segment=0, method="additive")
    np.testing.assert_allclose(fixed0[wl <= 1000], stepped[wl <= 1000])
    np.testing.assert_allclose(fixed0, s.values + 0.01, atol=1e-10)


def test_splice_boundaries_from_metadata():
    s = line_spectrum()
    stepped = Spectrum(
        wavelength=s.wavelength,
        values=s.values * np.where(s.wavelength <= 1000, 1.03, 1.0),
        name="x",
        meta={"splice_wavelengths": [1000.0, 1830.0]},
    )
    out = apply("splice_correction", stepped, boundaries="metadata")
    np.testing.assert_allclose(out.values, s.values, rtol=1e-9)
    with pytest.raises(ProcessingError, match="splice_wavelengths"):
        apply("splice_correction", line_spectrum(), boundaries="metadata")


def test_splice_skips_empty_segments():
    s = apply("crop", line_spectrum(), start=1300, stop=2500)
    out = apply("splice_correction", s)
    assert out.meta["splice_corrections"][0] == 1.0


def test_splice_param_validation():
    with pytest.raises(ValidationError):
        apply("splice_correction", line_spectrum(), boundaries=[1800, 1000])
    with pytest.raises(ValidationError):
        apply("splice_correction", line_spectrum(), reference_segment=3)
    with pytest.raises(ValidationError):
        apply("splice_correction", line_spectrum(), fit_bands=2, fit_degree=2)


# --- smooth ------------------------------------------------------------------------------


@pytest.mark.parametrize("mineral", MINERALS)
def test_smoothing_reduces_noise(mineral, synthetic_dir):
    clean = load(synthetic_dir, mineral)
    noisy = add_noise(clean, np.random.default_rng(1), NoiseModel())
    smoothed = apply("smooth", noisy, window=11)
    rms = lambda s: np.sqrt(np.mean((s.values - clean.values) ** 2))  # noqa: E731
    assert rms(smoothed) < 0.6 * rms(noisy)


def test_savgol_preserves_a_line_and_moving_average_runs():
    s = line_spectrum()
    np.testing.assert_allclose(apply("smooth", s).values, s.values, atol=1e-12)
    assert apply("smooth", s, method="moving_average", window=5).n_bands == s.n_bands


def test_smooth_does_not_cross_gaps():
    s = apply("mask", line_spectrum(slope=0), ranges=[(1000, 1005)])
    out = apply("smooth", s, window=5)
    assert np.isnan(out.values[650:656]).all()
    assert np.isfinite(out.values[:650]).all()


def test_smooth_validation():
    with pytest.raises(ValidationError):
        apply("smooth", line_spectrum(), window=10)
    irregular = line_spectrum(wl=np.array([400.0, 401, 403, 404, 405, 407, 410]))
    with pytest.raises(ProcessingError, match="regular"):
        apply("smooth", irregular, window=3)


# --- continuum ---------------------------------------------------------------------------


def test_upper_hull_of_concave_curve_is_the_curve():
    x = np.linspace(0, 1, 50)
    y = 1 - (x - 0.5) ** 2
    np.testing.assert_allclose(upper_hull(x, y), y)


def test_isolated_band_depth_after_continuum_removal():
    em = EndMember("t", "t", ((350.0, 0.3), (2500.0, 0.6)), (Band(2200.0, 30.0, 0.25),))
    cr = apply("continuum_removal", synthesize(em), start=2000, stop=2400)
    assert cr.quantity is Quantity.CONTINUUM_REMOVED
    assert cr.wavelength[0] == 2000 and cr.wavelength[-1] == 2400
    i = int(np.argmin(cr.values))
    assert cr.wavelength[i] == 2200
    assert 1 - cr.values[i] == pytest.approx(0.25, abs=1e-9)


@pytest.mark.parametrize("mineral", MINERALS)
def test_continuum_removed_is_at_most_one(mineral, synthetic_dir):
    cr = apply("continuum_removal", load(synthetic_dir, mineral))
    assert np.nanmax(cr.values) <= 1 + 1e-12
    assert cr.values[0] == pytest.approx(1) and cr.values[-1] == pytest.approx(1)


def test_continuum_needs_reflectance():
    cr = apply("continuum_removal", line_spectrum())
    with pytest.raises(ProcessingError, match="reflectance"):
        apply("continuum_removal", cr)


# --- QC ----------------------------------------------------------------------------------


def test_qc_on_synthetic_set(synthetic_dir):
    spectra = [load(synthetic_dir, m) for m in MINERALS]
    spectra += [load(synthetic_dir, f"{m}_noisy") for m in MINERALS]
    results = {r.name: r for r in run_qc(SpectralSet.from_spectra(spectra))}
    for m in MINERALS:
        assert results[m].ok
        assert results[m].metrics["max_splice_step"] < 1e-4
        assert 0.001 < results[f"{m}_noisy"].metrics["noise_rms"] < 0.004
    assert "splice_step" in results["illite_noisy"].flags


def test_qc_thresholds_are_settable_and_can_be_disabled(synthetic_dir):
    sset = SpectralSet.from_spectra([load(synthetic_dir, "hematite")])
    (r,) = run_qc(sset, QCParams(min_mean_reflectance=0.5))
    assert r.flags == ("low_albedo",)
    (r,) = run_qc(sset, QCParams(min_mean_reflectance=None, max_reflectance=0.1))
    assert r.flags == ("above_max",)


def test_qc_missing_bands():
    s = apply("mask", line_spectrum(), ranges=[(1350, 1500)])
    (r,) = run_qc(SpectralSet.from_spectra([s]))
    assert "missing_bands" in r.flags


# --- recipes -----------------------------------------------------------------------------

RECIPE = """
name = "test"

[[steps]]
op = "splice_correction"

[[steps]]
op = "smooth"
window = 9

[[steps]]
op = "continuum_removal"
start = 1300
stop = 2500
"""


def test_recipe_from_toml_runs_in_order(tmp_path, synthetic_dir):
    path = tmp_path / "r.toml"
    path.write_text(RECIPE)
    recipe = load_recipe(path)
    out = recipe.run([load(synthetic_dir, "illite_noisy")])
    assert out.quantity is Quantity.CONTINUUM_REMOVED
    assert [h.name for h in out[0].history][-3:] == [
        "splice_correction",
        "smooth",
        "continuum_removal",
    ]
    save_recipe(recipe, tmp_path / "r.json")
    assert load_recipe(tmp_path / "r.json") == recipe


def test_recipe_errors_name_the_step():
    with pytest.raises(ProcessingError, match="step 2"):
        Recipe.from_dict(
            {"steps": [{"op": "crop", "start": 1, "stop": 2}, {"op": "smooth", "w": 3}]}
        )
    with pytest.raises(ProcessingError, match="unknown operation"):
        Recipe.from_dict({"steps": [{"op": "nope"}]})
    with pytest.raises(ProcessingError, match="non-empty"):
        Recipe.from_dict({"steps": []})


def test_qhull_hull_matches_reference_chain(synthetic_dir):
    """The qhull-based upper hull equals the monotone-chain reference (random + real shapes)."""
    from swirl.preprocess.continuum import _upper_chain_python

    rng = np.random.default_rng(0)
    cases = [(np.arange(500.0), rng.random(500)) for _ in range(20)]
    for m in MINERALS:
        s = load(synthetic_dir, f"{m}_noisy")
        cases.append((s.wavelength, s.values))
    cases.append((np.arange(10.0), np.ones(10)))  # flat: qhull cannot, fallback must
    for x, y in cases:
        ref = np.interp(x, x[_upper_chain_python(x, y)], y[_upper_chain_python(x, y)])
        np.testing.assert_allclose(upper_hull(x, y), ref, rtol=0, atol=1e-12)
