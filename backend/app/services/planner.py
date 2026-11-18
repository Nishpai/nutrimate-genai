"""Deterministic meal planning.

1. For each slot (breakfast, lunch, dinner, optional snack) the ML engine ranks recipes
   that pass every hard constraint and have known nutrition.
2. Each slot gets a share of the daily calorie target. A recipe and a portion size
   (0.5 to 2 servings in quarter steps) are chosen to get close to that share, with a
   small bonus for a better model rank and a penalty for repeating a recipe.
3. Portions are then adjusted one step at a time while that brings the day's calories
   closer to the target and protein closer to its target.
All numbers are computed here from MySQL values. Gemini may only describe the result.
"""

from __future__ import annotations

from datetime import date, timedelta

from nutrimate_core import constraints as cons
from nutrimate_core.nutrition import scale, total

from .engine import UserState, engine, recipe_card
from .users import SLOT_SHARES

KEYS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]
PORTIONS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
SLOT_MEALS = {
    "breakfast": [None],  # chosen by nutrimate_core.meals.breakfast_fit, see slot_candidates
    "lunch": [["main"], ["main", "side", "other"]],
    "dinner": [["main"], ["main", "side", "other"]],
    "snack": [["snack", "side", "drink"], ["snack", "side", "drink", "dessert", "baking", "other"]],
}
N_CANDIDATES = 60
# A main meal should be a meal: at least this much protein and energy per serving. This
# keeps things like spice mixes or plain sugar syrups out of breakfast, lunch and dinner.
# Breakfast has its own bounds in nutrimate_core.meals.
MEAL_MIN = {"lunch": (8.0, 200.0), "dinner": (8.0, 200.0)}


def _is_meal(card: dict, slot: str) -> bool:
    if slot not in MEAL_MIN:
        return True
    min_protein, min_kcal = MEAL_MIN[slot]
    return (card["protein_g"] or 0) >= min_protein and (card["calories_kcal"] or 0) >= min_kcal


def slot_candidates(state: UserState, c: cons.Constraints, slot: str) -> list[dict]:
    if slot == "breakfast":
        res = engine.recommend(state, c, k=N_CANDIDATES, breakfast=True, require_nutrition=True)
        return res["items"]
    items = []
    for meal_types in SLOT_MEALS[slot]:
        res = engine.recommend(state, c, k=N_CANDIDATES, meal_types=meal_types, require_nutrition=True)
        items = [it for it in res["items"] if _is_meal(it["recipe"], slot)] or res["items"]
        if len(items) >= 5:
            return items
    return items


def item_nutrition(card: dict, servings: float) -> dict:
    return {k: (None if v is None else round(v, 1)) for k, v in scale(card, servings, KEYS).items()}


def _choose(cands, budget, protein_goal, used, rank_weight=0.02, exclude=frozenset()):
    """used counts how often each recipe already appears in the plan; exclude holds the
    recipes already on the same day, which are never picked again."""
    best = None
    for rank, it in enumerate(cands):
        card = it["recipe"]
        if card["calories_kcal"] is None or card["calories_kcal"] <= 0 or card["recipe_id"] in exclude:
            continue
        for p in PORTIONS:
            kcal = card["calories_kcal"] * p
            cost = abs(kcal - budget) / budget
            if protein_goal:
                cost += 0.3 * max(0.0, protein_goal - (card["protein_g"] or 0) * p) / protein_goal
            cost += rank_weight * rank + 0.6 * used.get(card["recipe_id"], 0)
            if best is None or cost < best[0]:
                best = (cost, it, p)
    return best


def _fallback_flag(it: dict) -> dict:
    return {"breakfast_fallback": True} if it.get("breakfast_fallback") else {}


def day_totals(meals: list[dict]) -> dict:
    return total([m["nutrition"] for m in meals], KEYS)["totals"]


def _refine(meals, target_kcal, target_protein):
    """Nudge portions while that reduces the distance to the targets."""
    def score(ms):
        t = day_totals(ms)
        s = abs(t["calories_kcal"] - target_kcal) / target_kcal
        if target_protein:
            s += 0.5 * max(0.0, target_protein - t["protein_g"]) / target_protein
        return s
    for _ in range(12):
        current = score(meals)
        best = None
        for i, m in enumerate(meals):
            for step in (-0.25, 0.25):
                p = m["servings"] + step
                if p < PORTIONS[0] or p > PORTIONS[-1]:
                    continue
                trial = [dict(x) for x in meals]
                trial[i] = {**m, "servings": p, "nutrition": item_nutrition(m["recipe"], p)}
                s = score(trial)
                if s < current - 1e-9 and (best is None or s < best[0]):
                    best = (s, trial)
        if best is None:
            break
        meals = best[1]
    return meals


def plan_day(cands_by_slot: dict, slots, target_kcal, target_protein, used: dict) -> list[dict]:
    meals = []
    today: set = set()
    remaining_share = sum(s for _, s in slots)
    remaining_kcal = target_kcal
    for slot, share in slots:
        budget = max(remaining_kcal * share / remaining_share, 100)
        protein_goal = target_protein * share if target_protein else None
        choice = _choose(cands_by_slot[slot], budget, protein_goal, used, exclude=today)
        remaining_share -= share
        if choice is None:
            continue
        _, it, p = choice
        nut = item_nutrition(it["recipe"], p)
        meals.append({"slot": slot, "recipe": it["recipe"], "servings": p, "nutrition": nut,
                      "reasons": it["reasons"][:2], **_fallback_flag(it)})
        rid = it["recipe"]["recipe_id"]
        used[rid] = used.get(rid, 0) + 1
        today.add(rid)
        remaining_kcal -= nut["calories_kcal"]
    meals = _refine(meals, target_kcal, target_protein)
    gap = target_kcal - day_totals(meals)["calories_kcal"]
    if gap > 0.08 * target_kcal and "snack" not in [m["slot"] for m in meals] and cands_by_slot.get("snack"):
        # three meals at up to two servings each could not reach the target: add a snack
        choice = _choose(cands_by_slot["snack"], max(gap, 100), None, used, exclude=today)
        if choice is not None:
            _, it, p = choice
            meals.append({"slot": "snack", "recipe": it["recipe"], "servings": p,
                          "nutrition": item_nutrition(it["recipe"], p), "reasons": it["reasons"][:2],
                          "added_to_reach_target": True})
            rid = it["recipe"]["recipe_id"]
            used[rid] = used.get(rid, 0) + 1
            meals = _refine(meals, target_kcal, target_protein)
    order = {"breakfast": 0, "lunch": 1, "snack": 2, "dinner": 3}
    return sorted(meals, key=lambda m: order.get(m["slot"], 9))


def summarise(days: list[dict], target_kcal, target_protein) -> dict:
    out = []
    for d in days:
        t = day_totals(d["meals"])
        d["totals"] = t
        d["kcal_diff_pct"] = round(100 * (t["calories_kcal"] - target_kcal) / target_kcal, 1)
        out.append(d["kcal_diff_pct"])
    return {
        "days": len(days), "target_kcal": target_kcal, "target_protein_g": target_protein,
        "avg_kcal": round(sum(d["totals"]["calories_kcal"] for d in days) / max(len(days), 1), 1),
        "avg_protein_g": round(sum(d["totals"]["protein_g"] for d in days) / max(len(days), 1), 1),
        "max_abs_kcal_diff_pct": max((abs(x) for x in out), default=0.0),
        "days_within_10pct": sum(abs(x) <= 10 for x in out),
    }


def generate(state: UserState, c: cons.Constraints, target_kcal: float, target_protein: float | None,
             days: int, meals_per_day: int, start: date | None = None) -> dict:
    slots = SLOT_SHARES[meals_per_day]
    cands = {slot: slot_candidates(state, c, slot) for slot, _ in slots}
    empty = [s for s, v in cands.items() if not v]
    if "snack" not in cands:
        cands["snack"] = slot_candidates(state, c, "snack")  # only used to top up a short day
    if empty:
        return {"days": [], "error": f"No recipes pass your rules for: {', '.join(empty)}. Try relaxing a rule."}
    used: dict = {}
    start = start or date.today()
    plan_days = []
    for d in range(days):
        meals = plan_day(cands, slots, target_kcal, target_protein, used)
        plan_days.append({"day_index": d, "date": (start + timedelta(days=d)).isoformat(), "meals": meals})
    out = {"days": plan_days, "summary": summarise(plan_days, target_kcal, target_protein),
           "rules": c.describe(), "start_date": start.isoformat()}
    n_fb = sum(1 for d in plan_days for m in d["meals"] if m.get("breakfast_fallback"))
    if n_fb:
        out["breakfast_note"] = (f"{n_fb} breakfast{'s' if n_fb > 1 else ''} in this plan "
                                 f"{'are' if n_fb > 1 else 'is'} a fallback: few breakfast recipes pass your rules, "
                                 "so a light dish not tagged as breakfast was used.")
    return out


def swap(plan: dict, day_index: int, slot: str, state: UserState, c: cons.Constraints,
         target_kcal: float, target_protein: float | None) -> dict:
    """Replace one meal with the best other candidate, keeping the day near its target."""
    day = plan["days"][day_index]
    used: dict = {}
    for d in plan["days"]:
        for m in d["meals"]:
            used[m["recipe"]["recipe_id"]] = used.get(m["recipe"]["recipe_id"], 0) + 1
    cands = [it for it in slot_candidates(state, c, slot) if it["recipe"]["recipe_id"] not in used]
    if not cands:
        raise ValueError("No other recipe passes your rules for this slot")
    if slot not in [m["slot"] for m in day["meals"]]:
        raise ValueError("that slot is not in this day")
    others = [m for m in day["meals"] if m["slot"] != slot]
    budget = max(target_kcal - sum(m["nutrition"]["calories_kcal"] for m in others), 100)
    share = dict(SLOT_SHARES[4]).get(slot, 0.3)
    _, it, p = _choose(cands, budget, (target_protein or 0) * share or None, used)
    new = {"slot": slot, "recipe": it["recipe"], "servings": p, "nutrition": item_nutrition(it["recipe"], p),
           "reasons": it["reasons"][:2], **_fallback_flag(it)}
    meals = [new if m["slot"] == slot else m for m in day["meals"]]
    day["meals"] = _refine(meals, target_kcal, target_protein)
    plan["summary"] = summarise(plan["days"], target_kcal, target_protein)
    return plan


def rebuild_from_db(plan: dict, t, c: cons.Constraints) -> dict:
    """Recompute every item from MySQL before saving, so client-sent numbers are never trusted."""
    for d in plan["days"]:
        for m in d["meals"]:
            row = t.one("SELECT * FROM recipes WHERE recipe_id = %s", (int(m["recipe"]["recipe_id"]),))
            if row is None:
                raise ValueError("unknown recipe in plan")
            card = recipe_card(row)
            problems = engine.check(card["recipe_id"], c)
            if problems:
                raise ValueError(f"{card['name']} breaks your rules: {', '.join(problems)}")
            servings = float(m["servings"])
            if not PORTIONS[0] <= servings <= PORTIONS[-1]:
                raise ValueError("portion out of range")
            m.update({"recipe": card, "servings": servings, "nutrition": item_nutrition(card, servings)})
    return plan
