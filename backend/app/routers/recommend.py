from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nutrimate_core import constraints as cons

from .. import db
from ..deps import current_user
from ..services.engine import engine
from ..services.users import base_constraints, get_profile, preferences, user_state

router = APIRouter(prefix="/api", tags=["recommendations"])


class RecommendIn(BaseModel):
    meal_type: str | None = None
    cuisine: str | None = None
    max_calories: float | None = Field(None, ge=50, le=3000)
    min_protein_g: float | None = Field(None, ge=0, le=200)
    max_minutes: float | None = Field(None, ge=1, le=1440)
    extra_exclude: list[str] = Field(default_factory=list, max_length=10)
    k: int = Field(12, ge=1, le=50)


class FeedbackIn(BaseModel):
    recipe_id: int
    action: Literal["like", "dislike", "save", "unsave", "clear", "view"]


def require_engine():
    if not engine.ready:
        raise HTTPException(503, f"Recommendation models are not loaded: {engine.error or 'starting up'}")


def log_recommendations(t: db.Tx, user_id: int, source: str, context: dict, result: dict) -> int:
    log_id = t.run("INSERT INTO recommendation_logs (user_id, source, context, model_info) VALUES (%s,%s,%s,%s)",
                   (user_id, source, db.dumps(context),
                    db.dumps({"mode": result.get("mode"), "passed": result.get("passed")})))
    t.many("INSERT INTO recommendation_items (log_id, rank_pos, recipe_id, score) VALUES (%s,%s,%s,%s)",
           [(log_id, n + 1, it["recipe"]["recipe_id"], it["score"]) for n, it in enumerate(result["items"])])
    return log_id


@router.post("/recommendations")
def recommend(body: RecommendIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    require_engine()
    profile = get_profile(t, user["id"])
    base = base_constraints(profile)
    c = cons.Constraints(
        diet=base.diet, exclude=list(dict.fromkeys(base.exclude + [e.strip().lower() for e in body.extra_exclude
                                                                     if e.strip()])),
        max_calories=body.max_calories, min_protein_g=body.min_protein_g,
        max_minutes=body.max_minutes if body.max_minutes is not None else base.max_minutes,
        meal_type=body.meal_type or None, cuisine=body.cuisine or None, hard_cuisine=bool(body.cuisine),
    )
    state = user_state(t, user["id"], profile)
    result = engine.recommend(state, c, k=body.k)
    prefs = preferences(t, user["id"])
    for it in result["items"]:
        it["saved"] = it["recipe"]["recipe_id"] in prefs["saved"]
    context = {"constraints": c.describe(), "request": body.model_dump()}
    result["log_id"] = log_recommendations(t, user["id"], "recommendations", context, result)
    result["applied_rules"] = c.describe()
    result["liked_count"] = len(state.liked)
    return result


@router.post("/feedback")
def feedback(body: FeedbackIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if not t.one("SELECT recipe_id FROM recipes WHERE recipe_id = %s", (body.recipe_id,)):
        raise HTTPException(404, "Recipe not found")
    t.run("INSERT INTO interactions (user_id, item_type, item_id, action) VALUES (%s, 'recipe', %s, %s)",
          (user["id"], str(body.recipe_id), body.action))
    return {"ok": True, **preferences(t, user["id"])}


@router.get("/preferences")
def my_preferences(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    prefs = preferences(t, user["id"])
    ids = prefs["liked"] + prefs["disliked"] + prefs["saved"]
    names = {}
    if ids:
        ph = ", ".join(["%s"] * len(ids))
        for r in t.all(f"SELECT recipe_id, name FROM recipes WHERE recipe_id IN ({ph})", ids):
            names[r["recipe_id"]] = r["name"]
    return {k: [{"recipe_id": i, "name": names.get(i)} for i in v] for k, v in prefs.items()}
