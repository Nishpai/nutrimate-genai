"""Hard dietary constraints.

Everything here is deterministic text matching on what the dataset gives us (name,
ingredient list and instruction steps). We scan the instructions too because the
Food.com ingredient lists are sometimes incomplete (we found recipes where an
ingredient appears only in the steps).

How a group is matched:
1. Phrases that say the thing is absent are removed first ("dairy-free milk",
   "egg-free", "non-dairy creamer", "vegan butter", "without eggs").
2. Known false friends for that group are removed ("peanut butter" and "cocoa butter"
   are not dairy, "eggplant" is not egg, "nutmeg" and "coconut" are not tree nuts).
3. What is left is searched for the group's synonyms with word boundaries, so "egg"
   does not match "eggplant" and "nut" does not match "doughnut". Simple plurals
   (eggs, cashews, anchovies) and hyphen or space variants (peanut-butter) match.

This is text matching, not a food-safety guarantee. If a recipe does not mention an
allergen we can only say it was "not found in the listed ingredients", never "safe".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .meals import breakfast_fit

# ---------------------------------------------------------------------------
# Synonym map. India-relevant names are included next to the English ones.
# ---------------------------------------------------------------------------

FISH = [
    "fish", "salmon", "tuna", "cod", "tilapia", "halibut", "trout", "sardine", "anchovy", "anchovies",
    "mackerel", "haddock", "snapper", "catfish", "pomfret", "surimi", "bass", "sole", "herring",
    "swordfish", "mahi mahi", "flounder", "pollock", "rohu", "hilsa", "ilish", "katla", "surmai",
    "bangda", "bombil", "bonito", "dashi", "fish sauce", "fish paste", "fish stock", "worcestershire",
    "caviar", "roe", "imitation crab",
]
SHELLFISH = [
    "shrimp", "prawn", "crab", "lobster", "scallop", "clam", "mussel", "oyster", "crawfish",
    "crayfish", "langoustine", "squid", "calamari", "octopus", "jhinga", "jinga", "kolambi",
    "shrimp paste", "oyster sauce", "seafood",
]
MEAT = [
    "chicken", "beef", "pork", "bacon", "ham", "turkey", "lamb", "mutton", "veal", "goat meat",
    "sausage", "pepperoni", "salami", "prosciutto", "pancetta", "chorizo", "kielbasa", "bratwurst",
    "hot dog", "frankfurter", "meat", "meatball", "meatloaf", "steak", "sirloin", "brisket", "ribs", "chuck",
    "pot roast", "spare rib",
    "ground round", "venison", "bison", "rabbit", "duck", "goose", "quail", "liver", "jerky",
    "keema", "kheema", "hamburger", "moose", "elk", "boar", "pheasant", "partridge", "spam",
    "gosht", "murgh", "chicken stock", "chicken broth", "beef stock", "beef broth", "bone broth",
    "bouillon", "consomme",
    # animal fats and gelling agents count as non-vegetarian
    "lard", "suet", "tallow", "schmaltz", "beef dripping", "gelatin", "gelatine", "isinglass",
]
MEAT_FISH = MEAT + FISH + SHELLFISH

DAIRY = [
    "milk", "butter", "buttermilk", "cheese", "cream", "yogurt", "yoghurt", "curd", "dahi", "ghee",
    "paneer", "chhena", "chenna", "whey", "casein", "caseinate", "lactose", "khoa", "khoya", "mawa",
    "malai", "rabri", "lassi", "shrikhand", "kefir", "custard", "half-and-half", "half and half",
    "creme fraiche", "sour cream", "milk powder", "condensed milk", "evaporated milk",
    "parmesan", "mozzarella", "cheddar", "ricotta", "feta", "brie", "mascarpone", "gouda", "gruyere",
    "provolone", "romano", "monterey jack", "colby", "velveeta", "quark", "ice cream",
]
EGG = ["egg", "egg white", "egg yolk", "mayonnaise", "mayo", "meringue", "eggnog", "albumin",
       "albumen", "aioli", "ovalbumin"]
VEGAN_EXTRA = ["honey", "bee pollen", "royal jelly"]

ALLERGEN_GROUPS = {
    "peanut": ["peanut", "groundnut", "moongphali", "moongfali", "mungfali", "monkey nut", "arachis",
               "peanut butter", "peanut oil"],
    "tree_nut": [
        "almond", "badam", "cashew", "kaju", "walnut", "akhrot", "pecan", "pistachio", "pista",
        "hazelnut", "filbert", "macadamia", "brazil nut", "pine nut", "chilgoza", "chestnut",
        "praline", "marzipan", "nutella", "gianduja", "frangipane", "nut", "mixed nuts",
    ],
    "dairy": DAIRY,
    "egg": EGG,
    "gluten": [
        "wheat", "flour", "maida", "atta", "sooji", "suji", "semolina", "rava", "dalia", "barley",
        "rye", "spelt", "farro", "seitan", "bread", "breadcrumb", "panko", "pasta", "spaghetti",
        "macaroni", "noodle", "vermicelli", "couscous", "bulgur", "cracker", "tortilla", "soy sauce",
        "beer", "malt", "pita", "naan", "roti", "chapati", "paratha", "puri", "biscuit", "cake mix",
        "pie crust", "croissant", "bagel",
    ],
    "soy": ["soy", "soya", "soybean", "tofu", "tempeh", "edamame", "miso", "tamari", "soy sauce",
            "soy lecithin", "textured vegetable protein"],
    "fish": FISH,
    "shellfish": SHELLFISH,
    "sesame": ["sesame", "tahini", "gingelly", "benne", "til seed", "til oil", "til ladoo",
               "til laddu", "til chikki", "til gud", "safed til", "kala til"],
}

# The words used in "<word>-free", "non-<word>" and "without <word>" for each group.
_ABSENT_WORDS = {
    "dairy": r"dairy|milk|lactose|casein", "egg": r"eggs?", "gluten": r"gluten|wheat",
    "peanut": r"peanuts?", "tree_nut": r"(?:tree[\s-]?)?nuts?", "soy": r"soy|soya",
    "sesame": r"sesame", "fish": r"fish", "shellfish": r"shellfish", "meat": r"meat",
}
_SUBSTITUTE = (r"(?:vegan|plant[\s-]based|dairy[\s-]free|non[\s-]?dairy|egg[\s-]free)[\s-]+(?:[a-z]+[\s-]+)?"
               r"(?:butter|cheese|cream|milk|yogurt|yoghurt|mayo|mayonnaise|ghee|margarine|creamer|"
               r"parmesan|mozzarella|cheddar|sour cream|cream cheese|egg|eggs)s?\b")

# Phrases removed before matching a group, because they contain a group word but are
# not that thing.
NOT_THIS_GROUP = {
    "dairy": [
        "peanut butter", "almond butter", "cashew butter", "nut butter", "sunflower butter",
        "apple butter", "pumpkin butter", "cocoa butter", "cacao butter", "shea butter",
        "butter bean", "butter lettuce", "coconut milk", "coconut cream", "cream of coconut",
        "almond milk", "soy milk", "soymilk", "soya milk", "rice milk", "oat milk", "cashew milk",
        "hemp milk", "coconut yogurt", "soy yogurt", "cream of tartar", "milk thistle",
        "cream together", "cream until", "cream the",
    ],
    "egg": ["eggplant", "egg replacer", "egg substitute", "egg replacement", "flax egg", "chia egg"],
    "gluten": [
        "rice flour", "almond flour", "coconut flour", "chickpea flour", "gram flour", "besan",
        "corn flour", "cornflour", "tapioca flour", "potato flour", "buckwheat flour", "sorghum flour",
        "millet flour", "ragi flour", "jowar flour", "bajra flour", "oat flour", "soy flour",
        "rice noodle", "glass noodle", "cellophane noodle", "rice vermicelli", "corn tortilla",
        "rice paper", "breadfruit", "rice cracker", "root beer", "ginger beer", "rice pasta",
    ],
    "meat": [
        "meatless", "mock meat", "coconut meat", "nut meat", "hot dog bun", "hamburger bun",
        "vegetable bouillon", "vegetable broth", "vegetable stock", "veggie bouillon", "chicken of the woods",
    ],
    "fish": ["fish-shaped", "crab apple", "fish shaped"],
    "shellfish": ["crab apple", "oyster mushroom", "oyster cracker", "oyster plant"],
    "tree_nut": [
        "nutmeg", "coconut", "doughnut", "donut", "butternut", "water chestnut", "nut-free",
        "nut free", "tiger nut", "nutritional yeast", "nut meg",
    ],
    "peanut": [],
    "soy": [],
    "sesame": [],
}
VEGAN_NOT = ["honeydew", "honey dew"]
# plant-based versions of meat products are not meat
_MEAT_SUBSTITUTE = (r"(?:vegetarian|vegan|veggie|meatless|plant[\s-]based|soy|soya|tofu)[\s-]+(?:[a-z]+[\s-]+)?"
                    r"(?:sausage|burger|bacon|chicken|crumble|meat|mince|ground round|hot dog|nugget|"
                    r"patty|patties|chorizo|pepperoni|ham|turkey|jerky)s?\b")

# Indian convention: "vegetarian" means no meat, fish or egg. "eggetarian" allows egg.
DIETS = ("any", "eggetarian", "vegetarian", "vegan")
DIET_RANK = {"any": 0, "eggetarian": 1, "vegetarian": 2, "vegan": 3}

# Labels shown in the app for the allergen group keys
GROUP_LABELS = {
    "peanut": "peanut", "tree_nut": "tree nuts", "any_nut": "nuts (peanut and tree nuts)",
    "dairy": "dairy", "egg": "egg", "gluten": "gluten (wheat, barley, rye)", "soy": "soy",
    "fish": "fish", "shellfish": "shellfish", "sesame": "sesame",
}


def _word(w: str) -> str:
    """One synonym as a regex: spaces and hyphens are interchangeable, and a plural
    ending (s, es, or y to ies) is allowed."""
    w = w.lower()
    if w.endswith("y") and len(w) > 3 and w[-2] not in "aeiou":
        stem = re.escape(w[:-1]).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]+")
        return stem + r"(?:y|ies)"
    return re.escape(w).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]+") + r"(?:s|es)?"


def _pattern(words: list[str]) -> re.Pattern:
    """Word-boundary regex over a list of synonyms, longest first."""
    parts = sorted({_word(w) for w in words}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


def _absent_pattern(group: str) -> re.Pattern | None:
    q = _ABSENT_WORDS.get(group)
    if q is None:
        return None
    alts = [
        rf"\b(?:{q})[\s-]?free\b(?:[\s-]+[a-z]+){{0,2}}",   # dairy-free milk, egg free mayo
        rf"\bnon[\s-]?(?:{q})\b(?:[\s-]+[a-z]+){{0,2}}",     # non-dairy creamer
        rf"\b(?:{q})less\b(?:[\s-]+[a-z]+)?",                 # eggless cake
        rf"\b(?:without|omit|omitting|no)[\s-]+(?:the[\s-]+|any[\s-]+|added[\s-]+)?(?:{q})\b",
    ]
    if group in ("dairy", "egg"):
        alts.append(_SUBSTITUTE)
    if group == "meat":
        alts.append(_MEAT_SUBSTITUTE)
    return re.compile("|".join(alts))


_MATCH = {g: _pattern(w) for g, w in ALLERGEN_GROUPS.items()}
_MATCH["meat"] = _pattern(MEAT_FISH)
_MATCH["honey"] = _pattern(VEGAN_EXTRA)
_ABSENT = {g: _absent_pattern(g) for g in list(ALLERGEN_GROUPS) + ["meat"]}
_NOT = {g: _pattern(p) if p else None for g, p in NOT_THIS_GROUP.items()}
_NOT["honey"] = _pattern(VEGAN_NOT)
_GROUP_RE = {g: _MATCH[g] for g in ALLERGEN_GROUPS}  # kept for callers that read it


def _clean_for(text: str, group: str) -> str:
    text = text.lower()
    rx = _ABSENT.get(group)
    if rx is not None:
        text = rx.sub(" ", text)
    nx = _NOT.get(group)
    if nx is not None:
        text = nx.sub(" ", text)
    if group == "meat":  # fish and shellfish false friends also apply to the diet check
        for g in ("fish", "shellfish"):
            text = _NOT[g].sub(" ", text)
    return text


def group_hits(text: str, group: str) -> list[str]:
    """The words that made a group match (empty list when it does not)."""
    return sorted({m.group(0) for m in _MATCH[group].finditer(_clean_for(text, group))})


def mentions_group(text: str, group: str) -> bool:
    return bool(_MATCH[group].search(_clean_for(text, group)))


def recipe_text(name: str, ingredients: str, instructions: str) -> str:
    """The text we search for constraint checks: name, ingredients and steps, lowercased."""
    return " ".join([name or "", (ingredients or "").replace("|", " ; "), instructions or ""]).lower()


def has_meat_or_fish(text: str) -> bool:
    return mentions_group(text, "meat")


def has_egg(text: str) -> bool:
    return mentions_group(text, "egg")


def has_animal_product(text: str) -> bool:
    """Dairy, egg or honey (meat and fish are checked separately)."""
    return mentions_group(text, "dairy") or mentions_group(text, "egg") or mentions_group(text, "honey")


def allergens_in(text: str) -> list[str]:
    return [g for g in ALLERGEN_GROUPS if mentions_group(text, g)]


def normalize_exclusion(term: str) -> str:
    """Map what a user types (e.g. 'peanuts', 'nuts', 'gluten') to an allergen group if possible."""
    t = term.strip().lower()
    aliases = {
        "peanuts": "peanut", "peanut": "peanut", "groundnut": "peanut", "groundnuts": "peanut",
        "moongphali": "peanut",
        "nuts": "any_nut", "nut": "any_nut", "any_nut": "any_nut", "tree nut": "tree_nut", "tree nuts": "tree_nut",
        "tree_nut": "tree_nut", "dairy": "dairy", "lactose": "dairy", "milk": "dairy",
        "egg": "egg", "eggs": "egg", "gluten": "gluten", "wheat": "gluten", "soy": "soy",
        "soya": "soy", "fish": "fish", "shellfish": "shellfish", "seafood": "shellfish",
        "sesame": "sesame", "til": "sesame",
    }
    return aliases.get(t, t)


def term_matches(text: str, term: str) -> bool:
    """True if a user exclusion (allergen group or free ingredient word) appears in the text."""
    key = normalize_exclusion(term)
    if key == "any_nut":  # people who say "no nuts" usually mean peanuts too
        return term_matches(text, "peanut") or term_matches(text, "tree_nut")
    if key in ALLERGEN_GROUPS:
        return mentions_group(text, key)
    if not key:
        return False
    return bool(_pattern([key]).search(text.lower()))


# ---------------------------------------------------------------------------
# The constraint object and the filter
# ---------------------------------------------------------------------------

@dataclass
class Constraints:
    diet: str = "any"                      # any / eggetarian / vegetarian / vegan
    exclude: list[str] = field(default_factory=list)   # allergens and disliked ingredients
    max_calories: float | None = None      # per serving, kcal
    min_protein_g: float | None = None     # per serving, grams
    max_minutes: float | None = None
    meal_type: str | None = None
    cuisine: str | None = None             # soft by default, see hard_cuisine
    hard_cuisine: bool = False

    def describe(self) -> list[str]:
        out = []
        if self.diet != "any":
            out.append(self.diet)
        if self.exclude:
            out.append("excluding " + ", ".join(self.exclude))
        if self.max_calories is not None:
            out.append(f"at most {self.max_calories:g} kcal per serving")
        if self.min_protein_g is not None:
            out.append(f"at least {self.min_protein_g:g} g protein per serving")
        if self.max_minutes is not None:
            out.append(f"ready in {self.max_minutes:g} min or less")
        if self.meal_type:
            out.append(f"meal type: {self.meal_type}")
        if self.cuisine and self.hard_cuisine:
            out.append(f"cuisine: {self.cuisine}")
        return out


def _breakfast_fit_of(row) -> str:
    try:
        fit = row["breakfast_fit"]
    except (KeyError, IndexError):
        fit = None
    if isinstance(fit, str):
        return fit
    get = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    return breakfast_fit(get("name", ""), get("category"), get("keywords"), get("ingredients"),
                         get("calories_kcal"), get("protein_g"), get("meal_type"))


def breakfast_fit_column(recipes: pd.DataFrame) -> pd.Series:
    """breakfast_fit for every row ("yes", "maybe" or "no"), see nutrimate_core.meals."""
    def col(name):
        return recipes[name] if name in recipes else pd.Series([None] * len(recipes), index=recipes.index)
    vals = [breakfast_fit(n, c, k, i, kc, p, m) for n, c, k, i, kc, p, m in zip(
        col("name"), col("category"), col("keywords"), col("ingredients"), col("calories_kcal"),
        col("protein_g"), col("meal_type"))]
    return pd.Series(vals, index=recipes.index)


def check_recipe(row, c: Constraints) -> list[str]:
    """Return the list of rules this single recipe breaks (empty list = passes).

    Used both by the filter and by the evaluation to count violations.
    Missing nutrient values break a nutrient rule, because we cannot confirm it.
    """
    problems = []
    text = row["search_text"]
    ingredients = row["ingredients"]
    if (c.diet != "any" or c.exclude) and (not isinstance(ingredients, str) or not ingredients):
        problems.append("ingredients unknown")
    if c.diet != "any" and has_meat_or_fish(text):
        problems.append("contains meat or fish")
    if c.diet in ("vegetarian", "vegan") and has_egg(text):
        problems.append("contains egg")
    if c.diet == "vegan" and has_animal_product(text):
        problems.append("contains dairy, egg or honey")
    for term in c.exclude:
        if term_matches(text, term):
            problems.append(f"mentions {term}")
    if c.max_calories is not None:
        kcal = row["calories_kcal"]
        if kcal is None or pd.isna(kcal):
            problems.append("calories unknown")
        elif kcal > c.max_calories:
            problems.append("too many calories")
    if c.min_protein_g is not None:
        prot = row["protein_g"]
        if prot is None or pd.isna(prot):
            problems.append("protein unknown")
        elif prot < c.min_protein_g:
            problems.append("not enough protein")
    if c.max_minutes is not None:
        mins = row["total_minutes"]
        if mins is None or pd.isna(mins) or mins > c.max_minutes:
            problems.append("takes too long or time unknown")
    if c.meal_type == "breakfast":
        if _breakfast_fit_of(row) != "yes":
            problems.append("not a breakfast dish")
    elif c.meal_type and row["meal_type"] != c.meal_type:
        problems.append("different meal type")
    if c.cuisine and c.hard_cuisine and row["cuisine"] != c.cuisine:
        problems.append("different cuisine")
    return problems


def filter_recipes(recipes: pd.DataFrame, c: Constraints) -> tuple[pd.DataFrame, dict]:
    """Apply the hard constraints. Returns the passing rows and counts of why rows were removed."""
    mask = np.ones(len(recipes), dtype=bool)
    removed = {}

    def apply(name, bad):
        nonlocal mask
        bad = np.asarray(bad, dtype=bool) & mask
        if bad.any():
            removed[name] = int(bad.sum())
        mask &= ~bad

    if c.diet != "any" or c.exclude:
        # no ingredient list means we cannot check anything, so the recipe is not shown
        apply("ingredients unknown", (recipes["ingredients"].fillna("") == "").to_numpy())
    if c.diet != "any":
        apply("meat or fish", ~recipes["is_eggetarian"].to_numpy(dtype=bool))
    if c.diet in ("vegetarian", "vegan"):
        apply("egg", ~recipes["is_vegetarian"].to_numpy(dtype=bool))
    if c.diet == "vegan":
        apply("dairy, egg or honey", ~recipes["is_vegan"].to_numpy(dtype=bool))
    texts = recipes["search_text"]
    for term in c.exclude:
        apply(f"mentions {term}", texts.map(lambda t, term=term: term_matches(t, term)).to_numpy())
    if c.max_calories is not None:
        kcal = recipes["calories_kcal"]
        apply("calories unknown", kcal.isna().to_numpy())
        apply("over calorie limit", (kcal > c.max_calories).to_numpy())
    if c.min_protein_g is not None:
        prot = recipes["protein_g"]
        apply("protein unknown", prot.isna().to_numpy())
        apply("under protein minimum", (prot < c.min_protein_g).to_numpy())
    if c.max_minutes is not None:
        mins = recipes["total_minutes"]
        apply("too long or time unknown", (mins.isna() | (mins > c.max_minutes)).to_numpy())
    if c.meal_type == "breakfast":
        fit = recipes["breakfast_fit"] if "breakfast_fit" in recipes else breakfast_fit_column(recipes)
        apply("not a breakfast dish", (fit != "yes").to_numpy())
    elif c.meal_type:
        apply("different meal type", (recipes["meal_type"] != c.meal_type).to_numpy())
    if c.cuisine and c.hard_cuisine:
        apply("different cuisine", (recipes["cuisine"] != c.cuisine).to_numpy())
    return recipes[mask], removed
