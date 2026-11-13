"""PLM2 sandbox (Christoph 2026-11-10): a second PLM2 instance where Project
Management and Sales try the change Offer and Timing pages and send feedback.

Only active with SANDBOX_MODE=true. Each person works on their OWN database,
cloned from a fixed snapshot (SANDBOX_TEMPLATE_DB) the first time they open the
sandbox; "Reset my copy" drops it and clones it again. Nothing in a copy is
real: the sandbox runs with mail and the background jobs off (main.py).

How a request finds its database: the ASGI middleware reads the shared
AdminPanel cookie, refuses anyone who is not plm2_Admin / Project Management /
Sales, makes sure the person's database exists and sets a context variable.
Every session (get_db and direct AsyncSessionLocal() alike) binds through
RoutingSession.get_bind, which reads that variable. Feedback is kept in its
own small database (SANDBOX_META_DB) so a reset never loses it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextvars import ContextVar
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

current_db: ContextVar[Optional[str]] = ContextVar("sandbox_db", default=None)
_engines: dict[str, AsyncEngine] = {}
_locks: dict[str, asyncio.Lock] = {}
_default_engine: Optional[AsyncEngine] = None


def enabled() -> bool:
    return bool(get_settings().sandbox_mode)


def set_default_engine(engine: AsyncEngine) -> None:
    global _default_engine
    _default_engine = engine


def db_name_for(username: str) -> str:
    """Postgres database name of one person's copy: plm_sbx_<username>."""
    slug = re.sub(r"[^a-z0-9]+", "_", username.lower()).strip("_")[:40] or "user"
    return f"plm_sbx_{slug}"


def _url_for(db: str):
    return make_url(get_settings().database_url).set(database=db)


def _engine_for(db: str) -> AsyncEngine:
    eng = _engines.get(db)
    if eng is None:
        eng = create_async_engine(_url_for(db), pool_size=3, max_overflow=5,
                                  pool_recycle=1800)
        _engines[db] = eng
    return eng


class RoutingSession(Session):
    """Binds every statement to the current person's database."""

    def get_bind(self, mapper=None, clause=None, **kw):
        db = current_db.get()
        if db is None:
            return _default_engine.sync_engine
        return _engine_for(db).sync_engine


# ----------------------------------------------------------------------
# Database copies
# ----------------------------------------------------------------------
async def _admin_conn() -> asyncpg.Connection:
    url = _url_for("postgres")
    return await asyncpg.connect(user=url.username, password=url.password,
                                 host=url.host, port=url.port or 5432,
                                 database="postgres")


async def _exists(conn, db: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from pg_database where datname = $1", db))


async def _clone(conn, db: str) -> None:
    template = get_settings().sandbox_template_db
    await conn.execute(f'CREATE DATABASE "{db}" TEMPLATE "{template}"')


async def ensure_copy(db: str) -> None:
    if db in _engines:
        return
    lock = _locks.setdefault(db, asyncio.Lock())
    async with lock:
        if db in _engines:
            return
        conn = await _admin_conn()
        try:
            if not await _exists(conn, db):
                logger.info("Sandbox: new copy %s", db)
                await _clone(conn, db)
        finally:
            await conn.close()
        _engine_for(db)


async def reset_copy(db: str) -> None:
    lock = _locks.setdefault(db, asyncio.Lock())
    async with lock:
        eng = _engines.pop(db, None)
        if eng is not None:
            await eng.dispose()
        conn = await _admin_conn()
        try:
            await conn.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = $1 and pid <> pg_backend_pid()", db)
            await conn.execute(f'DROP DATABASE IF EXISTS "{db}"')
            await _clone(conn, db)
        finally:
            await conn.close()
        _engine_for(db)
        logger.info("Sandbox: reset %s", db)


# ----------------------------------------------------------------------
# Feedback store (survives resets)
# ----------------------------------------------------------------------
_FEEDBACK_DDL = """
create table if not exists sandbox_feedback (
    id serial primary key,
    created_at timestamptz not null default now(),
    username text not null,
    page text,
    tab text,
    text text not null
)"""


async def _meta_conn() -> asyncpg.Connection:
    meta = get_settings().sandbox_meta_db
    url = _url_for(meta)
    kw = dict(user=url.username, password=url.password, host=url.host,
              port=url.port or 5432)
    try:
        conn = await asyncpg.connect(database=meta, **kw)
    except asyncpg.InvalidCatalogNameError:
        admin = await _admin_conn()
        try:
            await admin.execute(f'CREATE DATABASE "{meta}"')
        finally:
            await admin.close()
        conn = await asyncpg.connect(database=meta, **kw)
    await conn.execute(_FEEDBACK_DDL)
    return conn


# ----------------------------------------------------------------------
# Who may use it
# ----------------------------------------------------------------------
def _identity(cookie: Optional[str]) -> tuple[Optional[str], list[str]]:
    """(username, plm2 hub roles) from the shared cookie, (None, []) if none."""
    s = get_settings()
    if not cookie:
        return None, []
    try:
        payload = jwt.decode(cookie, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None, []
    roles = [r.get("name") for r in payload.get("roles", [])
             if isinstance(r, dict) and r.get("system") == s.role_system]
    return payload.get("email") or payload.get("username"), roles


def allowed(roles: list[str]) -> bool:
    if "plm2_Admin" in roles or get_settings().sandbox_open:
        return True
    wanted = {r.strip() for r in get_settings().sandbox_hub_roles.split(",") if r.strip()}
    return bool(wanted & set(roles))


def widen_roles(roles: list[str]) -> list[str]:
    """Sandbox users get every sandbox_hub_roles department (PM + Sales);
    plm2_Admin stays as it is."""
    if "plm2_Admin" in roles or not allowed(roles):
        return roles
    if get_settings().sandbox_open:
        # Open sandbox: full rights for everyone, in their own copy only.
        return roles + ["plm2_Admin"]
    wanted = [r.strip() for r in get_settings().sandbox_hub_roles.split(",") if r.strip()]
    return roles + [r for r in wanted if r not in roles]


async def _send_json(send, status: int, body: dict) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})


class SandboxMiddleware:
    """Routes /api requests to the caller's own copy; refuses everyone else."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        from starlette.requests import Request as _Req
        req = _Req(scope)
        if (req.headers.get("authorization") or "").startswith("Bearer "):
            return await _send_json(send, 403, {"detail": "No service tokens in the sandbox"})
        username, roles = _identity(req.cookies.get(get_settings().jwt_cookie_name))
        if username is None:
            return await _send_json(send, 401, {"detail": "Not logged in"})
        if not allowed(roles):
            return await _send_json(send, 403, {
                "detail": "The PLM2 sandbox is open to Project Management and Sales only",
                "sandbox_denied": True})
        db = db_name_for(username)
        try:
            await ensure_copy(db)
        except Exception:
            logger.exception("Sandbox copy %s not ready", db)
            return await _send_json(send, 503, {"detail": "Your sandbox copy could not be prepared"})
        scope.setdefault("state", {})["sandbox_user"] = username
        token = current_db.set(db)
        try:
            await self.app(scope, receive, send)
        finally:
            current_db.reset(token)


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
router = APIRouter(prefix="/sandbox", tags=["sandbox"])


def _user(request: Request) -> str:
    u = request.scope.get("state", {}).get("sandbox_user")
    if not u:
        raise HTTPException(401, "Not logged in")
    return u


@router.get("/info")
async def info(request: Request):
    s = get_settings()
    return {"sandbox": True, "username": _user(request),
            "landing": s.sandbox_landing}


@router.post("/reset")
async def reset(request: Request):
    db = db_name_for(_user(request))
    await reset_copy(db)
    return {"reset": True}


class FeedbackIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    page: Optional[str] = Field(default=None, max_length=500)
    tab: Optional[str] = Field(default=None, max_length=50)


@router.post("/feedback")
async def post_feedback(body: FeedbackIn, request: Request):
    conn = await _meta_conn()
    try:
        fid = await conn.fetchval(
            "insert into sandbox_feedback (username, page, tab, text) "
            "values ($1, $2, $3, $4) returning id",
            _user(request), body.page, body.tab, body.text.strip())
    finally:
        await conn.close()
    return {"id": fid}


@router.get("/feedback")
async def list_feedback(request: Request, mine: bool = True):
    """Your own notes; plm2_Admin may read everyone's with mine=false."""
    user = _user(request)
    _, roles = _identity(request.cookies.get(get_settings().jwt_cookie_name))
    conn = await _meta_conn()
    try:
        if mine or "plm2_Admin" not in roles:
            rows = await conn.fetch(
                "select * from sandbox_feedback where username = $1 order by id desc", user)
        else:
            rows = await conn.fetch("select * from sandbox_feedback order by id desc")
    finally:
        await conn.close()
    return [dict(r) for r in rows]
