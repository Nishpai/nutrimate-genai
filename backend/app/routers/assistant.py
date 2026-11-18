from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..deps import current_user
from ..rag import agent, llm
from ..rag.retriever import retriever
from ..services.engine import engine
from ..services.users import get_profile

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskIn(BaseModel):
    message: str = Field(min_length=2, max_length=600)


@router.get("/status")
def status(user: dict = Depends(current_user)):
    return {"gemini": llm.gemini_available(), "retriever": retriever.ready, "engine": engine.ready,
            "documents": int(len(retriever.docs)) if retriever.ready else 0}


@router.post("/ask")
def ask(body: AskIn, user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    if not retriever.ready or not engine.ready:
        raise HTTPException(503, "The assistant is still loading its models. Try again in a few seconds.")
    profile = get_profile(t, user["id"])
    t.run("INSERT INTO chat_messages (user_id, role, content) VALUES (%s, 'user', %s)", (user["id"], body.message))
    out = agent.ask(t, user["id"], profile, body.message)
    meta = {k: out[k] for k in ("mode", "model", "intent", "validation", "steps", "cards")}
    out["id"] = t.run("INSERT INTO chat_messages (user_id, role, content, meta) VALUES (%s, 'assistant', %s, %s)",
                      (user["id"], out["answer"], db.dumps(meta)))
    return out


@router.delete("/history")
def clear(user: dict = Depends(current_user), t: db.Tx = Depends(db.get_tx)):
    t.run("DELETE FROM chat_messages WHERE user_id = %s", (user["id"],))
    return {"ok": True}
