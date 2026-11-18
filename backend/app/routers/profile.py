from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nutrimate_core import targets as tg
from nutrimate_core.constraints import ALLERGEN_GROUPS
from nutrimate_core.parser import CUISINES

from .. import db
from ..deps import current_user
from ..services.users import get_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileIn(BaseModel):
    sex: Literal["male", "female"] | None = None
    age: int | None = Field(None, ge=13, le=100)
    height_cm: float | None = Field(None, ge=100, le=250)
    weight_kg: float | None = Field(None, ge=25, le=300)
    activity: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = None
    goal: Literal["lose", "maintain", "gain"] | None = None
    diet: Literal["any", "eggetarian", "vegetarian", "vegan"] = "any"
    allergies: list[str] = Field(default_factory=list, max_length=12)
    restrictions: list[str] = Field(default_factory=list, max_length=30)
    cuisines: list[str] = Field(default_factory=list, max_length=10)
    calorie_target: int | None = Field(None, ge=1000, le=5000)
    protein_target_g: int | None = Field(None, ge=20, le=400)
    carbs_target_g: int | None = Field(None, ge=0, le=800)
    fat_target_g: int | None = Field(None, ge=10, le=300)
    fiber_target_g: int | None = Field(None, ge=5, le=100)
    meals_per_day: int = Field(3, ge=3, le=4)
    max_minutes: int | None = Field(None, ge=5, le=600)


class EstimateIn(BaseModel):
    sex: Literal["male", "female"]
    age: int = Field(ge=13, le=100)
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=25, le=300)
    activity: Literal["sedentary", "light", "moderate", "active", "very_active"]
    goal: Literal["lose", "maintain", "gain"]


def _clean_list(values: list[str]) -> list[str]:
    out = []
    for v in values:
        v = v.strip().lower()
        if 2 <= len(v) <= 40 and v not in out:
            out.append(v)
    return out


@router.get("/options")
def options():
    return {"allergens": sorted(ALLERGEN_GROUPS), "cuisines": CUISINES,
            "diets": ["any", "eggetarian", "vegetarian", "vegan"],
            "activity": list(tg.ACTIVITY_FACTORS), "goals": list(tg.GOAL_ADJUST)}


@router.get("")
def read_profile(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    return {"profile": get_profile(t, user["id"]), "onboarded": bool(user["onboarded"])}


@router.post("/estimate")
def estimate(body: EstimateIn):
    return tg.estimate(body.sex, body.age, body.height_cm, body.weight_kg, body.activity, body.goal)


def save_profile(t: db.Tx, user_id: int, body: ProfileIn) -> dict:
    data = body.model_dump()
    data["allergies"] = _clean_list(data["allergies"])
    data["restrictions"] = _clean_list(data["restrictions"])
    data["cuisines"] = [c for c in data["cuisines"] if c in CUISINES]
    cols = list(data)
    vals = [db.dumps(data[c]) if c in ("allergies", "restrictions", "cuisines") else data[c] for c in cols]
    updates = ", ".join(f"{c} = VALUES({c})" for c in cols)
    t.run(f"INSERT INTO profiles (user_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) "
          f"ON DUPLICATE KEY UPDATE {updates}", (user_id, *vals))
    t.run("INSERT INTO profile_history (user_id, snapshot) VALUES (%s, %s)", (user_id, db.dumps(data)))
    return get_profile(t, user_id)


@router.put("")
def update_profile(body: ProfileIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    return {"profile": save_profile(t, user["id"], body)}


@router.post("/onboarding")
def onboarding(body: ProfileIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if body.calorie_target is None and None not in (body.sex, body.age, body.height_cm, body.weight_kg,
                                                    body.activity, body.goal):
        est = tg.estimate(body.sex, body.age, body.height_cm, body.weight_kg, body.activity, body.goal)
        body.calorie_target = est["daily_kcal"]
        body.protein_target_g = body.protein_target_g or est["daily_protein_g"]
        body.carbs_target_g = body.carbs_target_g or est["daily_carbs_g"]
        body.fat_target_g = body.fat_target_g or est["daily_fat_g"]
    profile = save_profile(t, user["id"], body)
    t.run("UPDATE users SET onboarded = 1 WHERE id = %s", (user["id"],))
    return {"profile": profile, "onboarded": True}
