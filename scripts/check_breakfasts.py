"""Generate a week plan for a range of diet and allergy profiles and list the breakfasts.

Needs MySQL with the catalogue loaded and the trained models. It writes
reports/breakfast_check.json (or the path given with --out) and prints a short table.

    python scripts/check_breakfasts.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.services import planner  # noqa: E402
from backend.app.services.engine import UserState, engine  # noqa: E402
from nutrimate_core import constraints as cons  # noqa: E402
from nutrimate_core.paths import REPORTS  # noqa: E402

PROFILES = [
    ("non-veg, no allergies", "any", [], ["American"]),
    ("non-veg, gluten and egg", "any", ["gluten", "egg"], ["Mexican"]),
    ("eggetarian, no allergies", "eggetarian", [], ["Indian"]),
    ("eggetarian, dairy", "eggetarian", ["dairy"], []),
    ("vegetarian, no allergies", "vegetarian", [], ["Indian"]),
    ("vegetarian, peanut and mushroom", "vegetarian", ["peanut", "mushroom"], ["Indian", "Thai"]),
    ("vegetarian, gluten", "vegetarian", ["gluten"], ["European"]),
    ("vegetarian, tree nuts and sesame", "vegetarian", ["tree_nut", "sesame"], []),
    ("vegan, no allergies", "vegan", [], ["Indian"]),
    ("vegan, peanut, tree nuts and soy", "vegan", ["peanut", "tree_nut", "soy"], []),
    ("vegan, gluten and sesame", "vegan", ["gluten", "sesame"], []),
    ("vegan, peanut, tree nuts, soy and gluten", "vegan", ["peanut", "tree_nut", "soy", "gluten"], []),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPORTS / "breakfast_check.json"))
    ap.add_argument("--kcal", type=float, default=2000)
    ap.add_argument("--protein", type=float, default=70)
    args = ap.parse_args()
    engine.load()
    results = []
    for label, diet, excl, cuisines in PROFILES:
        c = cons.Constraints(diet=diet, exclude=excl)
        state = UserState(cuisines=cuisines, goal="maintain", per_meal_kcal=args.kcal / 3)
        plan = planner.generate(state, c, args.kcal, args.protein, days=7, meals_per_day=3,
                                start=date(2026, 1, 5))
        if plan.get("error"):
            results.append({"profile": label, "error": plan["error"]})
            continue
        bfs = []
        for d in plan["days"]:
            for m in d["meals"]:
                if m["slot"] == "breakfast":
                    bfs.append({"name": m["recipe"]["name"], "servings": m["servings"],
                                "kcal": m["nutrition"]["calories_kcal"], "protein_g": m["nutrition"]["protein_g"],
                                "fallback": bool(m.get("breakfast_fallback")),
                                "problems": engine.check(m["recipe"]["recipe_id"], c)})
        results.append({"profile": label, "breakfasts": bfs,
                        "days_within_10pct": plan["summary"]["days_within_10pct"],
                        "breakfast_note": plan.get("breakfast_note")})
    Path(args.out).write_text(json.dumps({"kcal_target": args.kcal, "protein_target": args.protein,
                                          "profiles": results}, indent=2))
    for r in results:
        if "error" in r:
            print(f"{r['profile']}: {r['error']}")
            continue
        names = Counter(b["name"] for b in r["breakfasts"])
        fb = sum(b["fallback"] for b in r["breakfasts"])
        bad = sum(bool(b["problems"]) for b in r["breakfasts"])
        print(f"{r['profile']} | within 10%: {r['days_within_10pct']}/7 | fallback: {fb} | rule breaks: {bad}")
        for n, k in names.items():
            print(f"    {k}x {n}")


if __name__ == "__main__":
    main()
