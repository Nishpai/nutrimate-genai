from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..deps import current_user
from ..rag import llm
from ..services import planner
from ..services.users import base_constraints, get_profile, user_state
from .recommend import require_engine

router = APIRouter(prefix="/api/planner", tags=["planner"])


class GenerateIn(BaseModel):
    days: int = Field(1, ge=1, le=7)
    start_date: date | None = None
    calorie_target: int | None = Field(None, ge=1000, le=5000)
    protein_target_g: int | None = Field(None, ge=20, le=400)
    meals_per_day: int | None = Field(None, ge=3, le=4)
    with_narrative: bool = True


class SwapIn(BaseModel):
    plan: dict
    day_index: int = Field(ge=0, le=6)
    slot: str


class SaveIn(BaseModel):
    plan: dict
    name: str = Field("My meal plan", min_length=1, max_length=120)


def _targets(profile, body_kcal=None, body_protein=None):
    kcal = body_kcal or profile.get("calorie_target")
    if not kcal:
        raise HTTPException(400, "Set a daily calorie target in Settings (or pass one) before planning")
    return float(kcal), float(body_protein or profile.get("protein_target_g") or 0) or None


def narrative(plan: dict) -> tuple[str, str, dict]:
    s = plan["summary"]
    facts = {"summary": s, "rules": plan.get("rules", []), "days": [
        {"date": d["date"], "total_kcal": d["totals"]["calories_kcal"], "total_protein_g": d["totals"]["protein_g"],
         "meals": [{"slot": m["slot"], "name": m["recipe"]["name"], "servings": m["servings"],
                    "kcal": m["nutrition"]["calories_kcal"]} for m in d["meals"]]} for d in plan["days"]]}
    template = (f"This {s['days']}-day plan averages {s['avg_kcal']:g} kcal and {s['avg_protein_g']:g} g protein a day "
                f"against your {s['target_kcal']:g} kcal target. {s['days_within_10pct']} of {s['days']} days are within "
                f"10% of the calorie target. Portions were adjusted in quarter servings to get close to the target.")
    if plan.get("rules"):
        template += " Every recipe passes your rules: " + ", ".join(plan["rules"]) + "."
    if not llm.gemini_available():
        return template, "template", {"reason": "No GEMINI_API_KEY set"}
    try:
        text, model = llm.write("Describe my meal plan.", facts,
                                "Write a short, encouraging overview of this meal plan (at most 90 words). "
                                "Mention how it meets the calorie target and one or two highlights.")
        check = llm.validate_numbers(text, facts, "")
        if check["ok"]:
            return text, "gemini", {"model": model, **check}
        return template, "template", {"reason": "Gemini used a number not in the plan", **check}
    except Exception as exc:
        return template, "template", {"reason": str(exc)}


@router.post("/generate")
def generate(body: GenerateIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    require_engine()
    profile = get_profile(t, user["id"])
    kcal, protein = _targets(profile, body.calorie_target, body.protein_target_g)
    c = base_constraints(profile)
    plan = planner.generate(user_state(t, user["id"], profile), c, kcal, protein, body.days,
                            body.meals_per_day or profile.get("meals_per_day") or 3, body.start_date)
    if plan.get("error"):
        raise HTTPException(422, plan["error"])
    if body.with_narrative:
        plan["narrative"], plan["narrative_mode"], plan["narrative_check"] = narrative(plan)
    else:
        plan["narrative"], plan["narrative_mode"] = None, "none"
    return plan


@router.post("/swap")
def swap(body: SwapIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    require_engine()
    profile = get_profile(t, user["id"])
    kcal, protein = _targets(profile, body.plan.get("summary", {}).get("target_kcal"),
                             body.plan.get("summary", {}).get("target_protein_g"))
    c = base_constraints(profile)
    try:
        plan = planner.rebuild_from_db(body.plan, t, c)
        if body.day_index >= len(plan["days"]):
            raise ValueError("day out of range")
        plan = planner.swap(plan, body.day_index, body.slot, user_state(t, user["id"], profile), c, kcal, protein)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    return plan


@router.post("/save", status_code=201)
def save(body: SaveIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    require_engine()
    profile = get_profile(t, user["id"])
    c = base_constraints(profile)
    try:
        plan = planner.rebuild_from_db(body.plan, t, c)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    s = plan.get("summary", {})
    kcal, protein = _targets(profile, s.get("target_kcal"), s.get("target_protein_g"))
    plan["summary"] = planner.summarise(plan["days"], kcal, protein)
    pid = t.run("""INSERT INTO meal_plans (user_id, name, start_date, days, targets, summary, narrative, narrative_mode)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user["id"], body.name.strip(), plan["days"][0]["date"], len(plan["days"]),
                 db.dumps({"calories_kcal": kcal, "protein_g": protein}), db.dumps(plan["summary"]),
                 plan.get("narrative"), plan.get("narrative_mode") or "template"))
    t.many("""INSERT INTO meal_plan_items (plan_id, day_index, slot, recipe_id, servings, nutrition)
              VALUES (%s,%s,%s,%s,%s,%s)""",
           [(pid, d["day_index"], m["slot"], m["recipe"]["recipe_id"], m["servings"], db.dumps(m["nutrition"]))
            for d in plan["days"] for m in d["meals"]])
    return {"id": pid}


def load_plan(t: db.Tx, user_id: int, plan_id: int) -> dict:
    p = t.one("SELECT * FROM meal_plans WHERE id = %s AND user_id = %s", (plan_id, user_id))
    if p is None:
        raise HTTPException(404, "Plan not found")
    items = t.all("""SELECT i.*, r.name, r.cuisine, r.meal_type, r.total_minutes FROM meal_plan_items i
                     JOIN recipes r ON r.recipe_id = i.recipe_id WHERE i.plan_id = %s ORDER BY day_index, id""",
                  (plan_id,))
    days = {}
    for it in items:
        days.setdefault(it["day_index"], []).append({
            "slot": it["slot"], "servings": it["servings"], "nutrition": db.loads(it["nutrition"]),
            "recipe": {"recipe_id": it["recipe_id"], "name": it["name"], "cuisine": it["cuisine"],
                       "meal_type": it["meal_type"], "total_minutes": it["total_minutes"]}})
    start = p["start_date"]
    from datetime import timedelta
    plan_days = [{"day_index": d, "date": (start + timedelta(days=d)).isoformat(), "meals": ms,
                  "totals": planner.day_totals(ms)} for d, ms in sorted(days.items())]
    return {"id": p["id"], "name": p["name"], "start_date": start.isoformat(), "days": plan_days,
            "summary": db.loads(p["summary"]), "targets": db.loads(p["targets"]), "narrative": p["narrative"],
            "narrative_mode": p["narrative_mode"], "created_at": p["created_at"]}


@router.get("/plans")
def list_plans(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    rows = t.all("SELECT id, name, start_date, days, summary, narrative_mode, created_at FROM meal_plans "
                 "WHERE user_id = %s ORDER BY created_at DESC, id DESC", (user["id"],))
    for r in rows:
        r["summary"] = db.loads(r["summary"])
    return rows


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    return load_plan(t, user["id"], plan_id)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if not t.run("DELETE FROM meal_plans WHERE id = %s AND user_id = %s", (plan_id, user["id"])):
        raise HTTPException(404, "Plan not found")
    return {"ok": True}


class LogDayIn(BaseModel):
    day_index: int = Field(ge=0, le=6)
    log_date: date | None = None


@router.post("/plans/{plan_id}/log")
def log_day(plan_id: int, body: LogDayIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    plan = load_plan(t, user["id"], plan_id)
    day = next((d for d in plan["days"] if d["day_index"] == body.day_index), None)
    if day is None:
        raise HTTPException(404, "Day not in plan")
    when = body.log_date or date.today()
    rows = [(user["id"], when, m["slot"], "recipe", str(m["recipe"]["recipe_id"]), m["recipe"]["name"],
             m["servings"], "serving", *[m["nutrition"].get(k) for k in planner.KEYS]) for m in day["meals"]]
    t.many("""INSERT INTO meal_logs (user_id, log_date, slot, item_type, item_id, item_name, quantity, unit,
              calories_kcal, protein_g, carbs_g, fat_g, fiber_g) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
           rows)
    return {"logged": len(rows), "date": when.isoformat()}
