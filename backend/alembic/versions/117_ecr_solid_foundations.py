"""117: ECR-solid foundations (flow spec rev 6, lane L1).

Schema
  change_requests.sales_owner_id       named Sales owner (C10)
  change_requests.price_open           a price still open after approval (HARD #9)
  change_requests.pm_signed_offer_id   the offer a signature was given on (C14);
  change_requests.quality_signed_offer_id   no FK, like accepted_offer_id
  implementation_bookings.source       'estimate' (confirmed estimate) | 'typed' (C15)
  implementation_bookings.work_date    the day the hours were worked (C15)
  wf_departments.can_start_internal_change   may start an INTERNAL change (P3)

Data
  departments  Toolshop (P7, its own department, not Tool Engineer) and
               Management (P4, gives the OK on price drops / Absorb) seeded
  P3           Development, Process Engineer, Tool Engineer start internal changes
  sales owner  customer changes: the raiser when in Sales, else the project's
               Sales responsible; internal and mother-plant changes stay NULL
  signatures   bound to the accepted offer, else the latest sent one
  bookings     dated at creation, source 'typed'

Core expressions only (BOOLEAN on Postgres, INTEGER on SQLite). Repeatable:
every column is added once, every backfill only fills NULLs.

Revision ID: 117
Revises: 116
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None

INTERNAL_STARTERS = ("Development", "Process Engineer", "Tool Engineer")
NEW_DEPARTMENTS = ("Toolshop", "Management")

_dept = sa.table(
    "wf_departments",
    sa.column("id", sa.Integer), sa.column("name", sa.String),
    sa.column("flow_type", sa.String), sa.column("is_active", sa.Boolean),
    sa.column("can_start_change", sa.Boolean),
    sa.column("can_start_internal_change", sa.Boolean),
    sa.column("sort_order", sa.Integer), sa.column("created_at", sa.DateTime),
)
_ud = sa.table("user_departments", sa.column("user_id", sa.Integer),
               sa.column("department_id", sa.Integer))
_users = sa.table("users", sa.column("id", sa.Integer),
                  sa.column("is_active", sa.Boolean))
_resp = sa.table("project_responsibles", sa.column("project_id", sa.Integer),
                 sa.column("department_id", sa.Integer),
                 sa.column("user_id", sa.Integer))
_cr = sa.table(
    "change_requests",
    sa.column("id", sa.Integer), sa.column("project_id", sa.Integer),
    sa.column("raised_by", sa.Integer), sa.column("customer_relevant", sa.Boolean),
    sa.column("origin", sa.String), sa.column("sales_owner_id", sa.Integer),
    sa.column("pm_signed_by", sa.Integer), sa.column("quality_signed_by", sa.Integer),
    sa.column("accepted_offer_id", sa.Integer),
    sa.column("pm_signed_offer_id", sa.Integer),
    sa.column("quality_signed_offer_id", sa.Integer),
)
_offer = sa.table("change_offers", sa.column("id", sa.Integer),
                  sa.column("change_id", sa.Integer), sa.column("version", sa.Integer),
                  sa.column("status", sa.String), sa.column("sent_at", sa.DateTime))
_book = sa.table("implementation_bookings", sa.column("id", sa.Integer),
                 sa.column("booked_at", sa.DateTime), sa.column("source", sa.String),
                 sa.column("work_date", sa.Date))


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _has_table(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _add(table: str, column: sa.Column, fk: tuple | None = None) -> None:
    if not _has_table(table) or _has_column(table, column.name):
        return
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)
        if fk is not None:
            batch.create_foreign_key(fk[0], fk[1], [column.name], ["id"])


def _drop(table: str, column: str, fk: str | None = None) -> None:
    if not _has_table(table) or not _has_column(table, column):
        return
    with op.batch_alter_table(table) as batch:
        if fk is not None:
            batch.drop_constraint(fk, type_="foreignkey")
        batch.drop_column(column)


def upgrade() -> None:
    bind = op.get_bind()
    _add("change_requests", sa.Column("sales_owner_id", sa.Integer(), nullable=True),
         fk=("fk_change_requests_sales_owner_id", "users"))
    _add("change_requests", sa.Column("price_open", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    _add("change_requests", sa.Column("pm_signed_offer_id", sa.Integer(), nullable=True))
    _add("change_requests", sa.Column("quality_signed_offer_id", sa.Integer(),
                                      nullable=True))
    _add("implementation_bookings", sa.Column("source", sa.String(20), nullable=True))
    _add("implementation_bookings", sa.Column("work_date", sa.Date(), nullable=True))
    _add("wf_departments", sa.Column("can_start_internal_change", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))

    if _has_table("wf_departments"):
        names = {n for (n,) in bind.execute(sa.select(_dept.c.name)).all()}
        top = bind.execute(sa.select(sa.func.max(_dept.c.sort_order)).where(
            _dept.c.is_active.is_(True))).scalar() or 0
        for i, name in enumerate(NEW_DEPARTMENTS, start=1):
            if name not in names:
                bind.execute(_dept.insert().values(
                    name=name, flow_type="action", is_active=sa.true(),
                    can_start_change=sa.false(), can_start_internal_change=sa.false(),
                    sort_order=top + i, created_at=datetime.utcnow()))
        bind.execute(_dept.update().where(_dept.c.name.in_(INTERNAL_STARTERS))
                     .values(can_start_internal_change=sa.true()))

    if _has_table("change_requests"):
        _backfill_sales_owner(bind)
        if _has_table("change_offers"):
            _backfill_signed_offers(bind)
    if _has_table("implementation_bookings"):
        for bid, at in bind.execute(sa.select(_book.c.id, _book.c.booked_at).where(
                _book.c.work_date.is_(None))).all():
            bind.execute(_book.update().where(_book.c.id == bid).values(
                work_date=at.date() if at is not None else None))
        bind.execute(_book.update().where(_book.c.source.is_(None))
                     .values(source="typed"))


def _backfill_sales_owner(bind) -> None:
    sales_id = bind.execute(sa.select(_dept.c.id).where(
        _dept.c.name == "Sales")).scalar()
    if sales_id is None:
        return
    in_sales = {u for (u,) in bind.execute(
        sa.select(_ud.c.user_id).join(_users, _users.c.id == _ud.c.user_id)
        .where(_ud.c.department_id == sales_id, _users.c.is_active.is_(True))).all()}
    contact = {}
    if _has_table("project_responsibles"):
        for pid, uid in bind.execute(sa.select(_resp.c.project_id, _resp.c.user_id)
                                     .where(_resp.c.department_id == sales_id)).all():
            if uid in in_sales:            # a stale responsible is no contact
                contact[pid] = uid
    rows = bind.execute(sa.select(_cr.c.id, _cr.c.project_id, _cr.c.raised_by).where(
        _cr.c.sales_owner_id.is_(None), _cr.c.customer_relevant.is_(True),
        sa.or_(_cr.c.origin.is_(None), _cr.c.origin != "mother_plant"))).all()
    for cid, pid, raiser in rows:
        owner = raiser if raiser in in_sales else contact.get(pid)
        if owner is not None:
            bind.execute(_cr.update().where(_cr.c.id == cid).values(sales_owner_id=owner))


def _backfill_signed_offers(bind) -> None:
    rows = bind.execute(sa.select(
        _cr.c.id, _cr.c.accepted_offer_id, _cr.c.pm_signed_by, _cr.c.quality_signed_by,
        _cr.c.pm_signed_offer_id, _cr.c.quality_signed_offer_id).where(sa.or_(
            _cr.c.pm_signed_by.is_not(None), _cr.c.quality_signed_by.is_not(None)))).all()
    for cid, accepted, pm_by, q_by, pm_offer, q_offer in rows:
        offer = accepted
        if offer is None:
            offer = bind.execute(sa.select(_offer.c.id).where(
                _offer.c.change_id == cid, _offer.c.sent_at.is_not(None))
                .order_by(_offer.c.version.desc()).limit(1)).scalar()
        if offer is None:
            continue
        values = {}
        if pm_by is not None and pm_offer is None:
            values["pm_signed_offer_id"] = offer
        if q_by is not None and q_offer is None:
            values["quality_signed_offer_id"] = offer
        if values:
            bind.execute(_cr.update().where(_cr.c.id == cid).values(**values))


def downgrade() -> None:
    # The seeded departments stay: memberships may already point at them.
    _drop("wf_departments", "can_start_internal_change")
    _drop("implementation_bookings", "work_date")
    _drop("implementation_bookings", "source")
    _drop("change_requests", "quality_signed_offer_id")
    _drop("change_requests", "pm_signed_offer_id")
    _drop("change_requests", "price_open")
    _drop("change_requests", "sales_owner_id", fk="fk_change_requests_sales_owner_id")
