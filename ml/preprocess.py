"""Step 2: clean the raw Parquet files into the processed catalogue.

Input  (data/interim/):  recipes_raw, reviews_raw, indb, usda_* Parquet files
Output (data/processed/):
  recipes.parquet        recipe catalogue, per-serving nutrition, diet flags, allergens
  interactions.parquet   anonymised user-recipe ratings (1 to 5)
  foods.parquet          INDB and USDA foods, per 100 g (INDB also per serving)
  nutrition_flags.parquet recipes whose listed nutrition was not trusted
  summary.json

Decisions (see docs/METHODOLOGY.md):
  * ratings of 0 are reviews without stars and are dropped
  * the ratings are reduced to a 20-user / 15-recipe core so CF has enough signal
  * popular Indian recipes outside the core are added as cold-start items
  * implausible nutrition becomes null, never zero
The heavy work (1.4 million reviews, 522 thousand recipes) runs in Polars lazy frames.
Only the final catalogue of a few thousand recipes is turned into Python objects.
"""

from __future__ import annotations

import html
import json
import re

import numpy as np
import polars as pl

from nutrimate_core import constraints as cons
from nutrimate_core.paths import INTERIM, PROCESSED, params

NON_FOOD = {"Household Cleaner", "Bath/Beauty", "Homeopathy/Remedies"}
# A few non-food "recipes" are filed under food categories, so we also check names.
NON_FOOD_NAME = re.compile(
    r"play ?dough|dog (?:treat|biscuit|cookie)s?|(?:for|doggie) dogs?|dog treats|pumpkin dog|"
    r"frosty paws|cleaner|tub and shower|chews for dogs|good doggie", re.I)


def is_food(name, category, keywords):
    if category in NON_FOOD or NON_FOOD & set(k for k in keywords if k):
        return False
    return not NON_FOOD_NAME.search(name or "")

CUISINES = [  # specific names first, broad regions last
    ("Indian", ["Indian", "Pakistani"]),
    ("Thai", ["Thai"]),
    ("Chinese", ["Chinese", "Szechuan", "Hunan"]),
    ("Japanese", ["Japanese"]),
    ("Korean", ["Korean"]),
    ("Vietnamese", ["Vietnamese"]),
    ("Mexican", ["Mexican", "Tex Mex"]),
    ("Middle Eastern", ["Southwest Asia (middle East)", "Lebanese", "Turkish", "Moroccan", "Egyptian"]),
    ("Greek", ["Greek"]),
    ("Caribbean", ["Caribbean", "Cuban", "Puerto Rican"]),
    ("Cajun/Creole", ["Cajun", "Creole"]),
    ("African", ["African", "South African", "Ethiopian"]),
    ("European", ["European", "German", "Spanish", "Polish", "Swedish", "Scandinavian", "Russian",
                  "Swiss", "Hungarian", "Portuguese", "Danish", "Norwegian", "Scottish", "Belgian",
                  "Dutch", "Czech", "Welsh", "Finnish", "Icelandic"]),
    ("Asian", ["Asian", "Indonesian", "Malaysian", "Filipino"]),
    ("South American", ["South American", "Brazilian", "Peruvian", "Chilean", "Colombian", "Venezuelan"]),
    ("American", ["Southwestern U.S.", "Canadian", "Hawaiian", "Pennsylvania Dutch", "Native American"]),
]

MEAL_TYPES = {
    "breakfast": {"Breakfast", "Brunch", "Scones"},
    "dessert": {"Dessert", "Pie", "Bar Cookie", "Drop Cookies", "Candy", "Frozen Desserts", "Cheesecake",
                "Tarts", "Jellies", "Chocolate Chip Cookies", "Gelatin"},
    "drink": {"Beverages", "Smoothies", "Shakes", "Punch Beverage"},
    "main": {"One Dish Meal", "Chicken", "Chicken Breast", "Chicken Thigh & Leg", "Whole Chicken", "Meat",
             "Pork", "Steak", "Roast Beef", "Stew", "Curries", "Poultry", "Lamb/Sheep", "Ham", "Meatloaf",
             "Tilapia", "Tuna", "Crab", "Whole Turkey", "Turkey Breasts", "Savory Pies", "Spaghetti",
             "Penne", "Pasta Shells", "Gumbo", "Chowders", "Lentil", "Black Beans", "Soy/Tofu", "Manicotti",
             "Macaroni And Cheese", "Halibut", "Catfish", "Trout", "Lobster", "Squid", "Mahi Mahi",
             "Whole Duck", "Duck", "Duck Breasts", "Deer", "Wild Game", "Perch", "Whitefish",
             "Orange Roughy", "Veal", "Moose", "Elk", "Chicken Livers", "Crawfish", "Clear Soup"},
    "snack": {"Lunch/Snacks", "Spreads", "< 15 Mins"},
    "side": {"Vegetable", "Potato", "Rice", "Long Grain Rice", "White Rice", "Brown Rice", "Beans", "Corn",
             "Yam/Sweet Potato", "Cauliflower", "Grains", "Onions", "Spinach", "Greens", "Peppers",
             "Collard Greens", "Chard", "Short Grain Rice", "Medium Grain Rice", "Fruit"},
    "baking": {"Quick Breads", "Breads", "Yeast Breads", "Sourdough Breads"},
    "sauce": {"Sauces", "Salad Dressings", "Stocks"},
}


NUTRIENTS = {  # source column -> our column (all per serving)
    "Calories": "calories_kcal", "ProteinContent": "protein_g", "CarbohydrateContent": "carbs_g",
    "FatContent": "fat_g", "FiberContent": "fiber_g", "SugarContent": "sugar_g",
    "SodiumContent": "sodium_mg", "SaturatedFatContent": "sat_fat_g",
}


def iso_minutes(s):
    """'PT1H30M' -> 90. None when missing or unparseable."""
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m or not any(m.groups()):
        return None
    h, mi, _ = (int(g) if g else 0 for g in m.groups())
    return float(h * 60 + mi)


def join_list(items, sep="|"):
    return sep.join(str(x).strip() for x in (items if items is not None else []) if x)


def pick_cuisine(keywords):
    kw = set(keywords or [])
    for name, tags in CUISINES:
        if kw & set(tags):
            return name
    return "Unspecified"


def pick_meal_type(category, keywords):
    for mt, cats in MEAL_TYPES.items():
        if category in cats:
            return mt
    kw = set(keywords or [])
    for mt in ["breakfast", "dessert", "drink", "main"]:
        if kw & MEAL_TYPES[mt]:
            return mt
    return "other"


def food_filter() -> pl.Expr:
    non_food = list(NON_FOOD)
    return (
        ~pl.col("RecipeCategory").fill_null("").is_in(non_food)
        & ~pl.col("Keywords").fill_null([]).list.eval(pl.element().is_in(non_food)).list.any()
        & ~pl.col("Name").fill_null("").str.contains("(?i)" + NON_FOOD_NAME.pattern)
    )


def build_interactions(food_ids: pl.LazyFrame, p: dict) -> pl.DataFrame:
    rev = (
        pl.scan_parquet(INTERIM / "reviews_raw.parquet")
        .select(pl.col("AuthorId").alias("user_src"), pl.col("RecipeId").cast(pl.Int64).alias("recipe_id"),
                pl.col("Rating").alias("rating"), pl.col("DateSubmitted").alias("ts"))
        .filter(pl.col("rating") > 0)
        .join(food_ids, on="recipe_id", how="semi")
        .sort("ts")
        .unique(["user_src", "recipe_id"], keep="last")
        .collect()
    )
    d = rev
    for _ in range(50):  # repeat until both thresholds hold at once (k-core)
        before = d.height
        d = d.filter(pl.len().over("user_src") >= p["min_user_ratings"])
        d = d.filter(pl.len().over("recipe_id") >= p["min_recipe_ratings"])
        if d.height == before:
            break
    order = d.group_by("user_src").agg(pl.col("ts").min()).sort(["ts", "user_src"])
    order = order.with_row_index("n", offset=1).select(
        "user_src", pl.format("u{}", pl.col("n").cast(pl.String).str.zfill(5)).alias("user_id"))
    d = d.join(order, on="user_src").sort(["ts", "user_id"])
    return d.select("user_id", "recipe_id", pl.col("rating").cast(pl.Int8),
                    pl.col("ts").dt.convert_time_zone("UTC").dt.replace_time_zone(None).alias("ts"))


def clean_nutrition(rec: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    kcal, p, c, f = (pl.col(x) for x in ["Calories", "ProteinContent", "CarbohydrateContent", "FatContent"])
    atwater = 4 * p + 4 * c + 9 * f
    reason = (
        pl.when((kcal == 0) & (p == 0) & (c == 0) & (f == 0)).then(pl.lit("all values zero (calculator probably failed)"))
        .when((kcal > 2500) | (p > 250) | (c > 400) | (f > 250)).then(pl.lit("implausibly large for one serving"))
        .when((kcal > 50) & ((atwater - kcal).abs() / kcal > 0.5)).then(pl.lit("calories do not match macros (>50% off)"))
        .otherwise(None)
    )
    rec = rec.with_columns(reason.alias("flag_reason"))
    flags = rec.filter(pl.col("flag_reason").is_not_null()).select(
        pl.col("RecipeId").cast(pl.Int64).alias("recipe_id"), "Name", *NUTRIENTS.keys(), "flag_reason")
    bad = pl.col("flag_reason").is_not_null()
    rec = rec.with_columns(
        *[pl.when(bad).then(None).otherwise(pl.col(s).cast(pl.Float64)).alias(d) for s, d in NUTRIENTS.items()],
        pl.when(bad).then(pl.lit("flagged_missing")).otherwise(pl.lit("listed")).alias("nutrition_status"),
    )
    return rec, flags


def build_recipes(core_ids: pl.DataFrame, stats: pl.DataFrame, p: dict):
    raw = (pl.scan_parquet(INTERIM / "recipes_raw.parquet")
           .with_columns(pl.col("RecipeId").cast(pl.Int64))
           .filter(food_filter()))
    core = raw.join(core_ids.lazy(), left_on="RecipeId", right_on="recipe_id", how="semi")
    indian = pl.col("Keywords").fill_null([]).list.eval(pl.element().is_in(["Indian", "Pakistani"])).list.any()
    extra = (raw.join(core_ids.lazy(), left_on="RecipeId", right_on="recipe_id", how="anti")
             .filter(indian & (pl.col("ReviewCount").fill_null(0) >= 3))
             .sort(["ReviewCount", "RecipeId"], descending=[True, False]).head(p["extra_indian"]))
    rec = pl.concat([core.collect(), extra.collect()])
    rec, flags = clean_nutrition(rec)

    rows = rec.to_dicts()  # a few thousand recipes, plain Python is fine here
    out = []
    for r in rows:
        name = html.unescape(r["Name"] or "").strip()
        ingredients = join_list(r["RecipeIngredientParts"])
        instructions = html.unescape(join_list(r["RecipeInstructions"], "\n"))
        text = cons.recipe_text(name, ingredients, instructions)
        egg_ok = not cons.has_meat_or_fish(text)
        veg = egg_ok and not cons.has_egg(text)
        out.append({
            "recipe_id": r["RecipeId"], "name": name,
            "category": r["RecipeCategory"] or "Unknown",
            "keywords": join_list(r["Keywords"]), "ingredients": ingredients,
            "instructions": instructions,
            "description": html.unescape(r["Description"] or "")[:400],
            "total_minutes": iso_minutes(r["TotalTime"]),
            "servings": r["RecipeServings"],
            "year": r["DatePublished"].year if r["DatePublished"] else None,
            **{d: r[d] for d in NUTRIENTS.values()},
            "nutrition_status": r["nutrition_status"],
            "cuisine": pick_cuisine(r["Keywords"]),
            "meal_type": pick_meal_type(r["RecipeCategory"], r["Keywords"]),
            "is_eggetarian": egg_ok, "is_vegetarian": veg,
            "is_vegan": veg and not cons.has_animal_product(text),
            "allergens_found": "|".join(cons.allergens_in(text)),
        })
    df = pl.DataFrame(out, infer_schema_length=None)
    df = df.with_columns(pl.col("recipe_id").is_in(core_ids["recipe_id"].implode()).alias("in_cf_data"))
    df = df.join(stats, on="recipe_id", how="left").with_columns(
        pl.col("n_ratings").fill_null(0).cast(pl.Int32),
        pl.lit("Food.com Recipes and Reviews (CC0)").alias("source"))
    return df, flags


def build_foods() -> pl.DataFrame:
    indb = pl.read_parquet(INTERIM / "indb.parquet")
    num = lambda c: pl.col(c).cast(pl.Float64, strict=False)  # noqa: E731
    a = indb.select(
        pl.format("INDB:{}", pl.col("food_code")).alias("food_id"),
        pl.col("food_name").str.strip_chars().alias("name"),
        pl.lit("Indian Nutrient Databank (INDB 2024.11)").alias("source"),
        num("energy_kcal").alias("kcal_100g"), num("protein_g").alias("protein_100g"),
        num("carb_g").alias("carbs_100g"), num("fat_g").alias("fat_100g"),
        num("fibre_g").alias("fiber_100g"), num("freesugar_g").alias("sugar_100g"),
        num("sodium_mg").alias("sodium_100g"),
        pl.col("servings_unit").cast(pl.String).alias("serving_unit"),
        num("unit_serving_energy_kcal").alias("kcal_serving"),
        num("unit_serving_protein_g").alias("protein_serving"),
        num("unit_serving_carb_g").alias("carbs_serving"),
        num("unit_serving_fat_g").alias("fat_serving"),
        num("unit_serving_fibre_g").alias("fiber_serving"),
        pl.lit("Indian").alias("food_group"),
    )
    ids = {1008: "kcal_100g", 1003: "protein_100g", 1005: "carbs_100g", 1004: "fat_100g",
           1079: "fiber_100g", 2000: "sugar_100g", 1093: "sodium_100g"}
    fn = (pl.scan_parquet(INTERIM / "usda_food_nutrient.parquet")
          .filter(pl.col("nutrient_id").is_in(list(ids)))
          .group_by(["fdc_id", "nutrient_id"]).agg(pl.col("amount").mean())
          .collect()
          .pivot(on="nutrient_id", index="fdc_id", values="amount"))
    fn = fn.rename({str(k): v for k, v in ids.items() if str(k) in fn.columns})
    for v in ids.values():
        if v not in fn.columns:
            fn = fn.with_columns(pl.lit(None, dtype=pl.Float64).alias(v))
    cats = pl.read_csv(next((INTERIM.parent / "raw").glob("usda_sr_legacy/**/food_category.csv")))
    food = (pl.read_parquet(INTERIM / "usda_food.parquet")
            .join(cats.select(pl.col("id").alias("food_category_id"), pl.col("description").alias("food_group")),
                  on="food_category_id", how="left"))
    b = food.join(fn, on="fdc_id", how="left").select(
        pl.format("USDA:{}", pl.col("fdc_id")).alias("food_id"),
        pl.col("description").alias("name"),
        pl.lit("USDA FoodData Central SR Legacy (2018)").alias("source"),
        *[pl.col(v).cast(pl.Float64) for v in ids.values()],
        pl.lit(None, dtype=pl.String).alias("serving_unit"),
        *[pl.lit(None, dtype=pl.Float64).alias(c) for c in
          ["kcal_serving", "protein_serving", "carbs_serving", "fat_serving", "fiber_serving"]],
        pl.col("food_group").cast(pl.String),
    )
    foods = pl.concat([a, b.select(a.columns)])
    # per-100 g values outside physical limits are unknown, not zero
    limits = {"kcal_100g": 902, "protein_100g": 100, "carbs_100g": 100, "fat_100g": 100, "fiber_100g": 100,
              "sugar_100g": 100}
    return foods.with_columns(
        [pl.when((pl.col(c) < 0) | (pl.col(c) > lim)).then(None).otherwise(pl.col(c)).alias(c)
         for c, lim in limits.items()])


def main():
    p = params()["data"]
    PROCESSED.mkdir(parents=True, exist_ok=True)
    food_ids = (pl.scan_parquet(INTERIM / "recipes_raw.parquet")
                .with_columns(pl.col("RecipeId").cast(pl.Int64))
                .filter(food_filter()).select(pl.col("RecipeId").alias("recipe_id")))
    n_all = pl.scan_parquet(INTERIM / "recipes_raw.parquet").select(pl.len()).collect().item()
    n_food = food_ids.select(pl.len()).collect().item()
    print(f"dropped {n_all - n_food:,} non-food entries (cleaners, play dough, pet treats)")

    inter = build_interactions(food_ids, p)
    stats = inter.group_by("recipe_id").agg(pl.len().alias("n_ratings"),
                                             pl.col("rating").cast(pl.Float64).mean().round(3).alias("mean_rating"))
    recipes, flags = build_recipes(inter.select("recipe_id").unique(), stats, p)
    foods = build_foods()

    recipes.write_parquet(PROCESSED / "recipes.parquet")
    inter.write_parquet(PROCESSED / "interactions.parquet")
    foods.write_parquet(PROCESSED / "foods.parquet")
    flags.write_parquet(PROCESSED / "nutrition_flags.parquet")

    n_users, n_items = inter["user_id"].n_unique(), inter["recipe_id"].n_unique()
    summary = {
        "raw_recipes": n_all, "non_food_dropped": n_all - n_food,
        "recipes_in_catalogue": recipes.height,
        "recipes_with_ratings": int(recipes["in_cf_data"].sum()),
        "cold_start_indian_recipes": int((~recipes["in_cf_data"]).sum()),
        "interactions": inter.height, "users": n_users,
        "density": round(inter.height / (n_users * n_items), 5),
        "rating_share": {str(k): round(v, 3) for k, v in
                         inter["rating"].value_counts(normalize=True).sort("rating").iter_rows()},
        "nutrition_flagged_missing": int((recipes["nutrition_status"] != "listed").sum()),
        "vegetarian_recipes": int(recipes["is_vegetarian"].sum()),
        "vegan_recipes": int(recipes["is_vegan"].sum()),
        "foods_indb": int(foods["food_id"].str.starts_with("INDB").sum()),
        "foods_usda": int(foods["food_id"].str.starts_with("USDA").sum()),
        "cuisine_counts": dict(recipes["cuisine"].value_counts(sort=True).iter_rows()),
        "meal_type_counts": dict(recipes["meal_type"].value_counts(sort=True).iter_rows()),
    }
    (PROCESSED / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
