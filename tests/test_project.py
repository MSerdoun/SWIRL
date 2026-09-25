import io
import json
import zipfile

import numpy as np
import pytest

import swirl
from swirl import ProcessingStep, Spectrum
from swirl.preprocess import apply
from swirl.project import Project, ProjectError, load_project, save_project
from swirl.synthetic.drillhole import synthetic_drillhole


def spectra_mixed_grids(synthetic_dir):
    a = swirl.read(synthetic_dir / "illite_noisy.txt")[0]
    b = swirl.read(synthetic_dir / "chlorite.txt")[0]
    c = apply("crop", b, start=2000, stop=2400)  # another grid
    dup = Spectrum(wavelength=a.wavelength, values=a.values * 0.9, name=a.name, meta={"x": 1})
    return [a, c, b, dup]


def test_roundtrip_is_exact(tmp_path, synthetic_dir):
    spectra = spectra_mixed_grids(synthetic_dir)
    settings = {
        "recipe": {
            "name": "r",
            "steps": [{"op": "smooth", "params": {"window": 7}, "enabled": False}],
        }
    }
    path = tmp_path / "p.swirl"
    save_project(path, spectra, settings, name="demo")
    p = load_project(path)
    assert p.name == "demo" and p.settings == settings
    assert [s.name for s in p.spectra] == [s.name for s in spectra]  # duplicates kept
    for a, b in zip(spectra, p.spectra, strict=True):
        np.testing.assert_array_equal(a.wavelength, b.wavelength)
        np.testing.assert_array_equal(a.values, b.values)  # bit-exact, not rounded
        assert a.quantity == b.quantity
        assert dict(a.meta) == dict(b.meta)
        assert [h.to_dict() for h in a.history] == [h.to_dict() for h in b.history]


def test_file_layout_is_readable(tmp_path, synthetic_dir):
    path = tmp_path / "p.swirl"
    save_project(path, spectra_mixed_grids(synthetic_dir), {"k": 1})
    with zipfile.ZipFile(path) as zf:
        assert set(zf.namelist()) == {"project.json", "spectra.json", "spectra.npz"}
        header = json.loads(zf.read("project.json"))
    assert header["format"] == "swirl-project" and header["version"] == 1
    assert header["n_spectra"] == 4


def test_file_objects_and_swirl_read(tmp_path):
    hole = synthetic_drillhole()[:5]
    buf = io.BytesIO()
    save_project(buf, hole)
    buf.seek(0)
    assert len(load_project(buf).spectra) == 5
    path = tmp_path / "h.swirl"
    path.write_bytes(buf.getvalue())
    back = swirl.read(path)
    assert back[0].meta["synthetic_composition"] == hole[0].meta["synthetic_composition"]


def test_recipe_from_settings():
    p = Project(
        spectra=[],
        settings={
            "recipe": {
                "steps": [
                    {"op": "splice_correction", "params": {}, "enabled": True},
                    {"op": "smooth", "params": {"window": 7}, "enabled": False},
                ]
            },
            "continuum": {"on": True, "start": "1300", "stop": ""},
        },
    )
    r = p.recipe()
    assert [s.op for s in r.steps] == ["splice_correction", "continuum_removal"]
    assert r.steps[1].params.start == 1300 and r.steps[1].params.stop is None
    p.settings["recipe"]["steps"].append({"op": "continuum_removal", "params": {}, "enabled": True})
    assert [s.op for s in p.recipe().steps].count("continuum_removal") == 1
    assert Project(spectra=[]).recipe() is None
    assert (
        Project(spectra=[], settings={"band_params": {"min_depth": 0.02}}).band_params().min_depth
        == 0.02
    )


def test_errors(tmp_path):
    bad = tmp_path / "x.swirl"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ProjectError, match="not a zip"):
        load_project(bad)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("project.json", "{}")
    with pytest.raises(ProjectError, match="missing"):
        load_project(bad)
    save_project(bad, [])
    with zipfile.ZipFile(bad) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    header = json.loads(members["project.json"])
    header["version"] = 99
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("project.json", json.dumps(header))
        zf.writestr("spectra.json", members["spectra.json"])
        zf.writestr("spectra.npz", members["spectra.npz"])
    with pytest.raises(ProjectError, match="newer"):
        load_project(bad)


def test_history_steps_survive(tmp_path, synthetic_dir):
    s = apply("smooth", swirl.read(synthetic_dir / "illite.txt")[0], window=9)
    save_project(tmp_path / "p.swirl", [s])
    (back,) = load_project(tmp_path / "p.swirl").spectra
    assert back.history[-1] == ProcessingStep(
        "smooth", {"method": "savgol", "window": 9, "polyorder": 2}, s.history[-1].swirl_version
    )
