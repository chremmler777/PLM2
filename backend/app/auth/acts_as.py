"""Acts-as request context.

The auth dependency puts the acting identity here so the audit layer can write
both identities without every service threading an actor through its signature.
A ContextVar is per-asyncio-task, so it cannot bleed between concurrent
requests, and it is reset at the end of the request that set it.

Spec: docs/superpowers/specs/2026-07-22-acts-as-role-switch-design.md (D5).
"""
from contextvars import ContextVar
from typing import Optional

HEADER = "X-Acts-As-Department"

# (real_user_id, acting_as_department_id) while a request runs under acts-as.
_acts_as: ContextVar[Optional[tuple[int, int]]] = ContextVar("acts_as", default=None)


def set_acts_as(real_user_id: int, department_id: int):
    """Returns the token to reset with once the request is done."""
    return _acts_as.set((real_user_id, department_id))


def reset_acts_as(token) -> None:
    _acts_as.reset(token)


def current_acts_as() -> Optional[tuple[int, int]]:
    return _acts_as.get()
