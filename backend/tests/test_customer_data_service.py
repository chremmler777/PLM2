"""RevisionService: majors only from customer statements, minors are ours."""
from datetime import date

import pytest

from app.models.part import Part
from app.services.part_service import PartService, RevisionService
from app.services.revision_naming import RevisionRuleViolation


async def _part(session_factory, seed, number="P-S"):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number=number,
                                          name="Svc", part_type="purchased", created_by=seed["admin_id"])
        await s.commit()
        return p.id


async def test_receive_review_then_official_then_minor(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(
            s, pid, "review", date(2026, 9, 1), customer_index="A", created_by=seed["admin_id"])
        assert (e1.revision_name, e1.phase, e1.source, e1.status) == ("E1", "review", "customer", "approved")
        assert e1.customer_index == "A" and e1.part_phase_at_receipt == "rfq"
        e2 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e2.revision_name == "E2"
        one = await RevisionService.receive_customer_data(s, pid, "official", date(2026, 9, 3), created_by=seed["admin_id"])
        assert (one.revision_name, one.phase) == ("1", "official")
        part = await s.get(Part, pid)
        assert part.active_revision_id == one.id
        m = await RevisionService.create_proposal(s, pid, one.id, summary="tweak", created_by=seed["admin_id"])
        assert (m.revision_name, m.phase, m.source, m.status) == ("1.1", "official", "internal", "draft")
        with pytest.raises(RevisionRuleViolation):
            await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 4), created_by=seed["admin_id"])
        await s.commit()


async def test_promote_proposal_creates_next_major_with_statement(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        p1 = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        p2 = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        new = await RevisionService.promote_revision(s, p2.id, "official", date(2026, 9, 5), customer_index="B", created_by=seed["admin_id"])
        assert (new.revision_name, new.phase, new.customer_index) == ("1", "official", "B")
        assert "Promoted from E1.2" in (new.summary or "")
        await s.refresh(p1); await s.refresh(p2)
        assert p2.status == "approved" and p1.status == "rejected"
        await s.commit()


async def test_proposal_requires_major_parent_of_same_part(session_factory, seed):
    pid = await _part(session_factory, seed)
    other = await _part(session_factory, seed, number="P-O")
    async with session_factory() as s:
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        p = await RevisionService.create_proposal(s, pid, e1.id, created_by=seed["admin_id"])
        with pytest.raises(ValueError):
            await RevisionService.create_proposal(s, pid, p.id, created_by=seed["admin_id"])
        with pytest.raises(ValueError):
            await RevisionService.create_proposal(s, other, e1.id, created_by=seed["admin_id"])


async def test_lifecycle_phase_transitions(session_factory, seed):
    pid = await _part(session_factory, seed)
    async with session_factory() as s:
        with pytest.raises(ValueError):
            await RevisionService.set_lifecycle_phase(s, pid, "series", date(2026, 9, 1), seed["admin_id"])
        part = await RevisionService.set_lifecycle_phase(s, pid, "nominated", date(2026, 9, 1), seed["admin_id"])
        assert part.lifecycle_phase == "nominated" and part.nominated_at == date(2026, 9, 1)
        e1 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e1.part_phase_at_receipt == "nominated"
        part = await RevisionService.set_lifecycle_phase(s, pid, "series", date(2027, 1, 1), seed["admin_id"])
        assert part.sop_at == date(2027, 1, 1)
        await s.commit()


async def test_receive_with_chosen_major_number(session_factory, seed):
    pid = await _part(session_factory, seed, number="P-MAJ")
    async with session_factory() as s:
        e2 = await RevisionService.receive_customer_data(
            s, pid, "review", date(2026, 9, 1), major=2, created_by=seed["admin_id"])
        assert e2.revision_name == "E2"
        e3 = await RevisionService.receive_customer_data(s, pid, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        assert e3.revision_name == "E3"
        with pytest.raises(RevisionRuleViolation):
            await RevisionService.receive_customer_data(
                s, pid, "review", date(2026, 9, 3), major=3, created_by=seed["admin_id"])
        await s.commit()
