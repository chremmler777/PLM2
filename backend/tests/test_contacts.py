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


async def test_local_contacts_carry_user_id_and_username(client, admin_auth, seed):
    res = await client.get("/api/v1/contacts", headers=admin_auth)
    eng = next(c for c in res.json() if c["name"] == "Engineer")
    assert eng["user_id"] == seed["engineer_id"] and eng["username"] == "eng"


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
    assert by_name["Engineer (Entra)"]["username"] == "eng"
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
