import numpy as np
import pytest

from swirl import ProcessingStep, Quantity, SpectralSet, Spectrum


def make(name="s", values=None, wl=None, **kw):
    wl = np.array([400.0, 500.0, 600.0]) if wl is None else wl
    values = np.array([0.1, 0.2, 0.3]) if values is None else values
    return Spectrum(wavelength=wl, values=values, name=name, **kw)


class TestSpectrum:
    def test_rejects_non_increasing_wavelength(self):
        with pytest.raises(ValueError, match="strictly increasing"):
            make(wl=np.array([400.0, 400.0, 600.0]))

    def test_rejects_nan_wavelength(self):
        with pytest.raises(ValueError, match="non-finite"):
            make(wl=np.array([400.0, np.nan, 600.0]))

    def test_rejects_length_mismatch(self):
        with pytest.raises(ValueError, match="same length"):
            make(values=np.array([0.1, 0.2]))

    def test_nan_values_allowed(self):
        assert np.isnan(make(values=np.array([0.1, np.nan, 0.3])).values[1])

    def test_arrays_are_copied_and_read_only(self):
        vals = np.array([0.1, 0.2, 0.3])
        s = make(values=vals)
        vals[0] = 9.0
        assert s.values[0] == 0.1
        with pytest.raises(ValueError):
            s.values[0] = 1.0

    def test_meta_is_read_only(self):
        s = make(meta={"hole_id": "DH1"})
        with pytest.raises(TypeError):
            s.meta["hole_id"] = "DH2"  # type: ignore[index]

    def test_derive_appends_history_and_keeps_identity(self):
        s = make(meta={"hole_id": "DH1"})
        step = ProcessingStep("double", {"factor": 2})
        d = s.derive(step, values=s.values * 2)
        assert d.history == (step,)
        assert d.name == s.name and d.meta["hole_id"] == "DH1"
        np.testing.assert_allclose(d.values, [0.2, 0.4, 0.6])
        assert s.history == ()

    def test_quantity_coerced(self):
        assert make(quantity="continuum_removed").quantity is Quantity.CONTINUUM_REMOVED


class TestSpectralSet:
    def test_from_spectra(self):
        ss = SpectralSet.from_spectra([make("a"), make("b", values=np.array([1.0, 2, 3]) / 10)])
        assert len(ss) == 2 and ss.names == ("a", "b")
        assert ss.values.shape == (2, 3)
        assert ss[1].name == "b"
        assert [s.name for s in ss] == ["a", "b"]

    def test_rejects_different_grids(self):
        other = make("b", wl=np.array([400.0, 500.0, 601.0]))
        with pytest.raises(ValueError, match="resample explicitly"):
            SpectralSet.from_spectra([make("a"), other])

    def test_rejects_mixed_quantities(self):
        other = make("b", quantity=Quantity.CONTINUUM_REMOVED)
        with pytest.raises(ValueError, match="continuum_removed"):
            SpectralSet.from_spectra([make("a"), other])

    def test_derive_applies_step_to_every_member(self):
        ss = SpectralSet.from_spectra([make("a"), make("b")])
        step = ProcessingStep("noop")
        out = ss.derive(step, values=ss.values)
        assert all(s.history == (step,) for s in out)

    def test_values_read_only(self):
        ss = SpectralSet.from_spectra([make("a")])
        with pytest.raises(ValueError):
            ss.values[0, 0] = 1.0
