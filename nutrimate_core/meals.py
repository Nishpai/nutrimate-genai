"""Is a recipe a sensible breakfast?

Food.com tags are a weak signal on their own: the "Brunch" keyword is attached to pasta
salads and sesame noodles, and the "Breakfast" category holds desserts and spice mixes.
So the decision combines three things:

1. Block words in the name: pasta and noodles, curries, soups and stews, steaks and
   burgers, salads, spice mixes and cocktails always block (also any spirit or wine in
   the ingredients). Sauces and sweets block unless the name also has a breakfast word,
   and a name that ends in a topping ("Spiced Sugar", "Cinnamon Syrup") blocks.
2. A positive signal: a breakfast word in the name (oats, poha, upma, idli, dosa,
   paratha, eggs, omelette, pancakes, smoothie, toast, granola, yogurt, muffin and so
   on), or the Food.com "Breakfast" category or keyword, or "Brunch" together with a
   breakfast word.
3. Bounds per serving: 60 to 900 kcal and at least 3 g protein.
Drinks count as a breakfast only when they are a meal in a glass (smoothie, lassi,
protein shake, oat drinks); juices, teas and milk drinks are fallback only.

breakfast_fit returns "yes" (all three hold), "maybe" (not blocked, within bounds, and
a light dish type such as baking, a drink or a snack, used only as a labelled
fallback when a strict diet leaves too few "yes" recipes) or "no".
"""

from __future__ import annotations

import re

ALLOW = [
    "oat", "oats", "oatmeal", "porridge", "muesli", "granola", "cereal", "bran", "poha", "upma",
    "idli", "idly", "dosa", "uttapam", "uthappam", "appam", "paratha", "parantha", "thepla",
    "chilla", "cheela", "pesarattu", "dhokla", "sheera", "daliya", "dalia", "egg", "omelet",
    "omelette", "frittata", "quiche", "scramble", "scrambled", "shakshuka", "benedict", "huevos",
    "chilaquiles", "migas", "pancake", "hotcake", "crepe", "waffle", "french toast", "toast",
    "bagel", "muffin", "scone", "biscuit", "croissant", "danish", "smoothie", "lassi", "yogurt", "yoghurt",
    "parfait", "hash", "hashbrown", "hash brown", "home fries", "breakfast", "brunch",
    "coffee cake", "banana bread", "english muffin", "dutch baby", "strata", "fruit salad",
    "bircher", "congee", "grits",
]
# Count as a breakfast word only when the recipe also carries a Breakfast or Brunch tag.
WEAK = ["sandwich", "wrap", "burrito", "potatoes", "casserole", "bread", "taco", "bacon", "sausage"]
# Never breakfast, whatever the name or tags say.
HARD_BLOCK = [
    "pasta", "noodle", "spaghetti", "macaroni", "lasagna", "lasagne", "linguine", "fettuccine",
    "fettuccini", "penne", "rigatoni", "ravioli", "tortellini", "ramen", "lo mein", "chow mein",
    "pad thai", "curry", "korma", "vindaloo", "biryani", "pulao", "pilaf", "risotto", "steak",
    "burger", "pizza", "soup", "stew", "chili", "chilli", "chowder", "bisque", "gumbo", "salad",
    "slaw", "coleslaw", "dressing", "vinaigrette", "marinade", "rub", "seasoning", "spice mix",
    "spice blend", "masala powder", "roast", "ribs", "wings", "meatloaf", "meatballs", "kebab",
    "tikka", "enchilada", "nachos", "dinner", "gyro", "sloppy joe", "dal", "dahl", "dhal",
    "cocktail", "martini", "margarita", "mojito", "sangria", "punch", "liqueur", "wine", "beer",
    "vodka", "rum", "whiskey", "whisky", "bourbon", "daiquiri", "mimosa", "bloody mary",
    "mix", "pickle", "relish", "easter egg", "dessert", "frozen", "deviled", "filling for", "crust", "hotdish",
]
# Sauces and sweets: blocked unless the name also has a breakfast word (so "Masala Dosa
# with Chutney" and "Oatmeal Cookie Pancakes" stay, "Cinnamon Crispas" goes).
SOFT_BLOCK = [
    "sauce", "dip", "salsa", "chutney", "guacamole", "hummus", "cake", "cupcake", "cookie", "brownie", "fudge", "candy",
    "cheesecake", "ice cream", "sorbet", "truffle", "toffee", "praline", "pie", "tart", "pudding",
    "mousse", "custard", "bark", "brittle", "halwa", "barfi", "burfi", "ladoo", "laddu", "kheer",
    "gulab", "jalebi", "delight", "crisps", "crispas", "shortbread", "bars",
]
# A name that ends in one of these is the topping itself, not a meal ("Spiced Sugar").
CONDIMENT_END = ["syrup", "glaze", "frosting", "icing", "jam", "jelly", "preserves", "marmalade",
                 "spread", "butter", "sugar", "topping", "compote", "sauce", "honey", "curd", "gravy", "crust", "filling"]
SPIRITS = ["vodka", "rum", "gin", "tequila", "whiskey", "whisky", "bourbon", "brandy", "liqueur",
           "schnapps", "champagne", "wine", "beer", "kahlua", "amaretto", "cognac", "sherry"]
NOT_SPIRIT = ["wine vinegar", "rice wine vinegar", "cooking wine", "root beer", "ginger beer", "rum extract",
              "brandy extract", "ginger ale"]
# Meat and fish mains: blocked unless the name says it is a breakfast dish (eggs, hash,
# omelette, quiche and so on), so "Crab Quiche" stays and "Marinated Chicken" goes.
MAINS = ["chicken", "beef", "pork", "lamb", "mutton", "fish", "salmon", "tuna", "shrimp", "prawn",
         "crab", "lobster", "turkey", "hamburger", "chop", "marinated", "sub", "nugget", "patty",
         "patties", "appetizer", "pinwheel", "thanksgiving", "rice", "lentil", "sausage", "bratwurst",
         "beefaroni", "ham", "skins", "cheese ball", "chips", "frosty", "quesadilla", "bisquick"]
BREAKFAST_DISH = ["breakfast", "brunch", "omelet", "omelette", "frittata", "quiche", "scramble",
                  "scrambled", "benedict", "hash", "egg", "waffle", "pancake", "crepe", "burrito",
                  "biscuit", "bagel", "strata", "shakshuka", "huevos", "home fries", "muffin", "toast"]
FALLBACK_TYPES = {"breakfast", "baking", "drink", "snack"}
MIN_KCAL, MAX_KCAL, MIN_PROTEIN = 60.0, 900.0, 3.0


def _rx(words):
    parts = sorted({re.escape(w).replace(r"\ ", r"[\s-]+") + r"(?:s|es)?" for w in words}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


_ALLOW, _WEAK, _HARD, _SOFT = _rx(ALLOW), _rx(WEAK), _rx(HARD_BLOCK), _rx(SOFT_BLOCK)
_MAINS, _DISH = _rx(MAINS), _rx(BREAKFAST_DISH)
_DRINK_MEAL = _rx(["smoothie", "lassi", "protein shake", "breakfast", "oat", "oatmeal", "muesli"])
_SPIRIT, _NOT_SPIRIT = _rx(SPIRITS), _rx(NOT_SPIRIT)
_EXCEPT = _rx(["coffee cake", "fruit salad", "breakfast bars", "granola bars", "oat bars",
               "breakfast cookie"])
_CONDIMENT_END = re.compile(r"\b(?:" + "|".join(CONDIMENT_END) + r")s?\s*$")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _bare_name(name: str) -> str:
    n = re.sub(r"\([^)]*\)", " ", (name or "").lower())
    return re.sub(r"[^a-z&' -]+", " ", n).strip()


def _head(n: str) -> str:
    """The part of a name before "with", "and", "on" or "served", which names the dish."""
    return re.split(r"\s(?:with|and|&|on|in|served|over|topped)\s", n, maxsplit=1)[0]


def block_reason(name: str, ingredients: str = "") -> str | None:
    """Why a recipe can never be breakfast, or None."""
    full = (name or "").lower()
    n = _bare_name(name)
    m = _HARD.search(_EXCEPT.sub(" ", full))
    if m:
        return f"'{m.group(0)}' is not a breakfast dish"
    ing = _NOT_SPIRIT.sub(" ", (ingredients or "").lower().replace("|", " ; "))
    m = _SPIRIT.search(ing)
    if m:
        return f"contains {m.group(0)}"
    m = _MAINS.search(n)
    if m and not _DISH.search(n):
        return f"'{m.group(0)}' reads as a lunch or dinner dish"
    head = _EXCEPT.sub(" ", _head(n))
    m = _CONDIMENT_END.search(head)
    if m:
        return f"a {m.group(0).strip()} on its own is not a meal"
    # a sweet or a sauce blocks unless a breakfast word comes after it ("Oatmeal Cookie
    # Pancakes" stays, "Oatmeal Chocolate Chunk Cookies" goes)
    soft = list(_SOFT.finditer(head))
    if soft:
        allow = list(_ALLOW.finditer(head))
        if not allow or allow[-1].start() < soft[-1].start():
            return f"'{soft[-1].group(0)}' reads as a dessert or a side"
    return None


def breakfast_fit(name: str, category: str | None, keywords: str | None, ingredients: str | None,
                  calories_kcal=None, protein_g=None, meal_type: str | None = None) -> str:
    if block_reason(name, ingredients or ""):
        return "no"
    kcal, prot = _num(calories_kcal), _num(protein_g)
    if kcal is None or prot is None or not (MIN_KCAL <= kcal <= MAX_KCAL) or prot < MIN_PROTEIN:
        return "no"
    kw = {k.strip().lower() for k in (keywords or "").split("|") if k.strip()}
    kw_dessert = "dessert" in kw or (category or "").lower() in ("dessert", "candy", "frozen desserts")
    n = _bare_name(name)
    named = bool(_ALLOW.search(_head(n))) or (bool(kw & {"breakfast", "brunch"}) and bool(_WEAK.search(n)))
    if kw_dessert and not named:
        return "no"
    tagged = (category or "").lower() in ("breakfast", "smoothies") or "breakfast" in kw
    is_drink = (meal_type or "") == "drink" or (category or "").lower() in ("beverages", "shakes", "punch beverage")
    if is_drink and not _DRINK_MEAL.search(n):
        # a juice, tea or milk drink is a side at breakfast, not the meal: fallback only
        return "maybe"
    if named or tagged:
        return "yes"
    if (meal_type or "") in FALLBACK_TYPES:
        return "maybe"
    return "no"
