from nutrimate_core import constraints as cons

from .conftest import make_user, needs_models

pytestmark = needs_models
PROFILE = {"diet": "vegetarian", "allergies": ["peanut"], "restrictions": ["mushroom"], "calorie_target": 2200,
           "protein_target_g": 90}


def _rules():
    return cons.Constraints(diet="vegetarian", exclude=["peanut", "mushroom"])


def test_daily_plan_hits_target_and_respects_rules(client):
    from backend.app.services.engine import engine

    u = make_user(client, onboard=PROFILE)
    plan = client.post("/api/planner/generate", json={"days": 1, "with_narrative": False}, headers=u["headers"]).json()
    day = plan["days"][0]
    assert abs(day["totals"]["calories_kcal"] - 2200) / 2200 <= 0.10
    ids = [m["recipe"]["recipe_id"] for m in day["meals"]]
    assert len(ids) == len(set(ids)), "no recipe twice on the same day"
    for m in day["meals"]:
        assert engine.check(m["recipe"]["recipe_id"], _rules()) == []
        assert 0.5 <= m["servings"] <= 2.0
        # nutrition is the MySQL per-serving value times the portion
        expected = round(m["recipe"]["calories_kcal"] * m["servings"], 1)
        assert abs(m["nutrition"]["calories_kcal"] - expected) < 0.2


def test_weekly_plan_tolerance_swap_and_save(client):
    from backend.app import db
    from backend.app.services.engine import engine

    u = make_user(client, onboard=PROFILE)
    plan = client.post("/api/planner/generate", json={"days": 7, "with_narrative": True}, headers=u["headers"]).json()
    assert len(plan["days"]) == 7
    assert plan["summary"]["days_within_10pct"] >= 6
    assert plan["narrative_mode"] == "template" and "2200" in plan["narrative"].replace(",", "")
    for d in plan["days"]:
        for m in d["meals"]:
            assert engine.check(m["recipe"]["recipe_id"], _rules()) == []

    old = next(m for m in plan["days"][2]["meals"] if m["slot"] == "dinner")["recipe"]["recipe_id"]
    swapped = client.post("/api/planner/swap", json={"plan": plan, "day_index": 2, "slot": "dinner"},
                          headers=u["headers"]).json()
    new = next(m for m in swapped["days"][2]["meals"] if m["slot"] == "dinner")["recipe"]["recipe_id"]
    assert new != old and engine.check(new, _rules()) == []

    # a tampered client plan: the server must recompute nutrition from MySQL
    swapped["days"][0]["meals"][0]["nutrition"]["calories_kcal"] = 1
    swapped["days"][0]["meals"][0]["recipe"]["calories_kcal"] = 1
    saved = client.post("/api/planner/save", json={"plan": swapped, "name": "Test week"}, headers=u["headers"])
    assert saved.status_code == 201
    pid = saved.json()["id"]
    loaded = client.get(f"/api/planner/plans/{pid}", headers=u["headers"]).json()
    first = loaded["days"][0]["meals"][0]
    row = db.one("SELECT calories_kcal FROM recipes WHERE recipe_id = %s", (first["recipe"]["recipe_id"],))
    assert abs(first["nutrition"]["calories_kcal"] - round(row["calories_kcal"] * first["servings"], 1)) < 0.2

    logged = client.post(f"/api/planner/plans/{pid}/log", json={"day_index": 0}, headers=u["headers"]).json()
    assert logged["logged"] == len(loaded["days"][0]["meals"])
    assert [p["id"] for p in client.get("/api/planner/plans", headers=u["headers"]).json()] == [pid]
    assert client.delete(f"/api/planner/plans/{pid}", headers=u["headers"]).status_code == 200


def test_plan_rejects_a_recipe_that_breaks_the_rules(client):
    from backend.app import db

    u = make_user(client, onboard=PROFILE)
    plan = client.post("/api/planner/generate", json={"days": 1, "with_narrative": False}, headers=u["headers"]).json()
    meat = db.one("SELECT recipe_id FROM recipes WHERE is_vegetarian = 0 AND name LIKE '%%chicken%%' LIMIT 1")
    plan["days"][0]["meals"][0]["recipe"]["recipe_id"] = meat["recipe_id"]
    r = client.post("/api/planner/save", json={"plan": plan}, headers=u["headers"])
    assert r.status_code == 422 and "breaks your rules" in r.json()["detail"]


def test_planner_needs_a_calorie_target(client):
    u = make_user(client)
    r = client.post("/api/planner/generate", json={"days": 1}, headers=u["headers"])
    assert r.status_code == 400
