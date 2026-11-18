import json
import time

import polars as pl
import pytest

from backend.app import db
from ml.ingest import ingest_file

from .conftest import make_user

CSV = (
    "Food Name,Food Group,Energy (kcal),Protein (g),Carbohydrate (g),Total Fat (g),Fibre (g)\n"
    "Sprouted moong salad,Salads,110,7.5,16,1.2,4.1\n"
    "Roasted makhana,Snacks,350,9.7,77,0.1,NA\n"
    "Curd rice,Rice dishes,140,3.9,22,3.8,\n"
    "Broken row,only two\n"
    "Bad energy,Snacks,-20,1,1,1,1\n"
)


def _wait(client, headers, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/admin/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_admin_routes_need_admin(client):
    u = make_user(client)
    assert client.get("/api/admin/overview", headers=u["headers"]).status_code == 403
    assert client.get("/api/admin/datasets").status_code == 401


def test_upload_clean_import_and_delete(client):
    a = make_user(client, admin=True)
    up = client.post("/api/admin/datasets/upload", headers=a["headers"], data={"name": "test foods"},
                     files={"file": ("foods.csv", CSV.encode(), "text/csv")})
    assert up.status_code == 201, up.text
    ds = up.json()
    job = client.post(f"/api/admin/datasets/{ds['id']}/process", headers=a["headers"]).json()
    done = _wait(client, a["headers"], job["job_id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["progress"] == 1 and done["result"]["rows"] == 4
    row = db.one("SELECT status, row_count, profile FROM datasets WHERE id = %s", (ds["id"],))
    prof = json.loads(row["profile"])
    assert row["status"] == "cleaned" and prof["skipped_rows"] == 1
    cols = {c["name"]: c for c in prof["columns"]}
    assert cols["fibre_g"]["nulls"] == 1 + 1 and cols["energy_kcal"]["nulls"] == 1  # NA, blank and -20 become NULL
    assert prof["suggested_food_mapping"]["name"] == "food_name"

    job = client.post(f"/api/admin/datasets/{ds['id']}/import-foods", headers=a["headers"], json={}).json()
    done = _wait(client, a["headers"], job["job_id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["result"]["imported"] == 4
    found = client.get("/api/foods?q=makhana&source=imported", headers=a["headers"]).json()
    assert found["total"] == 1 and found["items"][0]["kcal_100g"] == 350 and found["items"][0]["fiber_100g"] is None
    jobs = client.get("/api/admin/jobs", headers=a["headers"]).json()
    assert {j["job_type"] for j in jobs} >= {"profile_clean", "import_foods"}
    gone = client.delete(f"/api/admin/datasets/{ds['id']}", headers=a["headers"]).json()
    assert gone["foods_removed"] == 4


def test_upload_rejects_unknown_types(client):
    a = make_user(client, admin=True)
    r = client.post("/api/admin/datasets/upload", headers=a["headers"], files={"file": ("x.exe", b"MZ", "application/x")})
    assert r.status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "tsv", "jsonl", "json_array", "parquet"])
def test_ingest_formats_keep_nulls(tmp_path, fmt):
    rows = [{"Name": "A", "Protein (g)": 5.0, "Energy kcal": 100.0},
            {"Name": "B", "Protein (g)": None, "Energy kcal": -3.0},
            {"Name": "C", "Protein (g)": 2.5, "Energy kcal": None}]
    df = pl.DataFrame(rows)
    src = tmp_path / {"csv": "f.csv", "tsv": "f.tsv", "jsonl": "f.jsonl", "json_array": "f.json",
                      "parquet": "f.parquet"}[fmt]
    if fmt == "csv":
        df.write_csv(src)
    elif fmt == "tsv":
        df.write_csv(src, separator="\t")
    elif fmt == "jsonl":
        df.write_ndjson(src)
    elif fmt == "json_array":
        df.write_json(src)
    else:
        df.write_parquet(src)
    prof = ingest_file(src, tmp_path / "out.parquet", batch_rows=2)
    out = pl.read_parquet(tmp_path / "out.parquet")
    assert prof["rows"] == 3 and out.columns == ["name", "protein_g", "energy_kcal"]
    assert out["protein_g"].to_list() == [5.0, None, 2.5]
    assert out["energy_kcal"].to_list() == [100.0, None, None]  # negative energy is not a real value
