import pytest
pytestmark = pytest.mark.asyncio

async def test_contacts_falls_back_to_local_users(client, admin_auth, seed):
    res = await client.get("/api/v1/contacts", headers=admin_auth)
    assert res.status_code == 200, res.text
    names = [c["name"] for c in res.json()]
    assert "Engineer" in names  # seeded local user
    # Non-person accounts (admin, service tokens) are not offered (§16).
    assert "Admin" not in names
    assert all("source" in c for c in res.json())


async def test_local_contacts_carry_user_id_not_username(client, admin_auth, seed):
    res = await client.get("/api/v1/contacts", headers=admin_auth)
    eng = next(c for c in res.json() if c["name"] == "Engineer")
    assert eng["user_id"] == seed["engineer_id"]
    # The picker sends the user id; the username is not handed out.
    assert "username" not in eng


async def test_real_users_on_local_or_example_domains_are_kept(
        client, admin_auth, seed, session_factory):
    from app.models.entities import User
    async with session_factory() as s:
        s.add_all([
            User(organization_id=1, username="jdoe", email="jane.doe@plant.local",
                 full_name="Jane Doe", hashed_password="x", role="engineer",
                 is_active=True, mfa_enabled=False),
            User(organization_id=1, username="bsmith", email="bob@example.com",
                 full_name="Bob Smith", hashed_password="x", role="engineer",
                 is_active=True, mfa_enabled=False),
        ])
        await s.commit()
    names = [c["name"] for c in (await client.get("/api/v1/contacts", headers=admin_auth)).json()]
    assert "Jane Doe" in names and "Bob Smith" in names
    assert "Admin" not in names


async def test_hub_entries_resolve_to_users_by_email(session_factory, seed):
    from app.api.v1.accounts.contacts import _people, _resolve_hub
    async with session_factory() as s:
        out = _people(await _resolve_hub(s, [
            {"name": "Engineer (Entra)", "email": "ENG@test.io", "source": "hub"},
            {"name": "Outside Person", "email": "o.person@customer.com", "source": "hub"},
            {"name": "Seeded", "email": "someone@example.com", "source": "hub"},
        ]))
    by_name = {c["name"]: c for c in out}
    assert by_name["Engineer (Entra)"]["user_id"] == seed["engineer_id"]
    assert "username" not in by_name["Engineer (Entra)"]
    assert by_name["Outside Person"]["user_id"] is None
    # not a PLM2 user and an example.com mailbox: still filtered
    assert "Seeded" not in by_name


async def test_is_person_contact_user_rows_skip_the_domain_rule():
    from app.services.early_stage_service import EarlyStageService as E
    assert not E.is_person_contact({"name": "Jane", "email": "jane@plant.local"})
    assert E.is_person_contact({"name": "Jane", "email": "jane@plant.local",
                                "username": "jane"}, is_user=True)
    # a service account stays out even as a user row
    assert not E.is_person_contact({"name": "PLM2 service", "email": "svc@x.local",
                                    "username": "plm2-service"}, is_user=True)


async def test_same_name_people_both_stay_distinguishable(
        client, admin_auth, seed, session_factory):
    """Review finding 6: two different users called the same are two rows,
    told apart by email and department; the same user once."""
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        q = Department(name="QA Contacts", flow_type="action", is_active=True)
        t = Department(name="TE Contacts", flow_type="action", is_active=True)
        s.add_all([q, t]); await s.flush()
        a = User(organization_id=1, username="jsmith1", email="john.smith@ktx.com",
                 full_name="John Smith", hashed_password="x", role="engineer",
                 is_active=True, mfa_enabled=False)
        b = User(organization_id=1, username="jsmith2", email="j.smith2@ktx.com",
                 full_name="John Smith", hashed_password="x", role="engineer",
                 is_active=True, mfa_enabled=False)
        s.add_all([a, b]); await s.flush()
        s.add_all([UserDepartment(user_id=a.id, department_id=q.id),
                   UserDepartment(user_id=b.id, department_id=t.id)])
        await s.commit()
        ids = {a.id, b.id}
    rows = [c for c in (await client.get("/api/v1/contacts", headers=admin_auth)).json()
            if c["name"] == "John Smith"]
    assert {c["user_id"] for c in rows} == ids
    assert {c["email"] for c in rows} == {"john.smith@ktx.com", "j.smith2@ktx.com"}
    assert {c["department"] for c in rows} == {"QA Contacts", "TE Contacts"}


async def test_hub_duplicates_of_one_user_come_once(session_factory, seed):
    from app.api.v1.accounts.contacts import _people, _resolve_hub
    async with session_factory() as s:
        out = _people(await _resolve_hub(s, [
            {"name": "Engineer", "email": "eng@test.io", "source": "hub"},
            {"name": "Engineer (alias)", "email": "ENG@test.io", "source": "hub"},
        ]))
    assert [c["user_id"] for c in out] == [seed["engineer_id"]]


async def test_contacts_are_scoped_to_the_callers_organization(
        client, admin_auth, seed, session_factory):
    """Review finding 7: another organization's users are not offered, and a
    hub entry does not resolve to them."""
    from app.models.entities import Organization, User
    from app.api.v1.accounts.contacts import _resolve_hub
    async with session_factory() as s:
        org = Organization(name="Other Org", code="OTH")
        s.add(org); await s.flush()
        s.add(User(organization_id=org.id, username="stranger",
                   email="stranger@other.com", full_name="Stranger Danger",
                   hashed_password="x", role="engineer", is_active=True,
                   mfa_enabled=False))
        await s.commit()
        other = org.id
    names = [c["name"] for c in (await client.get("/api/v1/contacts", headers=admin_auth)).json()]
    assert "Stranger Danger" not in names
    async with session_factory() as s:
        hit = await _resolve_hub(s, [{"name": "S", "email": "stranger@other.com"}], 1)
        assert hit[0]["user_id"] is None
        hit = await _resolve_hub(s, [{"name": "S", "email": "stranger@other.com"}], other)
        assert hit[0]["user_id"] is not None
