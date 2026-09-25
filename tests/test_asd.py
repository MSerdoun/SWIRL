import numpy as np
import pytest
from asd_factory import make_asd

import swirl
from swirl import Quantity
from swirl.io import ASDFormatError, read_asd
from swirl.io.asd import parse_header

WL = np.arange(350.0, 2501.0)
REF_DN = 20000.0 + 5000.0 * np.sin(WL / 300.0)
TRUE_R = 0.3 + 0.2 * np.exp(-(((WL - 2200) / 30) ** 2))
TARGET_DN = TRUE_R * REF_DN


def names(s):
    return [h.name for h in s.history]


def test_header_fields(tmp_path):
    p = make_asd(tmp_path / "s.asd", TARGET_DN, REF_DN)
    h = parse_header(p.read_bytes())
    assert h.version == 7 and h.channels == 2151
    assert (h.first_wavelength, h.wavelength_step) == (350.0, 1.0)
    assert h.data_type == "reflectance" and h.instrument == "FSFR"
    assert h.integration_time_ms == 17 and h.instrument_number == 18123
    assert (h.swir1_gain, h.swir2_gain) == (128, 256)
    assert (h.splice1_wavelength, h.splice2_wavelength) == (1000.0, 1800.0)
    assert h.comments == "core DH01 12.5m"
    assert h.acquired_at.isoformat() == "2026-09-25T10:15:30"


def test_reflectance_is_target_over_reference(tmp_path):
    (s,) = read_asd(make_asd(tmp_path / "DH01_12.5.asd", TARGET_DN, REF_DN))
    assert s.name == "DH01_12.5" and s.quantity is Quantity.REFLECTANCE
    np.testing.assert_allclose(s.wavelength, WL)
    np.testing.assert_allclose(s.values, TRUE_R, rtol=1e-12)
    assert names(s) == ["read_asd", "asd_reflectance_ratio"]
    assert s.meta["asd_reference_description"] == "Spectralon"
    assert s.meta["asd_reference_time"] == "2026-09-25T10:10:00"
    assert s.meta["acquired_at"] == "2026-09-25T10:15:30"
    assert s.meta["splice_wavelengths"] == [1000.0, 1800.0]


def test_stored_reflectance_kept(tmp_path):
    (s,) = read_asd(make_asd(tmp_path / "r.asd", TRUE_R, REF_DN))
    np.testing.assert_allclose(s.values, TRUE_R)
    assert names(s) == ["read_asd", "asd_stored_reflectance"]


def test_raw_and_reference_outputs(tmp_path):
    p = make_asd(tmp_path / "s.asd", TARGET_DN, REF_DN, data_type=0)
    (raw,) = read_asd(p, output="raw")
    (ref,) = read_asd(p, output="reference")
    assert raw.quantity is Quantity.RAW and ref.quantity is Quantity.RAW
    np.testing.assert_allclose(raw.values, TARGET_DN)
    np.testing.assert_allclose(ref.values, REF_DN)


def test_zero_reference_gives_nan(tmp_path):
    ref = REF_DN.copy()
    ref[5] = 0.0
    (s,) = read_asd(make_asd(tmp_path / "s.asd", TARGET_DN, ref))
    assert np.isnan(s.values[5]) and np.isfinite(s.values[6])


def test_version1_float_file_without_reference(tmp_path):
    p = make_asd(tmp_path / "old.asd", TRUE_R, version=b"ASD", data_format=0, value_code="f")
    (s,) = read_asd(p)
    np.testing.assert_allclose(s.values, TRUE_R, rtol=1e-6)
    assert s.history[0].params["value_bytes"] == 4


def test_version1_dn_without_reference_needs_raw(tmp_path):
    p = make_asd(tmp_path / "old.asd", TARGET_DN, version=b"ASD", data_format=0, value_code="f")
    with pytest.raises(ASDFormatError, match="output='raw'"):
        read_asd(p)
    assert read_asd(p, output="raw")[0].values[0] == pytest.approx(TARGET_DN[0], rel=1e-6)


def test_float_storage_in_v2_plus(tmp_path):
    p = make_asd(tmp_path / "f.asd", TARGET_DN, REF_DN, data_format=0, value_code="f")
    (s,) = read_asd(p)
    np.testing.assert_allclose(s.values, TRUE_R, rtol=1e-5)
    assert s.history[0].params["value_bytes"] == 4


def test_trailing_sections_ignored(tmp_path):
    p = make_asd(tmp_path / "v8.asd", TARGET_DN, REF_DN, version=b"as8", trailer=b"\x01" * 900)
    np.testing.assert_allclose(read_asd(p)[0].values, TRUE_R, rtol=1e-12)


def test_not_an_asd_file(tmp_path):
    p = tmp_path / "x.asd"
    p.write_bytes(b"XYZ" + b"\x00" * 600)
    with pytest.raises(ASDFormatError, match="not an ASD file"):
        read_asd(p)


def test_truncated_file(tmp_path):
    p = make_asd(tmp_path / "t.asd", TARGET_DN, REF_DN)
    p.write_bytes(p.read_bytes()[:3000])
    with pytest.raises(ASDFormatError):
        read_asd(p)


def test_short_file(tmp_path):
    p = tmp_path / "s.asd"
    p.write_bytes(b"as7" + b"\x00" * 10)
    with pytest.raises(ASDFormatError, match="shorter"):
        read_asd(p)


def test_registry_and_set_building(tmp_path):
    a = make_asd(tmp_path / "a.asd", TARGET_DN, REF_DN)
    b = make_asd(tmp_path / "b.asd", TARGET_DN * 0.9, REF_DN)
    sset = swirl.SpectralSet.from_spectra([*swirl.read(a), *swirl.read(b)])
    assert sset.names == ("a", "b")
    np.testing.assert_allclose(sset.values[1], 0.9 * TRUE_R, rtol=1e-12)


def test_asd_to_text_roundtrip(tmp_path):
    (s,) = swirl.read(make_asd(tmp_path / "a.asd", TARGET_DN, REF_DN))
    swirl.write([s], tmp_path / "a.csv")
    (back,) = swirl.read(tmp_path / "a.csv")
    np.testing.assert_allclose(back.values, s.values, atol=1e-6)
    assert names(back) == ["read_asd", "asd_reflectance_ratio", "read_text"]
    assert back.meta["asd_version"] == 7
