"""The constraint engine on its own, and its use by the recommender: a hard rule must win
over any score, including recipes the user has liked."""

import pandas as pd

from nutrimate_core import constraints as cons

from .conftest import make_user, needs_models


def _row(name, ingredients, kcal=400, protein=10, minutes=30):
    return {"name": name, "ingredients": ingredients, "search_text": cons.recipe_text(name, ingredients, ""),
            "calories_kcal": kcal, "protein_g": protein, "total_minutes": minutes, "meal_type": "main",
            "cuisine": "Indian"}


def test_diet_and_allergy_rules():
    vegan = cons.Constraints(diet="vegan")
    assert cons.check_recipe(_row("Masala Omelette", "eggs|onion"), vegan)
    assert cons.check_recipe(_row("Paneer Tikka", "paneer|yogurt"), vegan)
    assert not cons.check_recipe(_row("Chana Masala", "chickpeas|onion|tomato"), vegan)
    veg = cons.Constraints(diet="vegetarian")
    assert cons.check_recipe(_row("Butter Chicken", "chicken|butter"), veg)
    peanut = cons.Constraints(exclude=["peanut"])
    assert cons.check_recipe(_row("Satay", "chicken|peanut butter|soy sauce"), peanut)
    assert not cons.check_recipe(_row("Dal", "lentils|turmeric"), peanut)


def test_numeric_limits_and_unknown_values():
    c = cons.Constraints(max_calories=500, min_protein_g=15, max_minutes=20)
    assert cons.check_recipe(_row("Big bowl", "rice", kcal=800, protein=30, minutes=10), c)
    assert cons.check_recipe(_row("Small bowl", "rice", kcal=300, protein=5, minutes=10), c)
    assert cons.check_recipe(_row("Slow bowl", "rice", kcal=300, protein=20, minutes=90), c)
    assert not cons.check_recipe(_row("Good bowl", "rice", kcal=300, protein=20, minutes=10), c)
    # unknown calories can not be confirmed under a limit, so the recipe is removed
    assert cons.check_recipe(_row("Unknown", "rice", kcal=None, protein=20, minutes=10), c)
    # unknown ingredients can not be confirmed safe for an allergy
    assert cons.check_recipe(_row("Mystery", None), cons.Constraints(exclude=["peanut"]))


def test_filter_reports_reasons():
    flags = [(0, 0, 0), (1, 1, 1), (1, 0, 0)]  # is_eggetarian, is_vegetarian, is_vegan as the pipeline sets them
    rows = [_row("Satay", "chicken|peanut"), _row("Dal", "lentils"), _row("Egg curry", "eggs|onion")]
    for r, (e, v, vg) in zip(rows, flags):
        r.update(is_eggetarian=bool(e), is_vegetarian=bool(v), is_vegan=bool(vg), allergens_found="")
    df = pd.DataFrame(rows)
    kept, removed = cons.filter_recipes(df, cons.Constraints(diet="vegetarian", exclude=["peanut"]))
    assert list(kept["name"]) == ["Dal"]
    assert sum(removed.values()) == 2


@needs_models
def test_hard_constraints_override_scores(client):
    """Like several peanut recipes, which pushes peanut dishes up the hybrid score, then
    add a peanut allergy. No peanut recipe may appear, however high it would score."""
    from backend.app import db
    from backend.app.services.engine import engine

    u = make_user(client, onboard={"diet": "any"})
    liked = db.all_rows("""SELECT recipe_id FROM recipes WHERE in_cf_data = 1 AND allergens_found LIKE '%%peanut%%'
                      ORDER BY n_ratings DESC LIMIT 6""")
    for r in liked:
        client.post("/api/feedback", json={"recipe_id": r["recipe_id"], "action": "like"}, headers=u["headers"])
    before = client.post("/api/recommendations", json={"k": 30}, headers=u["headers"]).json()
    assert any("peanut" in it["recipe"]["allergens"] for it in before["items"]), "likes should surface peanut dishes"

    client.put("/api/profile", json={"diet": "vegetarian", "allergies": ["peanut"], "restrictions": ["mushroom"],
                                     "calorie_target": 2000}, headers=u["headers"])
    after = client.post("/api/recommendations", json={"k": 50, "max_calories": 600}, headers=u["headers"]).json()
    assert after["items"]
    c = cons.Constraints(diet="vegetarian", exclude=["peanut", "mushroom"], max_calories=600)
    for it in after["items"]:
        assert engine.check(it["recipe"]["recipe_id"], c) == [], it["recipe"]["name"]
        assert it["recipe"]["is_vegetarian"]
        assert it["recipe"]["calories_kcal"] is not None and it["recipe"]["calories_kcal"] <= 600
    assert after["removed"], "the response should say how many recipes the rules removed"
