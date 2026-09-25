import json

import numpy as np
import pytest

import swirl
from swirl.synthetic import (
    Band,
    EndMember,
    NoiseModel,
    SpliceOffsets,
    apply_splice_offsets,
    continuum,
    default_grid,
    generate_sample_set,
    load_end_members,
    mix,
    synthesize,
)


def test_bundled_end_members():
    ems = load_end_members()
    assert set(ems) == {"white_mica", "illite", "chlorite", "hematite"}


def test_default_grid():
    wl = default_grid()
    assert wl[0] == 350 and wl[-1] == 2500 and wl.size == 2151


def test_isolated_band_depth_is_exact():
    em = EndMember("t", "t", ((350.0, 0.5), (2500.0, 0.5)), (Band(2200.0, 30.0, 0.25),))
    s = synthesize(em)
    i = int(np.argmin(s.values))
    assert s.wavelength[i] == 2200.0
    assert 1 - s.values[i] / continuum(em, s.wavelength)[i] == pytest.approx(0.25)


def test_band_validation():
    with pytest.raises(ValueError):
        Band(2200.0, 30.0, 1.0)
    with pytest.raises(ValueError):
        Band(2200.0, 0.0, 0.1)


def test_mix():
    ems = load_end_members()
    a, b = synthesize(ems["illite"]), synthesize(ems["chlorite"])
    m = mix([a, b], [0.7, 0.3], "ill70_chl30")
    np.testing.assert_allclose(m.values, 0.7 * a.values + 0.3 * b.values)
    with pytest.raises(ValueError):
        mix([a, b], [0.7, 0.2], "bad")


def test_noise_sigma_rises_at_both_ends():
    sigma = NoiseModel().sigma(default_grid())
    mid = sigma[1000]
    assert sigma[0] > 3 * mid and sigma[-1] > 3 * mid


def test_splice_offsets_scale_only_outer_detectors():
    s = synthesize(load_end_members()["illite"])
    out = apply_splice_offsets(s, SpliceOffsets(vnir=0.02, swir2=-0.01))
    ratio = out.values / s.values
    wl = s.wavelength
    np.testing.assert_allclose(ratio[wl <= 1000], 1.02)
    np.testing.assert_allclose(ratio[(wl > 1000) & (wl <= 1800)], 1.0)
    np.testing.assert_allclose(ratio[wl > 1800], 0.99)


def test_generation_is_deterministic(tmp_path):
    t1 = generate_sample_set(tmp_path / "a")
    t2 = generate_sample_set(tmp_path / "b")
    assert t1 == t2
    a = swirl.read(tmp_path / "a" / "illite_noisy.txt")[0]
    b = swirl.read(tmp_path / "b" / "illite_noisy.txt")[0]
    np.testing.assert_array_equal(a.values, b.values)


def test_committed_examples_match_generator(tmp_path, synthetic_dir):
    """Guard: the files in examples/ are exactly what the generator produces."""
    generate_sample_set(tmp_path)
    committed = json.loads((synthetic_dir / "truth.json").read_text())
    fresh = json.loads((tmp_path / "truth.json").read_text())
    assert committed == fresh
    for entry in fresh["spectra"].values():
        c = swirl.read(synthetic_dir / entry["file"])[0]
        f = swirl.read(tmp_path / entry["file"])[0]
        np.testing.assert_allclose(c.values, f.values, atol=2e-6)
