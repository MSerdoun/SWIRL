import numpy as np
import pytest
from conftest import ROOT
from pydantic import ValidationError

import swirl
from swirl import Spectrum
from swirl.drillhole import build_log, holes
from swirl.preprocess import load_recipe
from swirl.synthetic.drillhole import (
    DEFAULT_ZONES,
    DrillholeConfig,
    Zone,
    composition_at,
    synthetic_drillhole,
)


@pytest.fixture(scope="module")
def hole():
    return synthetic_drillhole()


@pytest.fixture(scope="module")
def log(hole):
    recipe = load_recipe(ROOT / "examples" / "recipes" / "swir_basic.toml")
    return build_log(holes(hole)["SYN-DH01"], recipe=recipe)


# --- generator -----------------------------------------------------------------------------


def test_samples_and_metadata(hole):
    assert len(hole) == 200
    first, last = hole[0], hole[-1]
    assert (first.meta["hole_id"], first.meta["depth_from"], first.meta["depth_to"]) == (
        "SYN-DH01",
        0,
        1,
    )
    assert last.meta["depth_to"] == 200
    for s in hole:
        assert sum(s.meta["synthetic_composition"].values()) == pytest.approx(1)
    assert sum(s.meta["synthetic_dark"] for s in hole) == 3


def test_composition_blending():
    assert composition_at(30, DEFAULT_ZONES, 8) == pytest.approx(
        {"white_mica": 0.85, "illite": 0.15}
    )
    at_boundary = composition_at(60, DEFAULT_ZONES, 8)
    assert at_boundary["illite"] == pytest.approx((0.15 + 0.8) / 2)
    assert composition_at(60, DEFAULT_ZONES, 0)["illite"] == pytest.approx(0.8)


def test_aloh_trend_and_determinism(hole):
    centers = [s.meta["synthetic_aloh_center"] for s in hole]
    assert centers[0] == pytest.approx(2196 + 18 * 0.5 / 200)
    assert np.all(np.diff(centers) > 0)
    again = synthetic_drillhole()
    np.testing.assert_array_equal(hole[57].values, again[57].values)
    other = synthetic_drillhole(DrillholeConfig(seed=1))
    assert not np.array_equal(hole[57].values, other[57].values)


def test_config_validation():
    with pytest.raises(ValidationError):
        Zone(top=0, bottom=10, composition={"illite": 0.5})
    with pytest.raises(ValueError, match="unknown end-members"):
        synthetic_drillhole(
            DrillholeConfig(zones=[Zone(top=0, bottom=200, composition={"kaolinite": 1.0})])
        )


# --- grouping ------------------------------------------------------------------------------


def test_holes_grouping_and_order(hole):
    shuffled = hole[::-1]
    wl = hole[0].wavelength
    loose = Spectrum(wavelength=wl, values=hole[0].values, name="no-depth", meta={"hole_id": "X"})
    bare = Spectrum(
        wavelength=wl, values=hole[0].values, name="bare", meta={"hole_id": "B", "depth": "12.5"}
    )
    found = holes([*shuffled, loose, bare])
    assert set(found) == {"SYN-DH01", "B"}
    depths = [s.depth_from for s in found["SYN-DH01"]]
    assert depths == sorted(depths)
    assert found["B"][0].depth == 12.5


# --- the log recovers the known zonation --------------------------------------------------


def test_log_shape(log):
    assert len(log.names) == 200
    assert log.image.shape[0] == 200 and log.image.shape[1] <= 400
    assert log.quantity.value == "continuum_removed"


def test_band_depths_follow_mineral_fractions(log):
    """Linear mixing: band depths correlate linearly with the fractions (QC-passed samples;
    the darkened ones are exactly what QC is there to set aside)."""
    t = log.truth_composition
    ok = ~np.array(["low_albedo" in r.flags for r in log.qc])

    def r(a, band):
        return np.corrcoef(a[ok], np.array(log.bands[band]["depth"], float)[ok])[0, 1]

    assert r(t["chlorite"], "FeOH") > 0.95
    assert r(t["white_mica"] + t["illite"], "AlOH") > 0.95
    # The MgOH window also holds the micas' secondary 2350 nm band: weaker, still clear.
    assert r(t["chlorite"], "MgOH") > 0.8


def test_aloh_position_tracks_white_mica_composition(log):
    wm = log.truth_composition["white_mica"] > 0.6
    pos = np.array(log.bands["AlOH"]["position"], float)[wm]
    truth = log.truth_aloh_center[wm]
    assert np.corrcoef(pos, truth)[0, 1] > 0.9
    # Mixed illite (2205 nm) pulls the mixture position towards 2205: a small bias remains.
    assert abs(np.median(pos - truth)) < 1.5


def test_hematite_zone_is_darker(log):
    d = log.depth
    ok = ~np.array(["low_albedo" in r.flags for r in log.qc])
    top = np.median(log.mean_reflectance[(d < 60) & ok])
    bottom = np.median(log.mean_reflectance[(d > 165) & ok])
    assert bottom < 0.65 * top


def test_dark_samples_flagged(log, hole):
    flagged = {log.names[i] for i, r in enumerate(log.qc) if "low_albedo" in r.flags}
    assert flagged == {s.name for s in hole if s.meta["synthetic_dark"]}


def test_synth_hole_cli_roundtrip(tmp_path):
    from swirl.cli import main

    out = tmp_path / "hole.csv"
    assert main(["synth-hole", str(out), "--seed", "3"]) == 0
    spectra = swirl.read(out)
    found = holes(spectra)
    assert len(found["SYN-DH01"]) == 200
    assert "synthetic_composition" in found["SYN-DH01"][0].spectrum.meta
