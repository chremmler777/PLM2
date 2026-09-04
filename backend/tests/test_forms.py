"""SEP forms engine: definitions, instances, events, SEP item linking."""
from sqlalchemy import select

from app.models.forms import FormDefinition, FormInstance, FormEvent


async def test_models_roundtrip(session_factory, seed):
    async with session_factory() as s:
        d = FormDefinition(key="t", version=1, title="T", implements=None, cardinality="single",
                           gate_items=False, body={"sections": []})
        s.add(d)
        await s.flush()
        inst = FormInstance(project_id=seed["project_id"], definition_id=d.id, status="draft",
                            data={"a": 1}, created_by=seed["admin_id"], updated_by=seed["admin_id"])
        s.add(inst)
        await s.flush()
        s.add(FormEvent(instance_id=inst.id, user_id=seed["admin_id"], event="created"))
        await s.commit()
    async with session_factory() as s:
        got = (await s.execute(select(FormInstance))).scalar_one()
        assert got.data == {"a": 1}
        ev = (await s.execute(select(FormEvent))).scalar_one()
        assert ev.event == "created" and ev.role is None
