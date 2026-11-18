"""Test setup. Tests run against a separate MySQL database (nutrimate_ai_test by default,
or NUTRIMATE_TEST_DATABASE), never the app database. Tables there are emptied at the
start of a run.

Tests that need the trained model artifacts are skipped when models/ is missing (as in
CI). The live Gemini test runs only when GEMINI_API_KEY is set; every other test turns
Gemini off so results do not depend on the network.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

TEST_DB = os.environ.get("NUTRIMATE_TEST_DATABASE", "nutrimate_ai_test")
assert TEST_DB.endswith("_test"), "tests must use a database whose name ends in _test"
os.environ["MYSQL_DATABASE"] = TEST_DB

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import db  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from nutrimate_core.paths import MODELS, PROCESSED  # noqa: E402

FORCE_LIGHT = os.environ.get("NUTRIMATE_TEST_LIGHT") == "1"  # behave as in CI, without models or data
HAS_MODELS = not FORCE_LIGHT and all((MODELS / f).exists() for f in ("content.joblib", "lightfm.npz", "popularity.parquet",
                                                 "faiss.index", "faiss_docs.parquet", "faiss_info.json"))
HAS_PROCESSED = not FORCE_LIGHT and (PROCESSED / "recipes.parquet").exists() and (PROCESSED / "foods.parquet").exists()
needs_models = pytest.mark.skipif(not (HAS_MODELS and HAS_PROCESSED),
                                  reason="trained models or processed data not present")
USER_TABLES = ["chat_messages", "meal_logs", "meal_plan_items", "meal_plans", "recommendation_items",
               "recommendation_logs", "interactions", "profile_history", "profiles", "jobs", "datasets", "users"]

FIXTURE_RECIPES = [
    # used only when the processed catalogue is not available (CI)
    (900001, "Peanut Noodle Bowl", "noodles|peanut butter|soy sauce|garlic", 520, 18, 60, 22, 4, "main", 1, 1, 0, "peanut|soy"),
    (900002, "Chickpea Spinach Curry", "chickpeas|spinach|onion|tomato|garam masala", 410, 16, 52, 14, 11, "main", 1, 1, 1, ""),
    (900003, "Masala Omelette", "eggs|onion|green chilli|salt", 280, 19, 4, 20, 1, "breakfast", 1, 0, 0, "egg"),
    (900004, "Chicken Tikka", "chicken|yogurt|garam masala|lemon", 350, 42, 6, 16, 1, "main", 0, 0, 0, "dairy"),
]


def _reset_tables():
    with db.tx() as t:
        t.run("SET FOREIGN_KEY_CHECKS = 0")
        for table in USER_TABLES:
            t.run(f"DELETE FROM {table}")
        t.run("DELETE FROM foods WHERE dataset_id IS NOT NULL")
        t.run("SET FOREIGN_KEY_CHECKS = 1")


def _ensure_catalogue():
    n = db.one("SELECT COUNT(*) AS n FROM recipes")["n"]
    if HAS_PROCESSED:
        import pandas as pd
        df = pd.read_parquet(PROCESSED / "recipes.parquet",
                             columns=["recipe_id", "is_vegetarian", "is_vegan", "allergens_found"])
        expected = (len(df), int(df.is_vegetarian.sum()), int(df.is_vegan.sum()),
                    int(df.allergens_found.fillna("").str.len().sum()))
        row = db.one("""SELECT COUNT(*) AS n, COALESCE(SUM(is_vegetarian), 0) AS veg, COALESCE(SUM(is_vegan), 0) AS vegan,
                        COALESCE(SUM(CHAR_LENGTH(allergens_found)), 0) AS al FROM recipes""")
        current = (int(row["n"]), int(row["veg"]), int(row["vegan"]), int(row["al"]))
        if current != expected:  # reload when the catalogue or its diet and allergen flags changed
            from backend.scripts import load_catalogue
            load_catalogue.main()
        return
    if n == 0:
        with db.tx() as t:
            for r in FIXTURE_RECIPES:
                t.run("""INSERT INTO recipes (recipe_id, name, ingredients, calories_kcal, protein_g, carbs_g, fat_g,
                         fiber_g, meal_type, is_eggetarian, is_vegetarian, is_vegan, allergens_found, nutrition_status,
                         cuisine, in_cf_data, source)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'listed','Indian',0,'test')""",
                      r)
            t.many("""INSERT INTO foods (food_id, name, source, food_group, kcal_100g, protein_100g, carbs_100g, fat_100g,
                      fiber_100g) VALUES (%s,%s,'test',%s,%s,%s,%s,%s,%s)""",
                   [("TEST:1", "Chickpeas, boiled", "Legumes", 164, 8.9, 27.4, 2.6, 7.6),
                    ("TEST:2", "Rice, white, cooked", "Cereals", 130, 2.7, 28.2, 0.3, None)])


@pytest.fixture(scope="session")
def client():
    settings = get_settings()
    settings.load_models = HAS_MODELS and HAS_PROCESSED
    db.init_schema()
    _reset_tables()
    _ensure_catalogue()
    from backend.app.main import app
    with TestClient(app) as c:
        if settings.load_models:
            from backend.app.rag.retriever import retriever
            deadline = time.time() + 120
            while not retriever.ready and time.time() < deadline:
                time.sleep(0.5)
        yield c


@pytest.fixture(autouse=True)
def gemini_off(request, monkeypatch):
    """Template answers by default; the live test opts out with @pytest.mark.live_gemini."""
    if request.node.get_closest_marker("live_gemini") is None:
        monkeypatch.setattr(get_settings(), "gemini_api_key", "")


def pytest_configure(config):
    config.addinivalue_line("markers", "live_gemini: calls the real Gemini API (needs GEMINI_API_KEY)")


def make_user(client, *, admin: bool = False, onboard: dict | None = None) -> dict:
    email = f"u{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123", "full_name": "Test User"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    uid = r.json()["user"]["id"]
    if admin:
        db.run("UPDATE users SET role = 'admin' WHERE id = %s", (uid,))
        token = client.post("/api/auth/login", json={"email": email, "password": "password123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    if onboard is not None:
        body = {"sex": "female", "age": 30, "height_cm": 165, "weight_kg": 60, "activity": "moderate",
                "goal": "maintain", **onboard}
        r = client.post("/api/profile/onboarding", json=body, headers=headers)
        assert r.status_code == 200, r.text
    return {"id": uid, "email": email, "headers": headers}
