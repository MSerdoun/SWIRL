import numpy as np
import pytest
from asd_factory import make_asd
from fastapi.testclient import TestClient

from swirl.app import create_app
from swirl.app.workspace import Workspace


@pytest.fixture
def client():
    return TestClient(create_app(Workspace(), static_dir=None))


def load_examples(client):
    r = client.post("/api/spectra/examples")
    assert r.status_code == 200
    return {s["name"]: s["id"] for s in r.json()["added"]}


def test_health_and_root(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "npm run build" in client.get("/").text


def test_examples_and_detail(client):
    ids = load_examples(client)
    assert len(ids) == 8
    d = client.get(f"/api/spectra/{ids['illite_noisy']}").json()
    assert d["n_bands"] == 2151 and len(d["values"]) == 2151
    assert d["meta"]["source_path"] == "illite_noisy.txt"
    assert [h["name"] for h in d["history"]][-1] == "read_text"


def test_upload_text_asd_and_bad_file(client, tmp_path):
    wl = np.arange(350.0, 2501.0)
    ref = np.full(wl.size, 20000.0)
    asd = make_asd(tmp_path / "core.asd", 0.4 * ref, ref).read_bytes()
    files = [
        ("files", ("a.csv", b"wl,a\n350,0.1\n351,0.2\n", "text/csv")),
        ("files", ("core.asd", asd, "application/octet-stream")),
        ("files", ("bad.txt", b"no data here\n", "text/plain")),
    ]
    body = client.post("/api/spectra/upload", files=files).json()
    assert [s["name"] for s in body["added"]] == ["a", "core"]
    assert body["errors"][0]["file"] == "bad.txt"
    assert len(client.get("/api/spectra").json()) == 2


def test_operations_expose_schemas(client):
    ops = {o["name"]: o for o in client.get("/api/operations").json()}
    assert "window" in ops["smooth"]["schema"]["properties"]


def test_process_groups_by_grid_and_records_history(client):
    ids = load_examples(client)
    client.post(
        "/api/spectra/upload", files=[("files", ("x.csv", b"wl,x\n350,0.1\n351,0.2\n", "text/csv"))]
    )
    x_id = client.get("/api/spectra").json()[-1]["id"]
    steps = [{"op": "splice_correction", "params": {}}, {"op": "smooth", "params": {"window": 7}}]
    body = client.post(
        "/api/process", json={"ids": [ids["illite_noisy"], ids["chlorite"], x_id], "steps": steps}
    ).json()
    done = {r["name"] for r in body["results"]}
    assert done == {"illite_noisy", "chlorite"}
    assert len(body["errors"]) == 1 and body["errors"][0]["ids"] == [x_id]
    assert body["results"][0]["history"][-1]["params"]["window"] == 7


def test_process_reports_invalid_steps(client):
    ids = load_examples(client)
    steps = [{"op": "smooth", "params": {"window": 10}}, {"op": "nope"}]
    r = client.post("/api/process", json={"ids": [ids["illite"]], "steps": steps})
    assert r.status_code == 422
    problems = r.json()["detail"]["steps"]
    assert [p["step"] for p in problems] == [0, 1]


def test_qc_and_export(client):
    ids = load_examples(client)
    body = client.post("/api/qc", json={"ids": [ids["illite_noisy"]], "params": {}}).json()
    assert "splice_step" in body["results"][0]["flags"]
    assert client.post("/api/qc", json={"ids": [], "params": {"nope": 1}}).status_code == 422
    r = client.post(
        "/api/export",
        json={"ids": [ids["illite"], ids["chlorite"]], "steps": [{"op": "continuum_removal"}]},
    )
    assert r.status_code == 200 and "wavelength_nm,illite,chlorite" in r.text
    assert "# quantity: continuum_removed" in r.text


def test_delete_and_unknown_ids(client):
    ids = load_examples(client)
    assert client.delete(f"/api/spectra/{ids['illite']}").status_code == 200
    assert client.get(f"/api/spectra/{ids['illite']}").status_code == 404
    assert client.post("/api/process", json={"ids": ["zz"], "steps": []}).status_code == 404
    client.delete("/api/spectra")
    assert client.get("/api/spectra").json() == []


def test_recipe_parse(client):
    toml = '[[steps]]\nop = "smooth"\nwindow = 7\n'
    body = client.post("/api/recipe/parse", json={"text": toml, "filename": "r.toml"}).json()
    assert body["steps"] == [
        {"op": "smooth", "params": {"method": "savgol", "window": 7, "polyorder": 2}}
    ]
    bad = client.post("/api/recipe/parse", json={"text": "[[steps]]\nop='smooth'\nw=1\n"})
    assert bad.status_code == 422 and "step 1" in bad.json()["detail"]
    assert (
        client.post("/api/recipe/parse", json={"text": "{", "filename": "x.json"}).status_code
        == 422
    )


def test_schema_defaults_are_exposed(client):
    ops = {o["name"]: o for o in client.get("/api/operations").json()}
    assert ops["splice_correction"]["schema"]["properties"]["boundaries"]["default"] == [1000, 1800]


def test_bands_endpoint_with_truth(client):
    ids = load_examples(client)
    steps = [{"op": "continuum_removal", "params": {"start": 1300, "stop": 2500}}]
    body = client.post(
        "/api/bands", json={"ids": [ids["illite"], ids["chlorite"]], "steps": steps, "params": {}}
    ).json()
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["illite"]["bands"]["AlOH"]["position"] == pytest.approx(2205, abs=0.1)
    assert rows["illite"]["truth"]["AlOH"]["center"] == 2205
    assert "APS1480" not in rows["illite"]["truth"]
    assert "log(MgOH/AlOH)" in rows["chlorite"]["ratios"]
    bad = client.post("/api/bands", json={"ids": [ids["illite"]], "params": {"fit_points": 4}})
    assert bad.status_code == 422
    csv = client.post("/api/bands/export", json={"ids": [ids["illite"]], "steps": steps})
    assert csv.status_code == 200 and "AlOH_position" in csv.text
    schema = client.get("/api/bands/schema").json()
    assert schema["properties"]["bands"]["default"][5]["name"] == "AlOH"


def test_synthetic_hole_and_log(client):
    added = client.post("/api/spectra/examples/hole").json()["added"]
    assert len(added) == 200 and added[0]["hole_id"] == "SYN-DH01"
    assert added[0]["depth_from"] == 0 and added[-1]["depth_to"] == 200
    holes = client.get("/api/holes").json()
    assert holes == [{"hole_id": "SYN-DH01", "n": 200, "top": 0.0, "bottom": 200.0}]
    steps = [{"op": "continuum_removal", "params": {"start": 1300, "stop": 2500}}]
    log = client.post(
        "/api/log", json={"hole_id": "SYN-DH01", "steps": steps, "image_max_bands": 100}
    ).json()
    assert len(log["ids"]) == 200 and log["quantity"] == "continuum_removed"
    assert len(log["image"]["values"]) == 200 and len(log["image"]["wavelength"]) <= 100
    assert set(log["truth"]["composition"]) == {"white_mica", "illite", "chlorite", "hematite"}
    assert len(log["bands"]["AlOH"]["position"]) == 200
    assert sum("low_albedo" in f for f in log["qc"]) == 3
    assert client.post("/api/log", json={"hole_id": "nope"}).status_code == 404


def test_project_save_and_open(client):
    ids = load_examples(client)
    client.post("/api/spectra/examples/hole")
    n = len(client.get("/api/spectra").json())
    settings = {
        "recipe": {
            "name": "r",
            "steps": [{"op": "smooth", "params": {"window": 9}, "enabled": True}],
        },
        "continuum": {"on": True, "start": "", "stop": ""},
        "band_params": {"min_depth": 0.01},
        "qc_params": {},
        "ui": {"main_view": "drillhole"},
    }
    body = {
        "name": "demo",
        "settings": settings,
        "visible_ids": [ids["illite"], ids["chlorite"]],
        "focused_id": ids["chlorite"],
    }
    r = client.post("/api/project/save", json=body)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="demo.swirl"' in r.headers["content-disposition"]
    blob = r.content

    client.delete("/api/spectra")
    opened = client.post(
        "/api/project/open", files=[("file", ("demo.swirl", blob, "application/zip"))]
    ).json()
    assert opened["name"] == "demo" and opened["warnings"] == []
    assert len(opened["spectra"]) == n
    names = {s["id"]: s["name"] for s in opened["spectra"]}
    assert [names[i] for i in opened["visible_ids"]] == ["illite", "chlorite"]
    assert names[opened["focused_id"]] == "chlorite"
    assert opened["settings"]["recipe"]["steps"][0]["params"]["window"] == 9
    assert opened["settings"]["ui"]["main_view"] == "drillhole"
    assert opened["spectra"][0]["source"] == "synthetic"
    assert client.get("/api/holes").json()[0]["n"] == 200


def test_project_open_rejects_garbage_and_warns(client):
    r = client.post("/api/project/open", files=[("file", ("x.swirl", b"nope", "application/zip"))])
    assert r.status_code == 422
    load_examples(client)
    settings = {
        "band_params": {"fit_points": 4},
        "recipe": {"steps": [{"op": "nope", "params": {}}]},
    }
    blob = client.post("/api/project/save", json={"settings": settings}).content
    opened = client.post(
        "/api/project/open", files=[("file", ("p.swirl", blob, "application/zip"))]
    ).json()
    assert len(opened["warnings"]) == 2 and opened["settings"]["band_params"] == {}
