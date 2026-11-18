"""Breakfast suitability: the rules on their own, then the planner and the
recommendations page across many diet and allergy profiles."""

import pytest

from nutrimate_core import constraints as cons
from nutrimate_core.meals import block_reason, breakfast_fit

from .conftest import make_user, needs_models


def fit(name, category="Breakfast", keywords="", ingredients="oats|milk", kcal=300, protein=10, meal_type="breakfast"):
    return breakfast_fit(name, category, keywords, ingredients, kcal, protein, meal_type)


@pytest.mark.parametrize("name", [
    "Tomato Poha", "Rava Upma", "Soft Idli", "Masala Dosa with Coconut Chutney", "Aloo Paratha",
    "Masala Omelette", "Scrambled Eggs", "Buttermilk Pancakes", "Banana Smoothie", "Cinnamon Toast",
    "Crunchy Granola", "Greek Yogurt Parfait", "Blueberry Muffins", "Steel Cut Oatmeal", "Oatmeal Cookie Pancakes",
    "Avocado on Toast With Bacon and Maple Syrup", "Crab Quiche",
])
def test_breakfast_dishes_pass(name):
    assert fit(name) == "yes", block_reason(name)


@pytest.mark.parametrize("name", [
    "Sesame Noodles", "Asian Pasta Salad", "Chickpea Curry", "Pepper Steak", "Tomato Soup", "Caesar Salad",
    "Spiced Sugar", "Cinnamon Syrup", "Chocolate Fudge", "Mimosa Cocktail", "Oatmeal Chocolate Chunk Cookies",
    "Cream Cheese Delight", "Dry Oatmeal Mix", "Yogurt Marinated Chicken", "Vegetable Biryani",
])
def test_lunch_dinner_and_dessert_dishes_fail(name):
    assert fit(name, keywords="Brunch") == "no"


def test_brunch_tag_alone_is_not_enough():
    assert fit("Sesame Noodles", category="Asian", keywords="Brunch|Easy", meal_type="breakfast") == "no"
    assert fit("Veggie Sandwich", category="Lunch/Snacks", keywords="Easy", meal_type="snack") == "maybe"
    assert fit("Veggie Sandwich", category="Lunch/Snacks", keywords="Brunch", meal_type="snack") == "yes"


def test_spirits_in_ingredients_block():
    assert fit("Orange Smoothie", ingredients="orange juice|vodka|ice") == "no"
    assert fit("Waffles", ingredients="flour|eggs|milk|rum extract") == "yes"


def test_bounds():
    assert fit("Poached Egg", kcal=40, protein=6) == "no"
    assert fit("Giant Pancake Stack", kcal=1500, protein=30) == "no"
    assert fit("Plain Toast", kcal=150, protein=1) == "no"
    assert fit("Poached Eggs", kcal=140, protein=12) == "yes"


def test_meal_type_breakfast_in_filter_uses_the_rules():
    import pandas as pd
    rows = [
        {"name": "Sesame Noodles", "category": "Asian", "keywords": "Brunch", "meal_type": "breakfast"},
        {"name": "Tomato Poha", "category": "Breakfast", "keywords": "Indian", "meal_type": "breakfast"},
    ]
    for r in rows:
        r.update(ingredients="x", search_text="x", calories_kcal=300.0, protein_g=8.0, total_minutes=20.0,
                 cuisine="Asian", is_eggetarian=True, is_vegetarian=True, is_vegan=True, allergens_found="")
    kept, removed = cons.filter_recipes(pd.DataFrame(rows), cons.Constraints(meal_type="breakfast"))
    assert list(kept["name"]) == ["Tomato Poha"] and removed == {"not a breakfast dish": 1}


PROFILES = [
    {"diet": "any", "allergies": []},
    {"diet": "any", "allergies": ["gluten", "egg"]},
    {"diet": "eggetarian", "allergies": []},
    {"diet": "eggetarian", "allergies": ["dairy"]},
    {"diet": "vegetarian", "allergies": []},
    {"diet": "vegetarian", "allergies": ["peanut"], "restrictions": ["mushroom"]},
    {"diet": "vegetarian", "allergies": ["gluten"]},
    {"diet": "vegan", "allergies": []},
    {"diet": "vegan", "allergies": ["peanut", "tree_nut", "soy"]},
    {"diet": "vegan", "allergies": ["gluten", "sesame"]},
]


@needs_models
@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p["diet"] + "-" + "-".join(p["allergies"]) or "none")
def test_week_plan_breakfasts_are_breakfasts(client, profile):
    from backend.app.services.engine import engine

    u = make_user(client, onboard={**profile, "calorie_target": 2000, "protein_target_g": 70})
    plan = client.post("/api/planner/generate", json={"days": 7, "with_narrative": False}, headers=u["headers"]).json()
    assert len(plan["days"]) == 7, plan
    rules = cons.Constraints(diet=profile["diet"], exclude=profile["allergies"] + profile.get("restrictions", []))
    fits = engine.catalogue.set_index("recipe_id").breakfast_fit
    n_fallback = 0
    for d in plan["days"]:
        bf = [m for m in d["meals"] if m["slot"] == "breakfast"]
        assert len(bf) == 1
        m = bf[0]
        assert engine.check(m["recipe"]["recipe_id"], rules) == []
        f = fits[m["recipe"]["recipe_id"]]
        if m.get("breakfast_fallback"):
            n_fallback += 1
            assert f == "maybe"
        else:
            assert f == "yes", m["recipe"]["name"]
    assert ("breakfast_note" in plan) == (n_fallback > 0)


@needs_models
def test_recommendations_breakfast_filter(client):
    from backend.app.services.engine import engine

    u = make_user(client, onboard={"diet": "vegetarian", "allergies": []})
    res = client.post("/api/recommendations", json={"meal_type": "breakfast", "k": 12}, headers=u["headers"]).json()
    assert len(res["items"]) == 12
    fits = engine.catalogue.set_index("recipe_id").breakfast_fit
    assert all(fits[it["recipe"]["recipe_id"]] == "yes" for it in res["items"])
    assert not any(it.get("breakfast_fallback") for it in res["items"])


@needs_models
def test_recommendations_breakfast_fallback_is_labelled(client):
    """A very strict profile: real breakfasts come first, any fallback is marked."""
    u = make_user(client, onboard={"diet": "vegan", "allergies": ["peanut", "tree_nut", "soy", "gluten"]})
    res = client.post("/api/recommendations", json={"meal_type": "breakfast", "k": 24}, headers=u["headers"]).json()
    flags = [bool(it.get("breakfast_fallback")) for it in res["items"]]
    assert flags == sorted(flags), "fallback items come after real breakfasts"
    assert any(flags) == ("breakfast_note" in res)


def test_drinks_need_to_be_a_meal_in_a_glass():
    assert fit("Banana Smoothie", category="Smoothies", meal_type="drink") == "yes"
    assert fit("Mango Lassi", category="Beverages", meal_type="drink") == "yes"
    assert fit("Apple Milk Drink (Sharbat)", category="Beverages", keywords="Breakfast", meal_type="drink") == "maybe"
    assert fit("Iced Banana Latte", category="Beverages", keywords="Breakfast", meal_type="drink") == "maybe"
