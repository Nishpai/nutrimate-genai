"""Food explorer: search, filter, detail and side-by-side comparison. All values are read
from MySQL. Recipes are per serving; foods are per 100 g (INDB foods also per serving)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from nutrimate_core import constraints as cons
from nutrimate_core.nutrition import macro_energy_split

from .. import db
from ..deps import current_user
from ..rag.retriever import retriever
from ..services.engine import engine
from ..services.users import base_constraints, get_profile

router = APIRouter(prefix="/api", tags=["explorer"])

RECIPE_SORT = {"relevance": "n_ratings DESC", "protein": "protein_g IS NULL, protein_g DESC",
               "calories": "calories_kcal IS NULL, calories_kcal ASC", "rating": "mean_rating IS NULL, mean_rating DESC",
               "time": "total_minutes IS NULL, total_minutes ASC", "fiber": "fiber_g IS NULL, fiber_g DESC"}
FOOD_SORT = {"relevance": "name ASC", "protein": "protein_100g IS NULL, protein_100g DESC",
             "calories": "kcal_100g IS NULL, kcal_100g ASC", "fiber": "fiber_100g IS NULL, fiber_100g DESC"}
RECIPE_LIST_COLS = ("recipe_id, name, cuisine, meal_type, category, total_minutes, servings, calories_kcal, "
                    "protein_g, carbs_g, fat_g, fiber_g, is_vegetarian, is_vegan, is_eggetarian, allergens_found, "
                    "mean_rating, n_ratings, nutrition_status")


def _recipe_row(r: dict) -> dict:
    r = dict(r)
    for b in ("is_vegetarian", "is_vegan", "is_eggetarian", "in_cf_data"):
        if b in r:
            r[b] = bool(r[b])
    r["allergens"] = [a for a in (r.pop("allergens_found", "") or "").split("|") if a]
    return r


@router.get("/recipes")
def search_recipes(
    q: str = "", diet: Literal["any", "eggetarian", "vegetarian", "vegan"] = "any",
    cuisine: str | None = None, meal_type: str | None = None,
    max_calories: float | None = Query(None, ge=0), min_protein: float | None = Query(None, ge=0),
    max_minutes: float | None = Query(None, ge=0), sort: str = "relevance",
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    apply_profile: bool = False, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx),
):
    where, params = ["1=1"], []
    if q.strip():
        for word in q.strip().split()[:6]:
            where.append("(name LIKE %s OR ingredients LIKE %s)")
            params += [f"%{word}%", f"%{word}%"]
    if diet == "eggetarian":
        where.append("is_eggetarian = 1")
    elif diet == "vegetarian":
        where.append("is_vegetarian = 1")
    elif diet == "vegan":
        where.append("is_vegan = 1")
    for col, val in (("cuisine", cuisine), ("meal_type", meal_type)):
        if val:
            where.append(f"{col} = %s")
            params.append(val)
    if max_calories is not None:
        where.append("calories_kcal <= %s")
        params.append(max_calories)
    if min_protein is not None:
        where.append("protein_g >= %s")
        params.append(min_protein)
    if max_minutes is not None:
        where.append("total_minutes <= %s")
        params.append(max_minutes)
    order = RECIPE_SORT.get(sort, RECIPE_SORT["relevance"])
    rows = t.all(f"SELECT {RECIPE_LIST_COLS}, ingredients, instructions FROM recipes WHERE {' AND '.join(where)} "
                 f"ORDER BY {order}, recipe_id", params)
    if apply_profile:  # allergy and restriction rules from the profile, same engine as recommendations
        c = base_constraints(get_profile(t, user["id"]))
        rows = [r for r in rows if not cons.check_recipe(
            {**r, "search_text": cons.recipe_text(r["name"], r["ingredients"], r["instructions"])}, c)]
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]
    items = []
    for r in page_rows:
        r = {k: v for k, v in r.items() if k not in ("ingredients", "instructions")}
        items.append(_recipe_row(r))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/recipes/{recipe_id}")
def recipe_detail(recipe_id: int, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    r = t.one("SELECT * FROM recipes WHERE recipe_id = %s", (recipe_id,))
    if r is None:
        raise HTTPException(404, "Recipe not found")
    r = _recipe_row(r)
    r["ingredients"] = [i for i in (r["ingredients"] or "").split("|") if i]
    r["instructions"] = [s for s in (r["instructions"] or "").split("\n") if s.strip()]
    r["keywords"] = [k for k in (r["keywords"] or "").split("|") if k]
    r["energy_split"] = macro_energy_split(r["protein_g"], r["carbs_g"], r["fat_g"])
    profile = get_profile(t, user["id"])
    c = base_constraints(profile)
    r["profile_check"] = engine.check(recipe_id, c) if engine.ready else []
    t.run("INSERT INTO interactions (user_id, item_type, item_id, action) VALUES (%s, 'recipe', %s, 'view')",
          (user["id"], str(recipe_id)))
    return r


@router.get("/foods")
def search_foods(
    q: str = "", source: Literal["all", "indb", "usda", "imported"] = "all", group: str | None = None,
    max_calories: float | None = Query(None, ge=0), min_protein: float | None = Query(None, ge=0),
    sort: str = "relevance", page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx),
):
    where, params = ["1=1"], []
    if q.strip():
        for word in q.strip().split()[:6]:
            where.append("name LIKE %s")
            params.append(f"%{word}%")
    if source == "indb":
        where.append("food_id LIKE 'INDB:%%'")
    elif source == "usda":
        where.append("food_id LIKE 'USDA:%%'")
    elif source == "imported":
        where.append("dataset_id IS NOT NULL")
    if group:
        where.append("food_group = %s")
        params.append(group)
    if max_calories is not None:
        where.append("kcal_100g <= %s")
        params.append(max_calories)
    if min_protein is not None:
        where.append("protein_100g >= %s")
        params.append(min_protein)
    w = " AND ".join(where)
    total = t.one(f"SELECT COUNT(*) AS n FROM foods WHERE {w}", params)["n"]
    order = FOOD_SORT.get(sort, FOOD_SORT["relevance"])
    if sort == "relevance" and q.strip():
        order = "CHAR_LENGTH(name) ASC"
    rows = t.all(f"SELECT * FROM foods WHERE {w} ORDER BY {order}, food_id LIMIT %s OFFSET %s",
                 [*params, page_size, (page - 1) * page_size])
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


@router.get("/foods/groups")
def food_groups(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    return [r["food_group"] for r in t.all(
        "SELECT DISTINCT food_group FROM foods WHERE food_group IS NOT NULL ORDER BY food_group")]


@router.get("/foods/{food_id}")
def food_detail(food_id: str, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    r = t.one("SELECT * FROM foods WHERE food_id = %s", (food_id,))
    if r is None:
        raise HTTPException(404, "Food not found")
    r["energy_split"] = macro_energy_split(r["protein_100g"], r["carbs_100g"], r["fat_100g"])
    return r


@router.get("/compare")
def compare(items: str = Query(..., description="comma separated recipe:ID or food:ID, up to 4"),
            user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    out = []
    for token in [x.strip() for x in items.split(",") if x.strip()][:4]:
        kind, _, ident = token.partition(":")
        if kind == "recipe" and ident.isdigit():
            r = t.one("SELECT * FROM recipes WHERE recipe_id = %s", (int(ident),))
            if r:
                out.append({"type": "recipe", "id": str(r["recipe_id"]), "name": r["name"], "basis": "per serving",
                            "calories_kcal": r["calories_kcal"], "protein_g": r["protein_g"],
                            "carbs_g": r["carbs_g"], "fat_g": r["fat_g"], "fiber_g": r["fiber_g"],
                            "sugar_g": r["sugar_g"], "sodium_mg": r["sodium_mg"],
                            "energy_split": macro_energy_split(r["protein_g"], r["carbs_g"], r["fat_g"]),
                            "source": r["source"]})
        elif kind == "food":
            f = t.one("SELECT * FROM foods WHERE food_id = %s", (ident,))
            if f:
                out.append({"type": "food", "id": f["food_id"], "name": f["name"], "basis": "per 100 g",
                            "calories_kcal": f["kcal_100g"], "protein_g": f["protein_100g"],
                            "carbs_g": f["carbs_100g"], "fat_g": f["fat_100g"], "fiber_g": f["fiber_100g"],
                            "sugar_g": f["sugar_100g"], "sodium_mg": f["sodium_100g"],
                            "energy_split": macro_energy_split(f["protein_100g"], f["carbs_100g"], f["fat_100g"]),
                            "source": f["source"]})
    if not out:
        raise HTTPException(404, "None of those items were found")
    return {"items": out}


@router.get("/search/semantic")
def semantic_search(q: str = Query(..., min_length=2, max_length=200), k: int = Query(12, ge=1, le=50),
                    doc_type: Literal["all", "recipe", "food"] = "all",
                    user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if not retriever.ready:
        raise HTTPException(503, "The semantic index is not loaded")
    hits = retriever.search(q, k=k, doc_type=None if doc_type == "all" else doc_type)
    return {"items": hits}
