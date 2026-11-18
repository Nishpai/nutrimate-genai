from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .. import db
from ..deps import current_user
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _public(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "full_name": u["full_name"], "role": u["role"],
            "onboarded": bool(u["onboarded"])}


@router.post("/register", status_code=201)
def register(body: RegisterIn, t: db.Tx = Depends(db.get_tx)):
    email = body.email.lower()
    if t.one("SELECT id FROM users WHERE email = %s", (email,)):
        raise HTTPException(409, "An account with this email already exists")
    uid = t.run("INSERT INTO users (email, password_hash, full_name) VALUES (%s, %s, %s)",
                (email, hash_password(body.password), body.full_name.strip()))
    t.run("INSERT INTO profiles (user_id, allergies, restrictions, cuisines) VALUES (%s, '[]', '[]', '[]')", (uid,))
    user = t.one("SELECT * FROM users WHERE id = %s", (uid,))
    return {"token": create_token(uid, user["role"]), "user": _public(user)}


@router.post("/login")
def login(body: LoginIn, t: db.Tx = Depends(db.get_tx)):
    user = t.one("SELECT * FROM users WHERE email = %s", (body.email.lower(),))
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token(user["id"], user["role"]), "user": _public(user)}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return _public(user)
