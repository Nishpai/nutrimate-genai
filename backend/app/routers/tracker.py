"""Meal logging. Nutrition for a log entry is computed from MySQL at the time of logging."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nutrimate_core.nutrition import scale

from .. import db
from ..deps import current_user

router = APIRouter(prefix="/api/logs", tags=["tracker"])
KEYS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]


class LogIn(BaseModel):
    log_date: date | None = None
    slot: Literal["breakfast", "lunch", "dinner", "snack"]
    item_type: Literal["recipe", "food"]
    item_id: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0, le=5000)
    unit: Literal["serving", "g"]


def compute_entry(t: db.Tx, body: LogIn) -> tuple[str, dict]:
    if body.item_type == "recipe":
        if body.unit != "serving" or not body.item_id.isdigit():
            raise HTTPException(422, "Recipes are logged in servings")
        r = t.one("SELECT name, calories_kcal, protein_g, carbs_g, fat_g, fiber_g FROM recipes WHERE recipe_id = %s",
                  (int(body.item_id),))
        if r is None:
            raise HTTPException(404, "Recipe not found")
        return r["name"], scale(r, body.quantity, KEYS)
    f = t.one("SELECT * FROM foods WHERE food_id = %s", (body.item_id,))
    if f is None:
        raise HTTPException(404, "Food not found")
    if body.unit == "g":
        per100 = {"calories_kcal": f["kcal_100g"], "protein_g": f["protein_100g"], "carbs_g": f["carbs_100g"],
                  "fat_g": f["fat_100g"], "fiber_g": f["fiber_100g"]}
        return f["name"], scale(per100, body.quantity / 100, KEYS)
    if f["kcal_serving"] is None:
        raise HTTPException(422, "This food has no serving size in the database; log it in grams")
    serving = {"calories_kcal": f["kcal_serving"], "protein_g": f["protein_serving"], "carbs_g": f["carbs_serving"],
               "fat_g": f["fat_serving"], "fiber_g": f["fiber_serving"]}
    return f["name"], scale(serving, body.quantity, KEYS)


@router.post("", status_code=201)
def add_log(body: LogIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    name, nut = compute_entry(t, body)
    nut = {k: (None if v is None else round(v, 1)) for k, v in nut.items()}
    lid = t.run("""INSERT INTO meal_logs (user_id, log_date, slot, item_type, item_id, item_name, quantity, unit,
                   calories_kcal, protein_g, carbs_g, fat_g, fiber_g) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user["id"], body.log_date or date.today(), body.slot, body.item_type, body.item_id, name,
                 body.quantity, body.unit, *[nut[k] for k in KEYS]))
    return t.one("SELECT * FROM meal_logs WHERE id = %s", (lid,))


@router.get("")
def list_logs(day: date | None = None, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    day = day or date.today()
    rows = t.all("SELECT * FROM meal_logs WHERE user_id = %s AND log_date = %s ORDER BY FIELD(slot,"
                 "'breakfast','lunch','snack','dinner'), id", (user["id"], day))
    totals = {k: round(sum(r[k] or 0 for r in rows), 1) for k in KEYS}
    unknown = [r["item_name"] for r in rows if any(r[k] is None for k in KEYS)]
    return {"date": day.isoformat(), "items": rows, "totals": totals, "items_with_unknown_values": unknown}


@router.delete("/{log_id}")
def delete_log(log_id: int, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if not t.run("DELETE FROM meal_logs WHERE id = %s AND user_id = %s", (log_id, user["id"])):
        raise HTTPException(404, "Log entry not found")
    return {"ok": True}
