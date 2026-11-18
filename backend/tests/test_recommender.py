from backend.app import db

from .conftest import make_user, needs_models

pytestmark = needs_models


def test_recommendations_are_ranked_and_explained(client):
    u = make_user(client, onboard={"cuisines": ["Indian"]})
    r = client.post("/api/recommendations", json={"k": 12}, headers=u["headers"])
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) == 12
    scores = [it["score"] for it in items]
    assert scores == sorted(scores, reverse=True)
    assert len({it["recipe"]["recipe_id"] for it in items}) == 12
    assert all(it["reasons"] for it in items)
    assert set(items[0]["components"]) >= {"content", "cf", "popularity", "hybrid"}
    assert body["passed"] > 1000


def test_likes_change_the_ranking_and_dislikes_are_removed(client):
    u = make_user(client, onboard={})
    first = client.post("/api/recommendations", json={"k": 20}, headers=u["headers"]).json()["items"]
    curry = db.all_rows("""SELECT recipe_id FROM recipes WHERE in_cf_data = 1 AND name LIKE '%%curry%%'
                           ORDER BY n_ratings DESC LIMIT 5""")
    for r in curry:
        assert client.post("/api/feedback", json={"recipe_id": r["recipe_id"], "action": "like"},
                           headers=u["headers"]).status_code == 200
    disliked = first[0]["recipe"]["recipe_id"]
    client.post("/api/feedback", json={"recipe_id": disliked, "action": "dislike"}, headers=u["headers"])
    second = client.post("/api/recommendations", json={"k": 20}, headers=u["headers"]).json()
    ids = [it["recipe"]["recipe_id"] for it in second["items"]]
    liked_ids = {r["recipe_id"] for r in curry}
    assert disliked not in ids
    assert not liked_ids & set(ids), "already liked recipes are not recommended again"
    assert ids != [it["recipe"]["recipe_id"] for it in first]
    assert second["personalised"] and second["liked_count"] == 5


def test_feedback_validation_and_saved_flag(client):
    u = make_user(client, onboard={})
    assert client.post("/api/feedback", json={"recipe_id": 999999999, "action": "like"},
                       headers=u["headers"]).status_code == 404
    assert client.post("/api/feedback", json={"recipe_id": 1, "action": "eat"}, headers=u["headers"]).status_code == 422
    items = client.post("/api/recommendations", json={"k": 5}, headers=u["headers"]).json()["items"]
    rid = items[0]["recipe"]["recipe_id"]
    client.post("/api/feedback", json={"recipe_id": rid, "action": "save"}, headers=u["headers"])
    prefs = client.get("/api/preferences", headers=u["headers"]).json()
    assert rid in [x["recipe_id"] for x in prefs["saved"]]


def test_filters_are_applied(client):
    u = make_user(client, onboard={})
    r = client.post("/api/recommendations", json={"k": 15, "meal_type": "breakfast", "max_calories": 400,
                                                  "min_protein_g": 10}, headers=u["headers"]).json()
    assert r["items"]
    from backend.app.services.engine import engine
    fits = engine.catalogue.set_index("recipe_id").breakfast_fit
    for it in r["items"]:
        rec = it["recipe"]
        # breakfast means "rated a breakfast" (nutrimate_core.meals), or a labelled fallback
        assert fits[rec["recipe_id"]] == ("maybe" if it.get("breakfast_fallback") else "yes")
        assert rec["calories_kcal"] <= 400 and rec["protein_g"] >= 10
