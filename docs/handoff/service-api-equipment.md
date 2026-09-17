# Service API: bearer token + `GET /api/v1/equipment` by tool number

> **STATUS 2026-09-16: MERGED to main (`0f7270d8`), not yet deployed.**
> Deploy needs one env var on `plm2-backend` and an image rebuild. No
> migration. Consumer: the equipment/gauge import client, built after deploy.

**Context.** Machine callers (the import client, later Maintenance sync) have
no hub cookie and know tool numbers, not PLM part ids. This adds a read-only
service principal and a lookup keyed by tool number. Browsers are untouched:
they keep the AdminPanel JWT cookie with role objects.

## Authentication

```
Authorization: Bearer <PLM2_SERVICE_TOKEN>
```

Same pattern TWOS exposes to PDB. The auth dependency (`app/dependencies/auth.py`,
`_service_principal`) takes this path whenever a bearer header is present.

| Situation | Response |
|---|---|
| `PLM2_SERVICE_TOKEN` unset on the server | 503 `Service token is not configured` |
| Token mismatch | 401 `Invalid service token` |
| Any method other than GET, HEAD, OPTIONS | 403 `Service token is read-only` |
| Valid | request runs as user `plm2-service` |

`plm2-service` is auto-provisioned on first use: role `viewer`, hub-managed
sentinel password, default organisation. It shows up in the user list and in
audit like any other user. Deactivating it there is the kill switch.
`GET /auth/me` reports it with `plm2_roles: ["plm2_Viewer"]`.
`X-Acts-As-Department` is refused for it (403), as for every non-admin.

Token comparison is constant-time (`hmac.compare_digest`).

## Endpoint

```
GET /api/v1/equipment?tool_number=<n>[&include_gauges=true]
```

Works with the bearer token and with a hub cookie alike.

| Parameter | Meaning |
|---|---|
| `tool_number` | Required. Tool part number, e.g. `3454`, `0674-2`, `91-0001`. A short all-digit value is retried zero-padded: `745` finds `0745`. |
| `include_gauges` | Default `false`. `true` adds `-4x` gauge rows. |

Response: the stations that `serves` this tool, ordered by op code. Same rows
`ProcessFlowService.build` puts in `stations`, without `tool`, `upstream`,
`downstream`.

```json
[
  {
    "id": 812,
    "part_number": "3454-30",
    "name": "Punch & weld station",
    "op_code": "30",
    "kind": "secondary_station",
    "serves": ["3454", "3455", "3457"]
  }
]
```

`kind` is one of `eoat`, `in_cell_station`, `secondary_station`, `gauge`.
`serves` is the full coverage of that station, sorted, so a shared station
returned for 3455 still says it covers 3454 and 3457.

| Situation | Response |
|---|---|
| No `tool` part with that number | 404 |
| Tool exists, no equipment | 200 `[]` |
| `tool_number` missing | 422 |

Coverage comes from the `serves` relation, never from the number prefix: 3455
owns no equipment, its station is `3454-30`, and it is still returned.

## Deploy

1. Parent compose, `plm2-backend` environment:
   `PLM2_SERVICE_TOKEN: ${PLM2_SERVICE_TOKEN}` and the value in the `.env`
   next to it (`openssl rand -hex 32`). Give the same value to the client.
2. Rebuild and restart `plm2-backend` (code is baked into the image).
3. Smoke test:

```
curl -H "Authorization: Bearer $PLM2_SERVICE_TOKEN" \
  "https://<host>/plm2/api/v1/equipment?tool_number=3454&include_gauges=true"
```

## If the op-code format changes later

Christoph flagged (2026-09-16) that the suffix may change, e.g. `3450-030`.
The suffix only says what a thing is (EOAT, station, gauge); the tool keeps
its bare number as its own part, and coverage lives in `serves` rows. A
format change touches exactly three functions in
`app/services/equipment_numbering.py`: the two-digit regex in
`parse_equipment_number`, `classify`, and `equipment_number`. The only
composer is the gauge importer; the only parser is `ProcessFlowService`.
This endpoint and the process-flow view need no change beyond that.

## Tests

`backend/tests/test_service_token.py`, `backend/tests/test_equipment_by_tool.py`.
Suite runs parallel by default (`-n auto` in `pytest.ini`), ~6 min for 805 tests.
