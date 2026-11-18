from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import db
from ..deps import current_user

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/interactions")
def interactions(limit: int = Query(50, ge=1, le=500), user: dict = Depends(current_user),
                 t: db.Tx = Depends(db.get_tx)):
    return t.all("""SELECT i.id, i.item_type, i.item_id, i.action, i.created_at, r.name
                    FROM interactions i LEFT JOIN recipes r ON i.item_type = 'recipe' AND r.recipe_id = i.item_id
                    WHERE i.user_id = %s ORDER BY i.id DESC LIMIT %s""", (user["id"], limit))


@router.get("/recommendations")
def recommendations(limit: int = Query(20, ge=1, le=100), user: dict = Depends(current_user),
                    t: db.Tx = Depends(db.get_tx)):
    logs = t.all("SELECT * FROM recommendation_logs WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user["id"], limit))
    if not logs:
        return []
    ids = [lg["id"] for lg in logs]
    ph = ", ".join(["%s"] * len(ids))
    items = t.all(f"""SELECT ri.log_id, ri.rank_pos, ri.recipe_id, ri.score, r.name, r.calories_kcal, r.protein_g
                      FROM recommendation_items ri JOIN recipes r ON r.recipe_id = ri.recipe_id
                      WHERE ri.log_id IN ({ph}) ORDER BY ri.log_id, ri.rank_pos""", ids)
    by_log = {}
    for it in items:
        by_log.setdefault(it["log_id"], []).append(it)
    return [{"id": lg["id"], "source": lg["source"], "created_at": lg["created_at"],
             "context": db.loads(lg["context"]), "model_info": db.loads(lg["model_info"]),
             "items": by_log.get(lg["id"], [])} for lg in logs]


@router.get("/preferences")
def preference_changes(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    rows = t.all("SELECT id, snapshot, changed_at FROM profile_history WHERE user_id = %s ORDER BY id DESC LIMIT 50",
                 (user["id"],))
    return [{"id": r["id"], "changed_at": r["changed_at"], "snapshot": db.loads(r["snapshot"])} for r in rows]


@router.get("/chats")
def chats(limit: int = Query(100, ge=1, le=500), user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    rows = t.all("SELECT id, role, content, meta, created_at FROM chat_messages WHERE user_id = %s "
                 "ORDER BY id DESC LIMIT %s", (user["id"], limit))
    for r in rows:
        r["meta"] = db.loads(r["meta"])
    return list(reversed(rows))


@router.get("/logs")
def log_history(days: int = Query(30, ge=1, le=365), user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    return t.all("""SELECT log_date, COUNT(*) AS entries, SUM(calories_kcal) AS calories_kcal, SUM(protein_g) AS protein_g
                    FROM meal_logs WHERE user_id = %s AND log_date >= CURDATE() - INTERVAL %s DAY
                    GROUP BY log_date ORDER BY log_date DESC""", (user["id"], days))
