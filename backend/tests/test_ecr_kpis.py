"""ECR KPI board: RFQ on time (quoted_at vs required_by_date) and
implementation on time (released_at vs release_due_date), by calendar day."""
from datetime import datetime, timedelta

import pytest

from app.models.change import ChangeRequest

pytestmark = pytest.mark.asyncio


def _mk(seed, number, **kw):
    return ChangeRequest(
        change_number=number, title=number, reason="r", change_type="physical_part",
        project_id=seed["project_id"], raised_by=seed["engineer_id"],
        lead_id=seed["engineer_id"], customer_relevant=True, **kw)


@pytest.fixture
async def kpi_data(session_factory, seed):
    now = datetime.utcnow()
    day = lambda n: datetime(now.year, now.month, now.day) + timedelta(days=n)
    async with session_factory() as s:
        s.add_all([
            # RFQ quoted on the deadline day (later that afternoon): on time.
            _mk(seed, "K-1", status="quoted", required_by_date=day(-5),
                quoted_at=day(-5) + timedelta(hours=15)),
            # RFQ quoted 3 days late; then released 2 days early.
            _mk(seed, "K-2", status="released", required_by_date=day(-40),
                quoted_at=day(-37), release_due_date=day(-1), released_at=day(-3)),
            # RFQ still open and 4 days overdue.
            _mk(seed, "K-3", status="costing", required_by_date=day(-4)),
            # RFQ open, due in 3 days.
            _mk(seed, "K-4", status="costing", required_by_date=day(3)),
            # Implementation open and 6 days overdue.
            _mk(seed, "K-5", status="in_implementation", quoted_at=day(-60),
                release_due_date=day(-6)),
            # Released 5 days late.
            _mk(seed, "K-6", status="released", release_due_date=day(-10),
                released_at=day(-5)),
            # Cancelled with a missed deadline: not counted as open overdue.
            _mk(seed, "K-7", status="cancelled", required_by_date=day(-20)),
            # Quoted two years ago: outside the 12-month window.
            _mk(seed, "K-8", status="quoted", required_by_date=day(-800),
                quoted_at=day(-790)),
        ])
        await s.commit()


async def test_ecr_kpis(client, eng_auth, seed, kpi_data):
    res = await client.get("/api/v1/reports/ecr-kpis", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()

    rfq = body["rfq"]
    assert (rfq["on_time"], rfq["late"]) == (1, 1)
    assert rfq["rate"] == 0.5
    assert rfq["avg_days_late"] == 3.0
    assert rfq["open_overdue"] == 1
    assert rfq["open_due_7d"] == 1
    assert rfq["open_total"] == 2

    impl = body["implementation"]
    assert (impl["on_time"], impl["late"]) == (1, 1)
    assert impl["avg_days_late"] == 5.0
    assert impl["open_overdue"] == 1

    assert len(body["trend"]) == 12
    late = body["late"]
    # open overdue first, worst first; then completed misses
    assert [(r["change_number"], r["kind"]) for r in late[:2]] == [
        ("K-5", "implementation"), ("K-3", "rfq")]
    assert late[0]["done"] is None and late[0]["days_late"] == 6
    assert {r["change_number"] for r in late[2:]} == {"K-2", "K-6"}
    assert "K-7" not in {r["change_number"] for r in late}

    assert len(body["by_project"]) == 1
    p = body["by_project"][0]
    assert (p["rfq_on_time"], p["rfq_late"], p["impl_on_time"], p["impl_late"]) == (1, 1, 1, 1)


async def test_ecr_kpis_all_time(client, eng_auth, seed, kpi_data):
    body = (await client.get("/api/v1/reports/ecr-kpis?months=0", headers=eng_auth)).json()
    assert body["window_months"] is None
    assert (body["rfq"]["on_time"], body["rfq"]["late"]) == (1, 2)


async def test_ecr_kpis_empty(client, eng_auth, seed):
    body = (await client.get("/api/v1/reports/ecr-kpis", headers=eng_auth)).json()
    assert body["rfq"]["rate"] is None and body["implementation"]["rate"] is None
    assert body["late"] == [] and body["by_project"] == []


async def test_ecr_kpi_targets(client, eng_auth, admin_auth, seed, kpi_data):
    body = (await client.get("/api/v1/reports/ecr-kpis", headers=eng_auth)).json()
    assert body["rfq"]["target"] == 0.9            # default 90 %
    assert body["rfq"]["target_met"] is False      # 50 % < 90 %
    assert body["by_project"][0]["rfq_rate"] == 0.5
    assert all(t["rfq_rate"] is None for t in body["trend"] if t["rfq_on_time"] + t["rfq_late"] == 0)

    res = await client.put("/api/v1/reports/ecr-kpis/targets", json={"rfq": 50},
                           headers=eng_auth)
    assert res.status_code == 403
    res = await client.put("/api/v1/reports/ecr-kpis/targets", json={"rfq": 50},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json() == {"rfq": 50.0, "implementation": 90.0}
    res = await client.put("/api/v1/reports/ecr-kpis/targets", json={"rfq": 150},
                           headers=admin_auth)
    assert res.status_code == 422

    body = (await client.get("/api/v1/reports/ecr-kpis", headers=eng_auth)).json()
    assert body["rfq"]["target"] == 0.5 and body["rfq"]["target_met"] is True


async def test_ecr_kpis_leave_out_the_test_project(client, eng_auth, seed, kpi_data, session_factory):
    """SIM changes in test-project never count on the KPI board."""
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from app.models.entities import Project
    async with session_factory() as s:
        plant_id = (await s.get(Project, seed["project_id"])).plant_id
        tp = Project(plant_id=plant_id, name="Test Project", code="test-project", status="active")
        s.add(tp)
        await s.flush()
        s.add(_mk({**seed, "project_id": tp.id}, "K-SIM", status="quoted",
                  required_by_date=datetime.utcnow() - timedelta(days=30),
                  quoted_at=datetime.utcnow() - timedelta(days=1)))
        await s.commit()
    body = (await client.get("/api/v1/reports/ecr-kpis", headers=eng_auth)).json()
    assert (body["rfq"]["on_time"], body["rfq"]["late"]) == (1, 1)
    assert "K-SIM" not in {r["change_number"] for r in body["late"]}
