from backend.app import db

from .conftest import make_user, needs_models


def test_food_log_is_computed_from_mysql(client):
    u = make_user(client, onboard={"calorie_target": 2000})
    food = db.one("SELECT food_id, kcal_100g, protein_100g FROM foods WHERE kcal_100g IS NOT NULL LIMIT 1")
    r = client.post("/api/logs", json={"slot": "breakfast", "item_type": "food", "item_id": food["food_id"],
                                       "quantity": 250, "unit": "g"}, headers=u["headers"])
    assert r.status_code == 201
    entry = r.json()
    assert entry["calories_kcal"] == round(food["kcal_100g"] * 2.5, 1)
    recipe = db.one("SELECT recipe_id FROM recipes LIMIT 1")
    bad = client.post("/api/logs", json={"slot": "lunch", "item_type": "recipe", "item_id": str(recipe["recipe_id"]),
                                         "quantity": 100, "unit": "g"}, headers=u["headers"])
    assert bad.status_code == 422
    day = client.get("/api/logs", headers=u["headers"]).json()
    assert day["totals"]["calories_kcal"] == entry["calories_kcal"]
    dash = client.get("/api/dashboard?days=7", headers=u["headers"]).json()
    assert dash["today"]["calories_kcal"] == entry["calories_kcal"]
    assert dash["today_percent"]["calories_kcal"] == round(100 * entry["calories_kcal"] / 2000, 1)
    other = make_user(client)
    assert client.delete(f"/api/logs/{entry['id']}", headers=other["headers"]).status_code == 404
    assert client.delete(f"/api/logs/{entry['id']}", headers=u["headers"]).status_code == 200


def test_unknown_values_stay_unknown(client):
    u = make_user(client, onboard={})
    food = db.one("SELECT food_id FROM foods WHERE kcal_100g IS NOT NULL AND fiber_100g IS NULL LIMIT 1")
    if food is None:
        return
    entry = client.post("/api/logs", json={"slot": "snack", "item_type": "food", "item_id": food["food_id"],
                                           "quantity": 100, "unit": "g"}, headers=u["headers"]).json()
    assert entry["fiber_g"] is None
    day = client.get("/api/logs", headers=u["headers"]).json()
    assert day["items_with_unknown_values"]


@needs_models
def test_history_records_everything(client):
    u = make_user(client, onboard={"calorie_target": 2000})
    recs = client.post("/api/recommendations", json={"k": 5}, headers=u["headers"]).json()["items"]
    rid = recs[0]["recipe"]["recipe_id"]
    client.post("/api/feedback", json={"recipe_id": rid, "action": "like"}, headers=u["headers"])
    client.get(f"/api/recipes/{rid}", headers=u["headers"])
    client.post("/api/assistant/ask", json={"message": "calories in 100 g of rice"}, headers=u["headers"])
    client.put("/api/profile", json={"calorie_target": 2100}, headers=u["headers"])

    actions = [x["action"] for x in client.get("/api/history/interactions", headers=u["headers"]).json()]
    assert "like" in actions and "view" in actions
    logs = client.get("/api/history/recommendations", headers=u["headers"]).json()
    assert logs and logs[0]["items"][0]["recipe_id"] == rid and logs[0]["source"] == "recommendations"
    chats = client.get("/api/history/chats", headers=u["headers"]).json()
    assert [c["role"] for c in chats] == ["user", "assistant"] and chats[1]["meta"]["intent"]
    prof = client.get("/api/history/preferences", headers=u["headers"]).json()
    assert prof[0]["snapshot"]["calorie_target"] == 2100 and len(prof) == 2
    assert client.delete("/api/assistant/history", headers=u["headers"]).status_code == 200
    assert client.get("/api/history/chats", headers=u["headers"]).json() == []


def test_history_is_private(client):
    a = make_user(client, onboard={})
    b = make_user(client, onboard={})
    client.put("/api/profile", json={"diet": "vegan"}, headers=a["headers"])
    assert all(p["snapshot"]["diet"] != "vegan" for p in client.get("/api/history/preferences", headers=b["headers"]).json())
