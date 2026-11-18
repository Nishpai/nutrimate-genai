"""Load the processed recipe and food catalogue into MySQL (the source of truth for
nutrition values). Creates the tables first if needed. Safe to rerun: rows are upserted.

    python -m backend.scripts.load_catalogue
"""

from __future__ import annotations

import math
import time

import pandas as pd

from backend.app import db
from nutrimate_core.paths import PROCESSED

RECIPE_COLS = ["recipe_id", "name", "category", "keywords", "ingredients", "instructions", "description",
               "total_minutes", "servings", "year", "calories_kcal", "protein_g", "carbs_g", "fat_g",
               "fiber_g", "sugar_g", "sodium_mg", "sat_fat_g", "nutrition_status", "cuisine", "meal_type",
               "is_eggetarian", "is_vegetarian", "is_vegan", "allergens_found", "in_cf_data", "n_ratings",
               "mean_rating", "source"]
FOOD_COLS = ["food_id", "name", "source", "food_group", "kcal_100g", "protein_100g", "carbs_100g", "fat_100g",
             "fiber_100g", "sugar_100g", "sodium_100g", "serving_unit", "kcal_serving", "protein_serving",
             "carbs_serving", "fat_serving", "fiber_serving"]


def _val(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    if hasattr(v, "item"):
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    if isinstance(v, bool):
        return int(v)
    return v


def upsert(t: db.Tx, table: str, cols: list[str], df: pd.DataFrame, batch: int = 1000) -> int:
    df = df[cols].astype(object).where(df[cols].notna(), None)
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{c} = VALUES({c})" for c in cols[1:])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
    rows = [tuple(_val(v) for v in r) for r in df.itertuples(index=False, name=None)]
    for s in range(0, len(rows), batch):
        t.many(sql, rows[s:s + batch])
    return len(rows)


def main():
    t0 = time.time()
    db.init_schema()
    recipes = pd.read_parquet(PROCESSED / "recipes.parquet")
    foods = pd.read_parquet(PROCESSED / "foods.parquet")
    with db.tx() as t:
        n_r = upsert(t, "recipes", RECIPE_COLS, recipes)
        n_f = upsert(t, "foods", FOOD_COLS, foods)
    print(f"loaded {n_r:,} recipes and {n_f:,} foods into MySQL in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
