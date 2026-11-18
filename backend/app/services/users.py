"""Profile, preference and constraint helpers shared by the routers."""

from __future__ import annotations

from nutrimate_core import constraints as cons

from .. import db
from .engine import UserState

SLOT_SHARES = {
    3: [("breakfast", 0.25), ("lunch", 0.375), ("dinner", 0.375)],
    4: [("breakfast", 0.25), ("lunch", 0.35), ("snack", 0.10), ("dinner", 0.30)],
}
DEFAULT_FIBER = 30


def get_profile(t: db.Tx, user_id: int) -> dict:
    p = t.one("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
    if p is None:
        return {"user_id": user_id, "sex": None, "age": None, "height_cm": None, "weight_kg": None,
                "activity": None, "goal": None, "diet": "any", "allergies": [], "restrictions": [],
                "cuisines": [], "calorie_target": None, "protein_target_g": None, "carbs_target_g": None,
                "fat_target_g": None, "fiber_target_g": None, "meals_per_day": 3, "max_minutes": None}
    for k in ("allergies", "restrictions", "cuisines"):
        p[k] = db.loads(p[k]) or []
    p.pop("updated_at", None)
    return p


def targets(profile: dict) -> dict:
    return {
        "calories_kcal": profile.get("calorie_target"),
        "protein_g": profile.get("protein_target_g"),
        "carbs_g": profile.get("carbs_target_g"),
        "fat_g": profile.get("fat_target_g"),
        "fiber_g": profile.get("fiber_target_g") or DEFAULT_FIBER,
    }


def base_constraints(profile: dict) -> cons.Constraints:
    """Rules that always apply for this user: diet, allergies, restrictions, time limit."""
    exclude = list(dict.fromkeys([*profile.get("allergies", []), *profile.get("restrictions", [])]))
    return cons.Constraints(diet=profile.get("diet") or "any", exclude=exclude,
                            max_minutes=profile.get("max_minutes"))


def per_meal_kcal(profile: dict) -> float | None:
    kcal = profile.get("calorie_target")
    if not kcal:
        return None
    return round(kcal / max(profile.get("meals_per_day") or 3, 1))


def preferences(t: db.Tx, user_id: int) -> dict:
    """Latest like or dislike per recipe (a later action replaces an earlier one)."""
    rows = t.all(
        """SELECT i.item_id, i.action FROM interactions i
           JOIN (SELECT item_id, MAX(id) AS last_id FROM interactions
                 WHERE user_id = %s AND item_type = 'recipe' AND action IN ('like','dislike','clear')
                 GROUP BY item_id) x ON x.last_id = i.id""", (user_id,))
    liked = [int(r["item_id"]) for r in rows if r["action"] == "like"]
    disliked = [int(r["item_id"]) for r in rows if r["action"] == "dislike"]
    saved_rows = t.all(
        """SELECT i.item_id, i.action FROM interactions i
           JOIN (SELECT item_id, MAX(id) AS last_id FROM interactions
                 WHERE user_id = %s AND item_type = 'recipe' AND action IN ('save','unsave')
                 GROUP BY item_id) x ON x.last_id = i.id""", (user_id,))
    saved = [int(r["item_id"]) for r in saved_rows if r["action"] == "save"]
    return {"liked": liked, "disliked": disliked, "saved": saved}


def user_state(t: db.Tx, user_id: int, profile: dict | None = None) -> UserState:
    profile = profile or get_profile(t, user_id)
    prefs = preferences(t, user_id)
    return UserState(liked=prefs["liked"], disliked=prefs["disliked"], cuisines=profile.get("cuisines", []),
                     goal=profile.get("goal"), per_meal_kcal=per_meal_kcal(profile))
