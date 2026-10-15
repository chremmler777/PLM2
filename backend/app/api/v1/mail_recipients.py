"""Part data mail list per project, and the mail status / test.

GET/POST/DELETE /v1/projects/{project_id}/mail-recipients
GET  /v1/notifications/mail-status
POST /v1/notifications/mail-test   (mails only the signed-in user)

Rights: Project Management members or admin (ProjectTeamService.user_can_manage,
the right that keeps the project team)."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import Plant, Project, User, get_db
from app.models.mail import LIST_PART_DATA, MAIL_LISTS, MailRecipient
from app.services import part_data_mail
from app.services.audit_service import AuditService
from app.services.project_team_service import ProjectTeamService

logger = logging.getLogger(__name__)

projects_router = APIRouter(prefix="/projects", tags=["projects"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


class RecipientCreate(BaseModel):
    email: str
    display_name: Optional[str] = None
    list_key: str = LIST_PART_DATA


class RecipientOut(BaseModel):
    id: int
    list_key: str
    email: str
    display_name: Optional[str]
    active: bool
    created_at: Optional[datetime]


def _out(r: MailRecipient) -> RecipientOut:
    return RecipientOut(id=r.id, list_key=r.list_key, email=r.email, display_name=r.display_name,
                        active=r.active, created_at=r.created_at)


async def _require_manager(db: AsyncSession, user: User) -> None:
    if not await ProjectTeamService.user_can_manage(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only Project Management or an admin may keep the mail list")


async def _project(db: AsyncSession, project_id: int, user: User) -> Project:
    project = (await db.execute(
        select(Project).join(Plant).where(
            (Project.id == project_id) & (Plant.organization_id == user.organization_id))
    )).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@projects_router.get("/{project_id}/mail-recipients", response_model=list[RecipientOut])
async def list_recipients(
    project_id: int,
    list_key: str = LIST_PART_DATA,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _project(db, project_id, current_user)
    await _require_manager(db, current_user)
    rows = (await db.execute(
        select(MailRecipient).where(MailRecipient.project_id == project_id,
                                    MailRecipient.list_key == list_key)
        .order_by(MailRecipient.email))).scalars().all()
    return [_out(r) for r in rows]


@projects_router.post("/{project_id}/mail-recipients", response_model=RecipientOut,
                      status_code=status.HTTP_201_CREATED)
async def add_recipient(
    project_id: int,
    body: RecipientCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _project(db, project_id, current_user)
    await _require_manager(db, current_user)
    if body.list_key not in MAIL_LISTS:
        raise HTTPException(422, f"Unknown list {body.list_key!r}")
    email = part_data_mail.clean_address(body.email)
    if not part_data_mail.valid_address(email):
        raise HTTPException(422,
                            "Enter a full email address, like name@us.ktx.group.")
    existing = (await db.execute(select(MailRecipient).where(
        MailRecipient.project_id == project_id, MailRecipient.list_key == body.list_key,
        func.lower(MailRecipient.email) == email))).scalar_one_or_none()
    if existing is not None:
        if existing.active:
            raise HTTPException(status.HTTP_409_CONFLICT, "This address is already on the list.")
        existing.active = True
        if body.display_name:
            existing.display_name = body.display_name.strip()
        row = existing
    else:
        row = MailRecipient(project_id=project_id, list_key=body.list_key, email=email,
                            display_name=(body.display_name or "").strip() or None, active=True)
        db.add(row)
    await db.flush()
    await AuditService.record(db, entity_type="project", entity_id=project_id,
                              action="mail_recipient.added", user_id=current_user.id,
                              new_values={"list": body.list_key, "email": email})
    await db.commit()
    await db.refresh(row)
    return _out(row)


@projects_router.delete("/{project_id}/mail-recipients/{recipient_id}",
                        status_code=status.HTTP_204_NO_CONTENT)
async def remove_recipient(
    project_id: int,
    recipient_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _project(db, project_id, current_user)
    await _require_manager(db, current_user)
    row = await db.get(MailRecipient, recipient_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on this project's list.")
    await AuditService.record(db, entity_type="project", entity_id=project_id,
                              action="mail_recipient.removed", user_id=current_user.id,
                              old_values={"list": row.list_key, "email": row.email})
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@notifications_router.get("/mail-status")
async def mail_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_manager(db, current_user)
    return part_data_mail.mail_status()


@notifications_router.post("/mail-test")
async def mail_test(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One mail to the signed-in user, never to a list, whatever the trial
    setting says."""
    await _require_manager(db, current_user)
    to = part_data_mail.clean_address(current_user.email or "")
    if not part_data_mail.valid_address(to):
        raise HTTPException(422,
                            "Your account has no usable email address.")
    if not part_data_mail.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Mail is not configured on this server (ENTRA_* unset).")
    try:
        await part_data_mail.send_test(to)
    except Exception as exc:  # noqa: BLE001
        logger.exception("mail test to %s failed", to)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Sending failed: {part_data_mail.describe_error(exc)}")
    return {"sent_to": to}
