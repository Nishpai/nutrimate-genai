"""Daily target estimate with the Mifflin-St Jeor equation.

This is a rough starting point for a student project, not medical or dietetic advice.

    BMR (men)   = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    BMR (women) = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    TDEE        = BMR * activity factor
    goal        lose: TDEE - 500, maintain: TDEE, gain: TDEE + 300 (never below 1200 kcal)
    protein     1.6 g/kg when losing or gaining, 1.2 g/kg when maintaining
    fat         25% of calories (9 kcal/g), carbs are the rest (4 kcal/g)
"""

from __future__ import annotations

ACTIVITY_FACTORS = {
    "sedentary": 1.2,     # little or no exercise
    "light": 1.375,       # 1 to 3 days a week
    "moderate": 1.55,     # 3 to 5 days a week
    "active": 1.725,      # 6 to 7 days a week
    "very_active": 1.9,   # hard training or a physical job
}
GOAL_ADJUST = {"lose": -500, "maintain": 0, "gain": 300}
PROTEIN_PER_KG = {"lose": 1.6, "maintain": 1.2, "gain": 1.6}
MIN_KCAL = 1200


def estimate(sex: str, age: int, height_cm: float, weight_kg: float, activity: str, goal: str) -> dict:
    if sex not in ("male", "female"):
        raise ValueError("sex must be male or female for this equation")
    if activity not in ACTIVITY_FACTORS:
        raise ValueError(f"activity must be one of {sorted(ACTIVITY_FACTORS)}")
    if goal not in GOAL_ADJUST:
        raise ValueError(f"goal must be one of {sorted(GOAL_ADJUST)}")
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)
    tdee = bmr * ACTIVITY_FACTORS[activity]
    kcal = max(MIN_KCAL, tdee + GOAL_ADJUST[goal])
    protein = PROTEIN_PER_KG[goal] * weight_kg
    fat = 0.25 * kcal / 9
    carbs = max(0.0, (kcal - protein * 4 - fat * 9) / 4)
    return {
        "bmr": round(bmr), "tdee": round(tdee),
        "daily_kcal": round(kcal), "daily_protein_g": round(protein),
        "daily_carbs_g": round(carbs), "daily_fat_g": round(fat),
        "method": "Mifflin-St Jeor estimate",
        "note": "A rough estimate to start from, not medical advice.",
    }
