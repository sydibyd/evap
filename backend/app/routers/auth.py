from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize as S
from ..db import get_db
from ..models import User
from ..security import (ROLES, admin, any_user, create_access_token, hash_password,
                        verify_password)

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: str = Field(pattern="^(engineer|reviewer|admin)$")


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(engineer|reviewer|admin)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username))
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"token": create_access_token(u), "user": S.user(u)}


@router.get("/auth/me")
def me(user: User = Depends(any_user)):
    return S.user(user)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(admin)):
    return [S.user(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), _: User = Depends(admin)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    return S.user(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), me_: User = Depends(admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == me_.id and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(400, "You cannot demote or deactivate yourself")
    if body.role:
        u.role = body.role
    if body.active is not None:
        u.active = body.active
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    return S.user(u)


assert set(ROLES) == {"engineer", "reviewer", "admin"}
