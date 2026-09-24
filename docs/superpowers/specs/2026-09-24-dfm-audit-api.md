# DFM audit trail: API contract

Date: 2026-09-24. Backend: migration 081, `app/services/dfm_audit.py`, router `app/api/v1/items/dfm.py`.

Every tool's DFM archive keeps an append-only audit trail. Events are written by
the backend as a side effect of the normal DFM actions; there is no endpoint to
create, change or delete an event. The existing changelog entries on the tool
part (`dfm_topic_opened`, `dfm_entry_recorded`, ...) are unchanged.

## Actions

| action | written when | links | details |
|---|---|---|---|
| `topic_opened` | POST topics | topic | `title` |
| `topic_closed` | POST .../close | topic | `title` |
| `topic_reopened` | POST .../reopen | topic | `title` |
| `entry_recorded` | POST .../entries (new entry) | topic, entry | `kind`, `party`, `addressed_to`, `reply_to_id`, `note` (excerpt, max 120 chars, null when empty) |
| `entry_updated` | POST .../entries with `supersedes_id` | topic, entry | as `entry_recorded` plus `supersedes_id` |
| `file_attached` | one per stored file of an entry | topic, entry, file | `filename`, `size`, `content_type`, `sha256` |
| `file_downloaded` | GET .../files/{id}/download | topic, entry, file | `filename` |
| `file_viewed` | GET .../files/{id}/inline (PDF) | topic, entry, file | `filename` |

Rules:

- Changes (topics, entries, files) write their events in the same transaction
  as the change. A rejected request (400, 404, 409) or a failed store (500)
  writes no event.
- An entry writes exactly one of `entry_recorded` / `entry_updated`.
- Downloads and views write their event in a small separate commit after the
  read is authorised (file found on this tool, on disk, PDF for inline). If
  that write fails the file is still served and a warning is logged.
- `sha256` is the hex SHA-256 of the stored bytes, computed while writing the
  file. It is also stored on `dfm_entry_files.sha256` and returned as
  `sha256` in every file object of the topic/entry responses. Files stored
  before 081 have `sha256: null`.
- Backfilled events (migration 081, from rows that existed before) carry
  `details.backfilled: true`. The backfill creates `topic_opened`,
  `topic_closed` (only for topics currently finished), `entry_recorded` /
  `entry_updated` and `file_attached`. Earlier reopen/close cycles, views and
  downloads were never recorded and are not in the trail.

## GET /api/v1/parts/{part_id}/dfm/audit

Auth as the other DFM routes (401 without a session). `part_id` must be a tool
(404 unknown part, 400 "Only tools have a DFM archive" otherwise).

Query parameters (all optional):

| name | meaning |
|---|---|
| `topic_id` | only events of this topic. A topic that is not on this tool answers 404 "Topic not found" (same as the topic routes). |
| `action` | one of the actions above; anything else answers 400 |
| `limit` | 1..500, default 100 (422 outside the range) |
| `before_id` | only events with `id < before_id` (paging cursor) |

Answer: a JSON list, newest first (ordered by `id` descending; ids follow
insertion order, the backfill inserts in time order). Paging: pass the last
`id` of a page as `before_id` for the next; a page shorter than `limit` is the
last one.

```json
[
  {
    "id": 42,
    "at": "2026-09-24T09:15:02.113400",
    "action": "file_attached",
    "actor": {"id": 2, "name": "Engineer"},
    "topic": {"id": 7, "title": "Gate position"},
    "entry": {"id": 19, "kind": "original", "party": "ktx"},
    "file": {"id": 11, "filename": "dfm_request_A.pdf"},
    "details": {
      "filename": "dfm_request_A.pdf",
      "size": 482113,
      "content_type": "application/pdf",
      "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    }
  },
  {
    "id": 41,
    "at": "2026-09-24T09:15:02.101002",
    "action": "entry_recorded",
    "actor": {"id": 2, "name": "Engineer"},
    "topic": {"id": 7, "title": "Gate position"},
    "entry": {"id": 19, "kind": "original", "party": "ktx"},
    "file": null,
    "details": {
      "kind": "original",
      "party": "ktx",
      "addressed_to": ["toolmaker", "tier1"],
      "reply_to_id": null,
      "note": "DFM request rev A"
    }
  },
  {
    "id": 40,
    "at": "2026-09-24T09:12:40.550210",
    "action": "topic_opened",
    "actor": {"id": 2, "name": "Engineer"},
    "topic": {"id": 7, "title": "Gate position"},
    "entry": null,
    "file": null,
    "details": {"title": "Gate position"}
  }
]
```

Other detail shapes:

```json
{"action": "entry_updated", "details": {"kind": "original", "party": "ktx", "addressed_to": ["toolmaker"],
  "reply_to_id": null, "note": "rev B", "supersedes_id": 19}}
{"action": "file_viewed", "details": {"filename": "dfm_request_A.pdf"}}
{"action": "topic_closed", "details": {"title": "Gate position", "backfilled": true}}
{"action": "file_attached", "details": {"filename": "old.pdf", "size": 1200, "content_type": "application/pdf",
  "sha256": null, "backfilled": true}}
```

`at` is UTC without offset (same as the other DFM timestamps). `actor.name` is
the user's full name, else the username.

## GET /api/v1/parts/{part_id}/dfm/audit.csv

Same auth, tool and `topic_id` rules as above; no paging (the whole trail, or
one topic's, newest first).

- `Content-Type: text/csv; charset=utf-8`, body starts with a UTF-8 BOM so
  Excel shows umlauts correctly. Comma separated, CRLF line ends, standard CSV
  quoting.
- `Content-Disposition: attachment; filename="dfm-audit-<tool number>.csv"`,
  with a topic filter `dfm-audit-<tool number>-topic-<topic id>.csv`.
- Columns: `at` (ISO 8601), `actor` (name), `action`, `topic` (`#7 Gate
  position`), `entry` (`#19 original (ktx)`), `file` (`#11 dfm_request_A.pdf`),
  `details` (compact `key=value; key=value`, lists comma joined, nulls left out).

```
at,actor,action,topic,entry,file,details
2026-09-24T09:15:02.113400,Engineer,file_attached,#7 Gate position,#19 original (ktx),#11 dfm_request_A.pdf,filename=dfm_request_A.pdf; size=482113; content_type=application/pdf; sha256=9f86d0...
2026-09-24T09:15:02.101002,Engineer,entry_recorded,#7 Gate position,#19 original (ktx),,"kind=original; party=ktx; addressed_to=toolmaker,tier1; note=DFM request rev A"
2026-09-24T09:12:40.550210,Engineer,topic_opened,#7 Gate position,,,title=Gate position
```

## Not provided

No POST, PUT, PATCH or DELETE on `/dfm/audit` (405) and no per-event route.
