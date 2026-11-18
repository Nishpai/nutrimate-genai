"""Turn a chat message into a structured request with regular expressions.

The parser is deterministic and works offline. The assistant uses it to read diet,
calorie, protein, time, cuisine, meal type and exclusions from a message. Gemini is
never used for this step, so a request can not be changed by the language model.
"""

from __future__ import annotations

import re

from .constraints import DIET_RANK, Constraints, normalize_exclusion

CUISINE_WORDS = {
    "indian": "Indian", "south indian": "Indian", "north indian": "Indian", "punjabi": "Indian",
    "thai": "Thai", "chinese": "Chinese", "japanese": "Japanese", "korean": "Korean",
    "vietnamese": "Vietnamese", "mexican": "Mexican", "middle eastern": "Middle Eastern",
    "lebanese": "Middle Eastern", "turkish": "Middle Eastern", "greek": "Greek",
    "caribbean": "Caribbean", "cajun": "Cajun/Creole", "african": "African", "european": "European",
    "german": "European", "spanish": "European", "italian": "European", "asian": "Asian",
    "american": "American", "south american": "South American",
}
CUISINES = sorted(set(CUISINE_WORDS.values()))
MEAL_TYPES = ["breakfast", "main", "side", "snack", "dessert", "drink", "baking", "sauce"]
MEAL_WORDS = {
    "breakfast": "breakfast", "brunch": "breakfast", "lunch": "main", "dinner": "main", "supper": "main",
    "main course": "main", "main dish": "main", "snack": "snack", "dessert": "dessert", "sweet dish": "dessert",
    "drink": "drink", "smoothie": "drink", "beverage": "drink", "side dish": "side", "side": "side",
}

REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["meal_type", "diet", "cuisine", "max_calories", "min_protein_g", "max_minutes",
                 "excluded_ingredients", "prefer_high_protein", "prefer_low_calorie"],
    "properties": {
        "meal_type": {"enum": MEAL_TYPES + [None]},
        "diet": {"enum": ["any", "eggetarian", "vegetarian", "vegan"]},
        "cuisine": {"enum": CUISINES + [None]},
        "max_calories": {"type": ["number", "null"], "minimum": 50, "maximum": 3000},
        "min_protein_g": {"type": ["number", "null"], "minimum": 0, "maximum": 200},
        "max_minutes": {"type": ["number", "null"], "minimum": 1, "maximum": 1440},
        "excluded_ingredients": {"type": "array", "maxItems": 20,
                                 "items": {"type": "string", "minLength": 2, "maxLength": 40}},
        "prefer_high_protein": {"type": "boolean"},
        "prefer_low_calorie": {"type": "boolean"},
    },
}

STOP_AFTER_EXCLUSION = re.compile(
    r"\b(?:suggest|something|please|pls|under|below|less|within|with|for|that|i|i'm|im|me|"
    r"make|give|show|find|recipe|recipes|dish|dishes|meal|meals|in|at|but|which|is|are)\b|[.;!?]")
EXCLUSION_TRIGGER = re.compile(
    r"\b(?:avoid(?:ing)?|without|exclude|excluding|skip|allergic to|allergy to|hate|"
    r"(?:do not|don't|dont) (?:like|want|eat)|no)\s+(?!more\b|less\b|than\b)")


def empty_request() -> dict:
    return {"meal_type": None, "diet": "any", "cuisine": None, "max_calories": None,
            "min_protein_g": None, "max_minutes": None, "excluded_ingredients": [],
            "prefer_high_protein": False, "prefer_low_calorie": False}


def singular(word: str) -> str:
    w = word.strip()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("oes"):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us")) and len(w) > 3:
        return w[:-1]
    return w


def _is_request_word(part: str) -> bool:
    """True for chunks like 'thai dinner' that describe the request, not an ingredient."""
    words = list(CUISINE_WORDS) + list(MEAL_WORDS) + ["vegan", "vegetarian", "veg", "food", "lunch", "dinner"]
    return any(re.search(r"\b" + w + r"s?\b", part) for w in words)


def _exclusions(text: str) -> list[str]:
    found = []
    triggers = list(EXCLUSION_TRIGGER.finditer(text))
    for n, m in enumerate(triggers):
        end = triggers[n + 1].start() if n + 1 < len(triggers) else len(text)
        rest = text[m.end():end]
        stop = STOP_AFTER_EXCLUSION.search(rest)
        chunk = rest[: stop.start()] if stop else rest
        for part in re.split(r",|\band\b|\bor\b|/", chunk):
            part = re.sub(r"\b(?:any|some|the|a|an|like|eat|want)\b", " ", part).strip(" -'")
            part = re.sub(r"\s+", " ", part)
            free = re.fullmatch(r"([a-z]+) free", part)
            if free:
                part = free.group(1)
            if 2 <= len(part) <= 40 and len(part.split()) <= 3 and not _is_request_word(part):
                found.append(part)
    for m in re.finditer(r"\b([a-z]+) free\b", text):  # gluten-free, nut free, dairy-free
        found.append(m.group(1))
    out = []
    for f in found:
        f = singular(f)
        if f in ("meat", "non veg", "non-veg"):
            continue  # handled as a diet
        key = normalize_exclusion(f)
        if key not in out:
            out.append(key)
    return out


def parse_rule_based(message: str) -> dict:
    text = " " + message.lower().replace("-", " ").replace("’", "'") + " "
    req = empty_request()
    notes, follow_up = [], None

    # diet
    if re.search(r"\bvegan\b|\bplant based\b", text):
        req["diet"] = "vegan"
    elif re.search(r"\beggetarian\b|\bovo vegetarian\b|\bveg(?:etarian)? (?:but|with) eggs?\b", text):
        req["diet"] = "eggetarian"
    elif re.search(r"\bvegetarian\b|\bveggie\b|\bveg\b(?! ?gies)|\bno meat\b|\bmeatless\b|\bwithout meat\b", text) \
            and not re.search(r"\bnon ?veg", text):
        req["diet"] = "vegetarian"

    # calories: "under 600 calories", "600 kcal max", "a 500 calorie lunch"
    cal_unit = r"(?:k?cals?|calories|calorie)"
    m = re.search(r"(?:under|below|less than|at most|max(?:imum)?|no more than|up to|upto|within|<=?)\s*"
                  r"(\d+)\s*" + cal_unit, text)
    if m:
        req["max_calories"] = float(m.group(1))
    else:
        m = re.search(r"\b(\d+)\s*" + cal_unit, text)
        if m:
            req["max_calories"] = float(m.group(1))
            notes.append(f"Treated {m.group(1)} kcal as an upper limit per serving.")
    if req["max_calories"] is None:
        bare = re.search(r"\b(?:under|below|less than)\s+(\d{3,4})\b(?!\s*(?:g|grams|min|minutes|mins))", text)
        if bare:
            follow_up = f"Did you mean at most {bare.group(1)} kcal per serving? Please say it with the unit."
    if re.search(r"\blow (?:cal|calorie|kcal)|\blight\b", text):
        req["prefer_low_calorie"] = True

    # protein: "at least 25 g protein", "30g protein", "high protein"
    m = re.search(r"\b(\d+)\s*(?:g|gm|grams?)\s*(?:of\s+)?protein", text)
    if m:
        req["min_protein_g"] = float(m.group(1))
    if re.search(r"\bhigh (?:in )?protein\b|\bprotein rich\b|\blots of protein\b", text):
        req["prefer_high_protein"] = True

    # time
    m = re.search(r"(?:under|less than|within|in|max(?:imum)?)\s*(\d+)\s*(?:min|mins|minutes)\b", text)
    if m:
        req["max_minutes"] = float(m.group(1))
    elif re.search(r"\bquick\b|\bfast\b", text):
        req["max_minutes"] = 30.0
        notes.append("Took 'quick' to mean 30 minutes or less.")

    # cuisine and meal type
    for word in sorted(CUISINE_WORDS, key=len, reverse=True):
        if re.search(r"\b" + word + r"\b", text):
            req["cuisine"] = CUISINE_WORDS[word]
            if word == "italian":
                notes.append("Food.com has no Italian tag in this data, so I used European.")
            break
    for word in sorted(MEAL_WORDS, key=len, reverse=True):
        if re.search(r"\b" + word + r"s?\b", text):
            req["meal_type"] = MEAL_WORDS[word]
            if word in ("lunch", "dinner", "supper"):
                notes.append("Food.com does not separate lunch and dinner, so I searched main dishes.")
            break

    req["excluded_ingredients"] = _exclusions(text)

    # numbers outside the schema range are dropped with a question instead of being clipped
    for key in ("max_calories", "min_protein_g", "max_minutes"):
        rng = REQUEST_SCHEMA["properties"][key]
        if req[key] is not None and not (rng["minimum"] <= req[key] <= rng["maximum"]):
            follow_up = (f"{req[key]:g} looks out of range for {key.replace('_', ' ')} "
                         f"(allowed {rng['minimum']} to {rng['maximum']}). Could you check that number?")
            req[key] = None

    if req == empty_request() and follow_up is None:
        follow_up = ("I could not find any preference in that. What kind of meal do you want? For example: "
                     "'vegetarian dinner under 600 kcal, no peanuts'.")
    return {"request": req, "notes": notes, "follow_up": follow_up, "parser": "rule-based"}


def validate(req: dict) -> dict:
    """Check the request against the allowed ranges and enums. Raises ValueError."""
    props = REQUEST_SCHEMA["properties"]
    if set(req) != set(REQUEST_SCHEMA["required"]):
        raise ValueError("unexpected request keys")
    for key in ("meal_type", "diet", "cuisine"):
        if req[key] not in props[key]["enum"]:
            raise ValueError(f"bad value for {key}")
    for key in ("max_calories", "min_protein_g", "max_minutes"):
        v = req[key]
        if v is not None and not (props[key]["minimum"] <= v <= props[key]["maximum"]):
            raise ValueError(f"{key} out of range")
    return req


def parse(message: str) -> dict:
    """Parse a chat message. Always returns a valid request."""
    result = parse_rule_based(message)
    validate(result["request"])
    return result


def request_preference_text(req: dict) -> str:
    """Extra text for the content profile, built from the parsed request (cuisine and the
    Food.com 'High Protein' tag). It only nudges ranking; the hard rules come from to_constraints."""
    parts = []
    if req["cuisine"]:
        slug = "".join(ch if ch.isalnum() else "_" for ch in req["cuisine"].lower())
        parts += [f"cuisine_{slug}", f"tag_{slug}"]
    if req["prefer_high_protein"]:
        parts.append("tag_high_protein")
    return " ".join(parts)


def to_constraints(req: dict, base: Constraints | None = None) -> Constraints:
    """Merge a parsed request with the saved profile. Profile exclusions always stay on:
    a chat message can add rules but cannot remove an allergen from the profile."""
    base = base or Constraints()
    diet = max([base.diet, req["diet"]], key=lambda d: DIET_RANK[d])
    exclude = list(dict.fromkeys(base.exclude + req["excluded_ingredients"]))
    return Constraints(
        diet=diet, exclude=exclude,
        max_calories=req["max_calories"] if req["max_calories"] is not None else base.max_calories,
        min_protein_g=req["min_protein_g"] if req["min_protein_g"] is not None else base.min_protein_g,
        max_minutes=req["max_minutes"] if req["max_minutes"] is not None else base.max_minutes,
        meal_type=req["meal_type"] or base.meal_type,
        cuisine=req["cuisine"] or base.cuisine, hard_cuisine=bool(req["cuisine"]),
    )
