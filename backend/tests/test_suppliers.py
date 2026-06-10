"""Supplier master data tests."""


async def test_supplier_crud_and_part_link(client, eng_auth, seed):
    # Create
    res = await client.post(
        "/api/v1/suppliers",
        json={"name": "Bosch GmbH", "code": "V-1001", "contact_email": "sales@bosch.example"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    supplier_id = res.json()["id"]

    # Duplicate name rejected
    res = await client.post("/api/v1/suppliers", json={"name": "Bosch GmbH"}, headers=eng_auth)
    assert res.status_code == 409

    # Create a purchased part linked to the supplier
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": "B-100",
            "name": "Sensor",
            "part_type": "purchased",
            "data_classification": "confidential",
            "supplier_id": supplier_id,
        },
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    part_id = res.json()["id"]
    assert res.json()["supplier_id"] == supplier_id

    # Supplier list shows the part count
    res = await client.get("/api/v1/suppliers", headers=eng_auth)
    bosch = next(s for s in res.json() if s["id"] == supplier_id)
    assert bosch["part_count"] == 1

    # Supplier part listing
    res = await client.get(f"/api/v1/suppliers/{supplier_id}/parts", headers=eng_auth)
    assert [p["part_number"] for p in res.json()] == ["B-100"]

    # Unlink via part update (explicit null)
    res = await client.put(
        f"/api/v1/parts/{part_id}", json={"supplier_id": None}, headers=eng_auth
    )
    assert res.status_code == 200
    assert res.json()["supplier_id"] is None


async def test_supplier_deactivate_hidden_from_default_list(client, eng_auth):
    res = await client.post("/api/v1/suppliers", json={"name": "Old Vendor"}, headers=eng_auth)
    supplier_id = res.json()["id"]

    res = await client.patch(
        f"/api/v1/suppliers/{supplier_id}", json={"is_active": False}, headers=eng_auth
    )
    assert res.status_code == 200

    res = await client.get("/api/v1/suppliers", headers=eng_auth)
    assert all(s["id"] != supplier_id for s in res.json())

    res = await client.get("/api/v1/suppliers?include_inactive=true", headers=eng_auth)
    assert any(s["id"] == supplier_id for s in res.json())
