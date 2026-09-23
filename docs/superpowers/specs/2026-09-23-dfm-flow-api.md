# DFM flow: API contract

Date: 2026-09-23. Backend for `2026-09-23-dfm-flow-design.md` sections 1, 2
and 5. Migration 080. All paths under `/api/v1/parts/{part_id}/dfm/` as
before; `part_id` must be a tool.

## Recording a step

`POST /parts/{part_id}/dfm/topics/{topic_id}/entries` (multipart, as before)

Existing fields: `party`, `addressed_to` (JSON list string), `note`,
`sent_at` (YYYY-MM-DD or blank), `supersedes_id`, `files` (repeatable).

New form fields:

| field | type | meaning |
|---|---|---|
| `kind` | string, optional | `original` \| `forward` \| `answer` \| `question`. Default `original`. On an update (`supersedes_id` set) it defaults to the kind of the superseded entry. |
| `reply_to_id` | int, optional | the entry this one forwards, answers or asks again about. On an update it defaults to the superseded entry's `reply_to_id`. |

There is no `update` kind: an update is `supersedes_id`, same as before.

Rules (400 with `detail` as below; 409 for a finished topic and for a
double supersede stay unchanged):

| case | detail |
|---|---|
| unknown kind | `Unknown kind 'x'. Valid: original, forward, answer, question` |
| original with reply_to_id | `An original has no reply link` |
| forward/answer/question without reply_to_id | `A <kind> needs the message it replies to` |
| reply_to_id missing or in another topic | `The message replied to is not in this topic` |
| forward not from ktx | `Only KTX forwards messages` |
| forward of a message not addressed to ktx | `KTX can only forward a message it received` |
| forward addressed to the replied message's sender or an addressee of it | `A forward goes to a party that has not had the message yet` |
| question replying to a non-answer | `A question must reply to an answer` |
| question from a party the answer was not addressed to | `Only a party the answer was addressed to can ask again on it` |
| question not addressed to the answer's sender | `A question must be addressed to the sender of the answer it asks about` |
| answer from a party the message was not addressed to | `Only a party the message was addressed to can answer it` |
| answer not addressed to the replied message's sender | `An answer must be addressed to the sender of the message it replies to` |
| update with a different kind | `An update keeps the kind of the message it updates` |

Answers and questions may add the third party to `addressed_to` as a copy.
The response is the created entry shaped exactly like an item of the topic
detail's `entries` (including `history`, `answered_by`, `awaiting`).

## Derived state (never stored)

Only current entries (not superseded) count. For each `original`, `forward`
and `question`, each addressee is either answered (a current `answer` from
that party whose `reply_to_id` is this entry or any earlier version of it)
or awaiting. Days = whole days from the entry's `sent_at` (else the date it
was recorded) to today, never negative. `answer` entries always have empty
`answered_by` and `awaiting`. A forward does not answer the message it
forwards. The derivation also runs on finished topics; show it or not by
`status`.

### Entry (in `entries`, and the POST response)

New fields:

- `kind`: string (legacy rows read `original`)
- `reply_to_id`: int or null
- `answered_by`: `[{party, entry_id, date}]` (date = answer's mail date or
  recorded date, YYYY-MM-DD), in time order; a party may appear twice if it
  answered twice
- `awaiting`: `[{party, days}]`, in addressed_to order

Entries in `history` carry `kind` and `reply_to_id`, with empty
`answered_by` and `awaiting`.

### Topic list item (`GET .../dfm/topics`) and topic detail

New fields on both:

- `waiting_on`: `[{party, count, oldest_days}]`, parties in the fixed order
  toolmaker, ktx, tier1, only parties with count > 0
- `last_step`: `{kind, party, addressed_to, date}` of the latest current
  entry in time order (mail date, then recorded time), or null for an empty
  topic
- `all_answered`: true when nothing is awaiting and at least one answer exists

New on the topic detail only:

- `next_step`: `{entry_id, kind, from, to, days}`, the longest waiting
  addressee (ties: earlier entry in time order), or null

## Example: topic detail after the full relay

Toolmaker original to KTX (09-13), KTX forward to Tier 1 (09-15), Tier 1
answer to the forward (09-18), KTX answer to the original (09-20), toolmaker
question on KTX's answer (09-22); today 2026-09-23.

`GET /parts/1/dfm/topics/1`:

```json
{
  "id": 1,
  "tool_part_id": 1,
  "title": "Gate position",
  "status": "open",
  "opened_by": 2,
  "opened_at": "2026-09-23T22:13:13.530902",
  "closed_by": null,
  "closed_at": null,
  "entry_count": 5,
  "last_activity": "2026-09-23T22:13:14.306068",
  "waiting_on": [
    {
      "party": "ktx",
      "count": 1,
      "oldest_days": 1
    }
  ],
  "last_step": {
    "kind": "question",
    "party": "toolmaker",
    "addressed_to": [
      "ktx"
    ],
    "date": "2026-09-22"
  },
  "all_answered": false,
  "next_step": {
    "entry_id": 5,
    "kind": "question",
    "from": "toolmaker",
    "to": "ktx",
    "days": 1
  },
  "entries": [
    {
      "id": 1,
      "topic_id": 1,
      "party": "toolmaker",
      "addressed_to": [
        "ktx"
      ],
      "note": "DFM rev 1",
      "kind": "original",
      "reply_to_id": null,
      "answered_by": [
        {
          "party": "ktx",
          "entry_id": 4,
          "date": "2026-09-20"
        }
      ],
      "awaiting": [],
      "sent_at": "2026-09-13",
      "supersedes_id": null,
      "recorded_by": 2,
      "recorded_by_name": "Engineer",
      "recorded_at": "2026-09-23T22:13:13.672935",
      "files": [],
      "history": []
    },
    {
      "id": 2,
      "topic_id": 1,
      "party": "ktx",
      "addressed_to": [
        "tier1"
      ],
      "note": "please check gate",
      "kind": "forward",
      "reply_to_id": 1,
      "answered_by": [
        {
          "party": "tier1",
          "entry_id": 3,
          "date": "2026-09-18"
        }
      ],
      "awaiting": [],
      "sent_at": "2026-09-15",
      "supersedes_id": null,
      "recorded_by": 2,
      "recorded_by_name": "Engineer",
      "recorded_at": "2026-09-23T22:13:13.845192",
      "files": [],
      "history": []
    },
    {
      "id": 3,
      "topic_id": 1,
      "party": "tier1",
      "addressed_to": [
        "ktx"
      ],
      "note": "gate ok",
      "kind": "answer",
      "reply_to_id": 2,
      "answered_by": [],
      "awaiting": [],
      "sent_at": "2026-09-18",
      "supersedes_id": null,
      "recorded_by": 2,
      "recorded_by_name": "Engineer",
      "recorded_at": "2026-09-23T22:13:14.003853",
      "files": [],
      "history": []
    },
    {
      "id": 4,
      "topic_id": 1,
      "party": "ktx",
      "addressed_to": [
        "toolmaker"
      ],
      "note": "accepted by Tier 1",
      "kind": "answer",
      "reply_to_id": 1,
      "answered_by": [],
      "awaiting": [],
      "sent_at": "2026-09-20",
      "supersedes_id": null,
      "recorded_by": 2,
      "recorded_by_name": "Engineer",
      "recorded_at": "2026-09-23T22:13:14.164061",
      "files": [],
      "history": []
    },
    {
      "id": 5,
      "topic_id": 1,
      "party": "toolmaker",
      "addressed_to": [
        "ktx"
      ],
      "note": "and the rib?",
      "kind": "question",
      "reply_to_id": 4,
      "answered_by": [],
      "awaiting": [
        {
          "party": "ktx",
          "days": 1
        }
      ],
      "sent_at": "2026-09-22",
      "supersedes_id": null,
      "recorded_by": 2,
      "recorded_by_name": "Engineer",
      "recorded_at": "2026-09-23T22:13:14.306068",
      "files": [],
      "history": []
    }
  ]
}
```

The same topic in `GET /parts/1/dfm/topics`:

```json
[
  {
    "id": 1,
    "tool_part_id": 1,
    "title": "Gate position",
    "status": "open",
    "opened_by": 2,
    "opened_at": "2026-09-23T22:13:13.530902",
    "closed_by": null,
    "closed_at": null,
    "entry_count": 5,
    "last_activity": "2026-09-23T22:13:14.306068",
    "waiting_on": [
      {
        "party": "ktx",
        "count": 1,
        "oldest_days": 1
      }
    ],
    "last_step": {
      "kind": "question",
      "party": "toolmaker",
      "addressed_to": [
        "ktx"
      ],
      "date": "2026-09-22"
    },
    "all_answered": false
  }
]
```
