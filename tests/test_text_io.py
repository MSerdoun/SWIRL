import numpy as np
import pytest

import swirl
from swirl import ProcessingStep, Spectrum
from swirl.io import TextFormatError, read_text, write_text


def step_names(s):
    return [h.name for h in s.history]


def test_roundtrip_preserves_values_names_meta_history(tmp_path):
    wl = np.arange(350.0, 360.0)
    s = Spectrum(
        wavelength=wl,
        values=np.linspace(0.1, 0.5, wl.size),
        name="DH01_12.5",
        meta={"hole_id": "DH01", "depth_from": 12.5, "note": "é"},
        history=(ProcessingStep("synthesize", {"k": 1}),),
    )
    s2 = s.derive(ProcessingStep("x"), values=s.values * 1.1)
    s2 = Spectrum(wavelength=wl, values=s2.values, name="other", history=s2.history)
    path = tmp_path / "out.csv"
    write_text([s, s2], path)
    back = read_text(path)
    assert [b.name for b in back] == ["DH01_12.5", "other"]
    np.testing.assert_allclose(back[0].values, s.values, atol=1e-6)
    np.testing.assert_allclose(back[0].wavelength, wl)
    assert back[0].meta["depth_from"] == 12.5 and back[0].meta["note"] == "é"
    assert step_names(back[0]) == ["synthesize", "read_text"]
    assert step_names(back[1]) == ["synthesize", "x", "read_text"]


def test_nan_roundtrip(tmp_path):
    s = Spectrum(wavelength=[1000.0, 1001.0, 1002.0], values=[0.2, np.nan, 0.3], name="a")
    write_text([s], tmp_path / "a.txt")
    assert np.isnan(read_text(tmp_path / "a.txt")[0].values[1])


def test_viewspec_like_tab_export_with_header(tmp_path):
    p = tmp_path / "export.txt"
    p.write_text("Wavelength\tS1.asd\tS2.asd\n350\t0.41\t0.52\n351\t0.42\t0.53\n")
    a, b = read_text(p)
    assert (a.name, b.name) == ("S1.asd", "S2.asd")
    np.testing.assert_allclose(b.values, [0.52, 0.53])
    assert a.meta["source_column"] == "S1.asd"


def test_semicolon_decimal_comma(tmp_path):
    p = tmp_path / "fr.csv"
    p.write_text("lambda;ech1\n350;0,41\n351;0,42\n")
    (s,) = read_text(p)
    np.testing.assert_allclose(s.values, [0.41, 0.42])
    assert s.history[-1].params["decimal"] == ","


def test_whitespace_decimal_comma(tmp_path):
    p = tmp_path / "ws.dat"
    p.write_text("350 0,41\n351 0,42\n")
    np.testing.assert_allclose(read_text(p)[0].values, [0.41, 0.42])


def test_plain_csv(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("wl,a,b\n350,0.1,0.2\n351,0.3,0.4\n")
    assert [s.name for s in read_text(p)] == ["a", "b"]


def test_percent_is_converted_and_recorded(tmp_path):
    p = tmp_path / "pct.txt"
    p.write_text("350\t41.0\n351\t42.0\n")
    (s,) = read_text(p)
    np.testing.assert_allclose(s.values, [0.41, 0.42])
    assert s.history[-1].name == "scale_values" and s.history[-1].params["factor"] == 0.01


def test_explicit_scale_overrides_auto(tmp_path):
    p = tmp_path / "pct.txt"
    p.write_text("350\t41.0\n351\t42.0\n")
    np.testing.assert_allclose(read_text(p, reflectance_scale=1.0)[0].values, [41.0, 42.0])


def test_values_not_reflectance_rejected(tmp_path):
    p = tmp_path / "dn.txt"
    p.write_text("350\t4100\n351\t4200\n")
    with pytest.raises(TextFormatError, match="neither reflectance"):
        read_text(p)


def test_micrometres_converted(tmp_path):
    p = tmp_path / "um.txt"
    p.write_text("0.350\t0.1\n0.351\t0.2\n")
    (s,) = read_text(p)
    np.testing.assert_allclose(s.wavelength, [350.0, 351.0])
    assert "convert_wavelength" in step_names(s)


def test_decreasing_order_reversed(tmp_path):
    p = tmp_path / "rev.txt"
    p.write_text("352\t0.3\n351\t0.2\n350\t0.1\n")
    (s,) = read_text(p)
    np.testing.assert_allclose(s.wavelength, [350, 351, 352])
    np.testing.assert_allclose(s.values, [0.1, 0.2, 0.3])
    assert "reverse_order" in step_names(s)


def test_headerless_names(tmp_path):
    single = tmp_path / "one.txt"
    single.write_text("350\t0.1\n351\t0.2\n")
    assert read_text(single)[0].name == "one"
    multi = tmp_path / "many.txt"
    multi.write_text("350\t0.1\t0.2\n351\t0.2\t0.3\n")
    assert [s.name for s in read_text(multi)] == ["many_1", "many_2"]


def test_missing_value_tokens(tmp_path):
    p = tmp_path / "gaps.csv"
    p.write_text("wl,a\n350,0.1\n351,NaN\n352,\n353,0.2\n")
    assert np.isnan(read_text(p)[0].values[1:3]).all()


def test_ragged_row_reports_line_number(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("wl\ta\tb\n350\t0.1\t0.2\n351\t0.2\n")
    with pytest.raises(TextFormatError, match="line 3"):
        read_text(p)


def test_garbage_token_reports_line_number(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("350\t0.1\n351\tabc\n")
    with pytest.raises(TextFormatError, match="line 2"):
        read_text(p)


def test_no_data(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("just a header\n")
    with pytest.raises(TextFormatError, match="no numeric data"):
        read_text(p)


def test_cp1252_file(tmp_path):
    p = tmp_path / "win.txt"
    p.write_bytes("Longueur d'onde\téchantillon\n350\t0.1\n351\t0.2\n".encode("cp1252"))
    assert read_text(p)[0].name == "échantillon"


def test_writer_rejects_unwritable_names(tmp_path):
    s = Spectrum(wavelength=[1.0, 2.0], values=[0.1, 0.2], name="a,b")
    with pytest.raises(ValueError, match="cannot be written"):
        write_text([s], tmp_path / "x.csv")


def test_registry_dispatch(tmp_path):
    p = tmp_path / "x.tsv"
    p.write_text("350\t0.1\n351\t0.2\n")
    assert swirl.read(p)[0].n_bands == 2
    q = tmp_path / "x.unknown"
    q.write_text("350\t0.1\n351\t0.2\n")
    with pytest.raises(ValueError, match="no format registered"):
        swirl.read(q)
    assert swirl.read(q, format="text")[0].n_bands == 2


def test_trailing_delimiter_on_every_row(tmp_path):
    p = tmp_path / "trail.csv"
    p.write_text("wl,a,\n350,0.1,\n351,0.2,\n")
    (s,) = read_text(p)
    assert s.name == "a"
    np.testing.assert_allclose(s.values, [0.1, 0.2])
