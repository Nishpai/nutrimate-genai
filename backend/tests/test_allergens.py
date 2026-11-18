"""Allergen and diet matching: synonyms, plurals, Indian names, and the false friends
that must not match. Pure text tests, no database needed."""

import pytest

from nutrimate_core import constraints as cons


def text(ingredients: str, name: str = "Test dish", steps: str = "") -> str:
    return cons.recipe_text(name, ingredients, steps)


TRUE_POSITIVES = [
    # dairy, including Indian names
    ("dairy", "milk|sugar"), ("dairy", "ghee|rice"), ("dairy", "paneer|peas"), ("dairy", "butter"),
    ("dairy", "heavy cream"), ("dairy", "curd|cucumber"), ("dairy", "dahi"), ("dairy", "khoa|sugar"),
    ("dairy", "khoya"), ("dairy", "malai"), ("dairy", "cheddar cheese"), ("dairy", "whey protein"),
    ("dairy", "sodium caseinate"), ("dairy", "buttermilk"), ("dairy", "sweet lassi"),
    ("dairy", "condensed milk"), ("dairy", "parmesan"), ("dairy", "sour cream"),
    # gluten and wheat
    ("gluten", "whole wheat flour"), ("gluten", "maida"), ("gluten", "atta"), ("gluten", "sooji"),
    ("gluten", "semolina"), ("gluten", "rava|curd"), ("gluten", "pearl barley"), ("gluten", "rye bread"),
    ("gluten", "seitan"), ("gluten", "bread crumbs"), ("gluten", "pasta"), ("gluten", "couscous"),
    ("gluten", "bulgur"), ("gluten", "soy sauce"), ("gluten", "flour tortillas"),
    # peanut
    ("peanut", "peanuts"), ("peanut", "roasted groundnuts"), ("peanut", "moongphali"),
    ("peanut", "peanut butter"), ("peanut", "peanut oil"), ("peanut", "peanut-butter"),
    # tree nuts
    ("tree_nut", "almonds"), ("tree_nut", "badam"), ("tree_nut", "cashews"), ("tree_nut", "kaju"),
    ("tree_nut", "pistachios"), ("tree_nut", "pista"), ("tree_nut", "walnuts"), ("tree_nut", "akhrot"),
    ("tree_nut", "hazelnuts"), ("tree_nut", "pecans"), ("tree_nut", "macadamia nuts"),
    ("tree_nut", "almond milk"), ("tree_nut", "chopped nuts"),
    # egg
    ("egg", "eggs"), ("egg", "egg whites"), ("egg", "mayonnaise"), ("egg", "meringue"), ("egg", "albumin"),
    # soy
    ("soy", "soy sauce"), ("soy", "soya chunks"), ("soy", "firm tofu"), ("soy", "edamame"),
    ("soy", "tempeh"), ("soy", "white miso"),
    # fish and shellfish
    ("fish", "salmon fillets"), ("fish", "anchovies"), ("fish", "fish sauce"), ("fish", "pomfret"),
    ("shellfish", "prawns"), ("shellfish", "shrimp"), ("shellfish", "crab meat"), ("shellfish", "mussels"),
    # sesame
    ("sesame", "sesame seeds"), ("sesame", "til seeds"), ("sesame", "tahini"), ("sesame", "gingelly oil"),
    ("sesame", "safed til|jaggery"),
]

FALSE_POSITIVES = [
    ("dairy", "dairy-free milk|oats"), ("dairy", "non-dairy creamer"), ("dairy", "almond milk"),
    ("dairy", "coconut milk|curry leaves"), ("dairy", "soy milk"), ("dairy", "peanut butter"),
    ("dairy", "cocoa butter"), ("dairy", "butternut squash"), ("dairy", "butter beans"),
    ("dairy", "vegan butter|flour"), ("dairy", "cream of tartar"), ("dairy", "coconut cream"),
    ("egg", "eggplant"), ("egg", "egg-free mayonnaise"), ("egg", "eggless cake mix"),
    ("egg", "egg replacer"), ("egg", "flax egg"),
    ("tree_nut", "nutmeg"), ("tree_nut", "coconut"), ("tree_nut", "butternut squash"),
    ("tree_nut", "water chestnuts"), ("tree_nut", "doughnuts"), ("tree_nut", "nut-free granola"),
    ("tree_nut", "peanuts"),
    ("peanut", "almonds"), ("peanut", "butternut squash"),
    ("gluten", "rice flour"), ("gluten", "besan"), ("gluten", "chickpea flour"), ("gluten", "gluten-free pasta"),
    ("gluten", "rice noodles"), ("gluten", "corn tortillas"), ("gluten", "buckwheat"), ("gluten", "ginger beer"),
    ("fish", "shellfish stock"), ("fish", "crab apple"),
    ("shellfish", "oyster mushrooms"),
    ("sesame", "rice"),
]


@pytest.mark.parametrize("group,ingredients", TRUE_POSITIVES)
def test_allergen_true_positives(group, ingredients):
    assert cons.mentions_group(text(ingredients), group), f"{group} should match {ingredients!r}"
    assert group in cons.allergens_in(text(ingredients))


@pytest.mark.parametrize("group,ingredients", FALSE_POSITIVES)
def test_allergen_false_positives(group, ingredients):
    assert not cons.mentions_group(text(ingredients), group), (
        f"{group} must not match {ingredients!r}: {cons.group_hits(text(ingredients), group)}")


def test_til_in_instructions_is_not_sesame():
    t = text("onion|rice", steps="Cook til golden brown, then stir til smooth.")
    assert not cons.mentions_group(t, "sesame")


def test_name_and_steps_are_checked():
    assert cons.mentions_group(text("rice|water", name="Peanut Rice"), "peanut")
    assert cons.mentions_group(text("flour|water", steps="Brush with beaten egg."), "egg")


@pytest.mark.parametrize("ingredients", [
    "gelatin|sugar", "fish sauce|lime", "chicken stock|rice", "beef broth", "lard|flour", "anchovy paste",
    "oyster sauce|broccoli", "shrimp paste", "chuck roast", "bacon bits",
])
def test_non_vegetarian_ingredients(ingredients):
    assert cons.has_meat_or_fish(text(ingredients))


@pytest.mark.parametrize("ingredients", [
    "vegetable stock|rice", "coconut meat", "meatless crumbles", "vegetarian sausage", "veggie burger patties",
    "hot dog buns", "oyster mushrooms", "eggplant", "crab apples",
])
def test_vegetarian_false_friends(ingredients):
    assert not cons.has_meat_or_fish(text(ingredients))


@pytest.mark.parametrize("ingredients,vegan", [
    ("honey|oats", False), ("ghee|dal", False), ("paneer", False), ("eggs", False), ("milk powder", False),
    ("almond milk|oats", True), ("coconut milk|vegetables", True), ("honeydew melon|mint", True),
    ("peanut butter|banana", True), ("vegan butter|flour", True), ("eggplant|tomato", True),
])
def test_vegan_rules(ingredients, vegan):
    assert cons.has_animal_product(text(ingredients)) is (not vegan)


def test_eggetarian_allows_egg_vegetarian_does_not():
    row = {"name": "Masala Omelette", "ingredients": "eggs|onion", "search_text": text("eggs|onion", "Masala Omelette"),
           "calories_kcal": 300, "protein_g": 18, "total_minutes": 10, "meal_type": "breakfast", "cuisine": "Indian"}
    assert cons.check_recipe(row, cons.Constraints(diet="eggetarian")) == []
    assert "contains egg" in cons.check_recipe(row, cons.Constraints(diet="vegetarian"))


@pytest.mark.parametrize("typed,group", [
    ("peanuts", "peanut"), ("groundnut", "peanut"), ("tree nuts", "tree_nut"), ("lactose", "dairy"),
    ("milk", "dairy"), ("wheat", "gluten"), ("soya", "soy"), ("til", "sesame"), ("seafood", "shellfish"),
])
def test_typed_exclusions_map_to_groups(typed, group):
    assert cons.normalize_exclusion(typed) == group


def test_no_nuts_means_peanut_and_tree_nuts():
    assert cons.term_matches(text("peanuts"), "nuts")
    assert cons.term_matches(text("cashews"), "nuts")
    assert not cons.term_matches(text("nutmeg|coconut"), "nuts")


def test_free_text_exclusion_uses_word_boundaries():
    assert cons.term_matches(text("button mushrooms"), "mushroom")
    assert not cons.term_matches(text("ham"), "hamburger")
    assert not cons.term_matches(text("graham crackers"), "ham")
