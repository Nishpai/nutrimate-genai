"""The assistant: retrieval finds candidates, MySQL supplies every number, Python does the
maths, and a reply with a number that is not in the facts is rejected."""

import os

import pytest

from backend.app import db
from backend.app.rag import llm

from .conftest import make_user, needs_models


def test_validation_rejects_invented_numbers():
    facts = {"items": [{"matched": "Rice", "calories_kcal": 130.0, "protein_g": 2.7}]}
    assert llm.validate_numbers("Rice has 130 kcal and 2.7 g protein.", facts, "")["ok"]
    bad = llm.validate_numbers("Rice has 150 kcal and 2.7 g protein.", facts, "")
    assert not bad["ok"] and bad["unsupported"] == ["150 kcal"]
    # numbers without a nutrition unit (counts, list numbers) are not checked
    assert llm.validate_numbers("Here are 3 ideas.", facts, "")["ok"]
    # numbers the user wrote in the question are allowed
    assert llm.validate_numbers("For 200 g you get 260 kcal.", {"v": 260.0}, "200 g of rice")["ok"]


def _food_values(food_id):
    return db.one("SELECT name, kcal_100g, protein_100g, carbs_100g, fat_100g FROM foods WHERE food_id = %s", (food_id,))


@needs_models
def test_lookup_values_come_from_mysql(client):
    u = make_user(client, onboard={"calorie_target": 2000, "protein_target_g": 80})
    r = client.post("/api/assistant/ask", json={"message": "How many calories are in 200 g of boiled chickpeas?"},
                    headers=u["headers"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["intent"] == "lookup" and out["mode"] == "fallback"
    assert [s["node"] for s in out["steps"]] == ["parse_intent", "retrieve", "fetch", "compute", "respond"]
    card = out["cards"][0]
    assert card["type"] == "food" and card["portion"] == "200 g"
    row = _food_values(card["id"])
    assert "chickpea" in row["name"].lower()
    assert card["calories_kcal"] == round(row["kcal_100g"] * 2, 1)
    assert card["protein_g"] == round(row["protein_100g"] * 2, 1)
    assert f"{card['calories_kcal']:g}" in out["answer"]
    # percent of the daily target is computed in Python from the profile target
    item = out["facts"]["items"][0]
    assert item["percent_of_daily_calories"] == round(100 * card["calories_kcal"] / 2000, 1)


@needs_models
def test_recommend_intent_obeys_rules_and_uses_mysql_values(client):
    from backend.app.services.engine import engine
    from nutrimate_core import constraints as cons

    u = make_user(client, onboard={"diet": "vegan", "allergies": ["soy"], "calorie_target": 2000})
    out = client.post("/api/assistant/ask", json={"message": "Suggest a high protein dinner under 600 kcal"},
                      headers=u["headers"]).json()
    assert out["intent"] == "recommend" and out["cards"]
    c = cons.Constraints(diet="vegan", exclude=["soy"], max_calories=600)
    for card in out["cards"]:
        assert engine.check(int(card["id"]), c) == []
        row = db.one("SELECT calories_kcal, protein_g FROM recipes WHERE recipe_id = %s", (int(card["id"]),))
        assert card["calories_kcal"] == round(row["calories_kcal"], 1)
        assert card["protein_g"] == round(row["protein_g"], 1)


@needs_models
def test_targets_intent_uses_the_log(client):
    u = make_user(client, onboard={"calorie_target": 2000, "protein_target_g": 80})
    food = db.one("SELECT food_id, kcal_100g, protein_100g FROM foods WHERE kcal_100g > 100 AND protein_100g > 5 LIMIT 1")
    client.post("/api/logs", json={"slot": "lunch", "item_type": "food", "item_id": food["food_id"], "quantity": 100,
                                   "unit": "g"}, headers=u["headers"])
    out = client.post("/api/assistant/ask", json={"message": "How much protein do I have left today?"},
                      headers=u["headers"]).json()
    assert out["intent"] == "targets"
    f = out["facts"]
    assert f["eaten_today"]["calories_kcal"] == round(food["kcal_100g"], 1)
    assert f["remaining"]["calories_kcal"] == round(2000 - food["kcal_100g"], 1)


@needs_models
@pytest.mark.live_gemini
@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_live_gemini_reply_is_checked(client):
    """Real Gemini call. Gemini only writes the text: the cards still hold MySQL values and
    the reply either passes the number check or is replaced by the template."""
    u = make_user(client, onboard={"calorie_target": 2000})
    out = client.post("/api/assistant/ask", json={"message": "How many calories are in 150 g of cooked rice?"},
                      headers=u["headers"]).json()
    # Gemini must have answered: either the reply passed the check, or it was rejected by
    # the check. A connection or API error fails this test.
    assert out["model"], out["validation"]
    if out["mode"] == "fallback":
        assert "not in the database facts" in out["validation"]["reason"]
    else:
        assert out["validation"]["ok"] and out["model"]
        assert llm.validate_numbers(out["answer"], out["facts"], "150 g of cooked rice")["ok"]
    card = out["cards"][0]
    row = _food_values(card["id"]) if card["type"] == "food" else None
    if row:
        assert card["calories_kcal"] == round(row["kcal_100g"] * 1.5, 1)
