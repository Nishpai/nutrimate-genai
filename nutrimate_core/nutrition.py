"""Deterministic nutrition arithmetic.

Every number the app shows about food comes from here or straight from MySQL. Unknown
values stay None the whole way through: they are never treated as zero. A total that
includes an unknown value is marked incomplete and lists which items were unknown.
"""

from __future__ import annotations

import math

NUTRIENTS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]
MACROS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]


def clean(value) -> float | None:
    """Turn any DB or pandas value into a float, or None when unknown."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return v


def scale(values: dict, factor: float, keys=NUTRIENTS) -> dict:
    """Multiply known nutrient values by a portion factor. Unknown stays unknown."""
    out = {}
    for k in keys:
        v = clean(values.get(k))
        out[k] = None if v is None else v * factor
    return out


def per_100g_to_portion(values_100g: dict, grams: float, keys=NUTRIENTS) -> dict:
    return scale(values_100g, grams / 100.0, keys)


def total(items: list[dict], keys=NUTRIENTS, label_key: str = "name") -> dict:
    """Sum nutrients over items. Returns totals, plus which items had unknown values."""
    sums = {k: 0.0 for k in keys}
    unknown = {k: [] for k in keys}
    for it in items:
        for k in keys:
            v = clean(it.get(k))
            if v is None:
                unknown[k].append(it.get(label_key, "?"))
            else:
                sums[k] += v
    return {
        "totals": {k: round(sums[k], 1) for k in keys},
        "unknown": {k: names for k, names in unknown.items() if names},
        "complete": not any(unknown.values()),
    }


def round_values(values: dict, digits: int = 1) -> dict:
    return {k: (None if clean(v) is None else round(float(v), digits)) for k, v in values.items()}


def macro_energy_split(protein_g, carbs_g, fat_g) -> dict | None:
    """Share of energy from each macro using 4/4/9 kcal per gram. None if any is unknown."""
    p, c, f = clean(protein_g), clean(carbs_g), clean(fat_g)
    if p is None or c is None or f is None:
        return None
    kcal = 4 * p + 4 * c + 9 * f
    if kcal <= 0:
        return None
    return {"protein": round(400 * p / kcal, 1), "carbs": round(400 * c / kcal, 1),
            "fat": round(900 * f / kcal, 1)}


def percent_of(value, target) -> float | None:
    v, t = clean(value), clean(target)
    if v is None or not t:
        return None
    return round(100 * v / t, 1)
