"""Nutrition analytics from the meal logs. All sums are done in SQL or Python."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from nutrimate_core.nutrition import macro_energy_split

from .. import db
from ..deps import current_user
from ..services.users import get_profile, targets

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
KEYS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]


@router.get("")
def dashboard(days: int = Query(14, ge=7, le=90), user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    today = date.today()
    start = today - timedelta(days=days - 1)
    profile = get_profile(t, user["id"])
    tg = targets(profile)
    rows = t.all(f"""SELECT log_date, {', '.join(f'SUM({k}) AS {k}' for k in KEYS)}, COUNT(*) AS entries
                     FROM meal_logs WHERE user_id = %s AND log_date BETWEEN %s AND %s
                     GROUP BY log_date ORDER BY log_date""", (user["id"], start, today))
    by_day = {r["log_date"]: r for r in rows}
    series = []
    for n in range(days):
        d = start + timedelta(days=n)
        r = by_day.get(d)
        series.append({"date": d.isoformat(), **{k: (round(r[k] or 0, 1) if r else 0) for k in KEYS},
                       "logged": bool(r)})
    logged = [s for s in series if s["logged"]]
    avg = {k: (round(sum(s[k] for s in logged) / len(logged), 1) if logged else None) for k in KEYS}
    today_row = series[-1]
    within = None
    if tg["calories_kcal"] and logged:
        within = sum(abs(s["calories_kcal"] - tg["calories_kcal"]) <= 0.1 * tg["calories_kcal"] for s in logged)
    slots = t.all("""SELECT slot, SUM(calories_kcal) AS kcal FROM meal_logs
                     WHERE user_id = %s AND log_date BETWEEN %s AND %s GROUP BY slot""", (user["id"], start, today))
    top = t.all("""SELECT item_name, item_type, COUNT(*) AS times, SUM(calories_kcal) AS kcal FROM meal_logs
                   WHERE user_id = %s AND log_date BETWEEN %s AND %s GROUP BY item_name, item_type
                   ORDER BY times DESC, kcal DESC LIMIT 5""", (user["id"], start, today))
    counts = t.one("""SELECT (SELECT COUNT(*) FROM meal_plans WHERE user_id = %s) AS plans,
                             (SELECT COUNT(DISTINCT item_id) FROM interactions WHERE user_id = %s AND action = 'like') AS likes,
                             (SELECT COUNT(*) FROM chat_messages WHERE user_id = %s AND role = 'user') AS questions""",
                   (user["id"], user["id"], user["id"]))
    streak = 0
    for s in reversed(series):
        if not s["logged"]:
            if s["date"] == today.isoformat():
                continue
            break
        streak += 1
    return {
        "range": {"start": start.isoformat(), "end": today.isoformat(), "days": days},
        "targets": tg, "today": today_row,
        "today_percent": {k: (round(100 * today_row[k] / tg[k], 1) if tg[k] else None) for k in KEYS},
        "series": series, "averages": avg, "days_logged": len(logged), "days_within_10pct": within,
        "energy_split": macro_energy_split(avg["protein_g"], avg["carbs_g"], avg["fat_g"]) if logged else None,
        "by_slot": [{"slot": r["slot"], "kcal": round(r["kcal"] or 0, 1)} for r in slots],
        "top_items": top, "counts": counts, "streak_days": streak,
    }
