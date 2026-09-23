# DFM archive as a flow: originals, answers, follow-ups, forwards

Date: 2026-09-23. Status: user goal ("dfm is implemented but not intuitive,
need to identify original, answered and where it was sent ... use best way"),
design decided by delegation; builds on
`2026-09-23-tool-dfm-archive-design.md`.

## Problem

The first DFM archive stores entries per party column with an "addressed to"
list and in-place updates. In use it is not intuitive:

- You cannot see which entry is the original DFM and which is a reply.
- You cannot see whether something was answered, or who still owes an answer.
- The relay KTX does all the time (toolmaker DFM in, KTX forwards to the
  Tier 1, Tier 1 answers, KTX answers the toolmaker, toolmaker asks again)
  has no shape: it is three columns of loose cards.

## The flow the user described

```
Toolmaker          KTX                 Tier 1
   | DFM rev 1 ---->|                     |      original (toolmaker to KTX)
   |                |--- forward ------->|      forward (KTX to Tier 1, links the original)
   |                |<------ answer -----|      answer to the forward
   |<--- answer ----|                     |      answer to the original
   | question ----->|                     |      ask again (follow-up on KTX's answer)
   |                | ...                 |
```

KTX also starts DFMs itself (KTX to toolmaker, KTX to Tier 1). Every step
must be saved with its files and mail date.

## Design

### 1. Message types (data)

Each entry gets a `kind` and an optional `reply_to_id`:

| kind | meaning | reply_to | who can create it |
|---|---|---|---|
| `original` | a new DFM study or request | none | any party |
| `forward` | passes a received message on to another party | the message forwarded | KTX |
| `answer` | a reply | the message answered | an addressee of that message |
| `question` | ask again, follow-up on an answer | the answer asked about | an addressee of that answer |
| `update` | a corrected version of one's own message | via existing `supersedes_id` | the sender |

Rules, enforced by the backend with 400 on violation:
- `reply_to_id` must be in the same topic.
- An `answer` or `question` comes from a party the replied-to message was
  addressed to, and is addressed to that message's sender (prefilled; the
  form may add the third party as copy).
- A `forward` replies to a message KTX received, comes from KTX and is
  addressed to a party that was neither sender nor addressee of it.
- `original` has no `reply_to_id`.
- Existing rows (before this change) become `original` (migration default)
  with no reply link, so nothing is lost.

### 2. Answered or waiting (derived, never stored)

For every `original`, `forward` and `question` message, each addressee is
either **answered** (there is an `answer` with `reply_to_id` = this message
from that party) or **waiting since** the message date. The topic detail
response carries per message:

- `awaiting`: list of parties that still owe an answer, with days waiting
- `answered_by`: list of `{party, entry_id, date}`

The topic list carries a summary: `waiting_on: [{party, count, oldest_days}]`
and `last_step` (kind, from, to, date). A topic with nothing waiting and at
least one answer shows "all answered"; the "Finish confirmed" action stays
manual.

### 3. The screen: a sequence flow

The ledger becomes a swimlane sequence diagram, the standard picture for a
message exchange between parties:

- Three lanes with headers: Toolmaker, KTX, Tier 1 (fixed order), each with
  a count of messages waiting on that party.
- One row per message in time order (mail date, then recording time).
  An arrow runs from the sender's lane to each addressee's lane. The message
  card sits in the sender's lane and shows:
  - a type badge: **Original**, **Forward**, **Answer**, **Question**,
    colour coded (blue, violet, green, amber) and repeated in the arrow colour
  - "to Toolmaker, Tier 1", mail date, recorder initials, files (PDF opens
    in the pane, others download), note
  - "reply to #12 Original" link for answers, questions and forwards;
    clicking it scrolls to and highlights that message
  - status: "Answered by KTX 09-27" (green) or "Waiting on Tier 1 · 4 days"
    (amber, dashed arrow)
  - "(updated)" plus collapsed earlier versions, as today
- Actions on each card, only the ones that make sense for that card:
  **Answer** (on a message addressed to a party, from that party),
  **Ask again** (on an answer), **Forward to Tier 1 / to Toolmaker**
  (on a message KTX received), **Update** (own message).
- Top of the topic: a status strip with the next step in words, for example
  "Waiting on Tier 1 for 4 days: KTX forward of Toolmaker DFM rev 1" and
  counts per party, plus a small legend of the four types.

### 4. Recording a step: a guided form

"+ New DFM" opens the form for an original (from, to, title line or note,
mail date, files). Every other step starts from a card action, so the form
is prefilled: type, from, to, reply link. The form states the step in plain
words at the top ("Answer from KTX to Toolmaker on Original #12") so the user
always knows what they are saving. Files drop in the same way as today.

### 5. Topic list

Each topic row shows its status pill (open / finished), the waiting summary
("waiting on Tier 1 · 4 d"), the last step and date, and the message count,
so the tool page tells at a glance where each DFM stands.

## Data change

Migration after 079: `dfm_entries.kind` String(20) not null default
`original` (server default for existing rows), `dfm_entries.reply_to_id`
FK `dfm_entries.id` nullable, indexed. Guarded like 076-079.

## Testing

Backend: each kind's rules (valid and each 400), awaiting/answered
derivation incl. forward chains and ask-again, summary on the topic list,
old rows read as originals, supersede still works, closed topic still 409.

Frontend: lanes and arrows render for a full relay (original, forward,
answer, answer, question); type badges and status lines; card actions shown
only where valid; each action opens the form prefilled and posts the right
kind, reply_to and addressees; reply link highlights the target; status
strip text; topic list summary.

Browser check on the local test stack with the ISOFIX tool (199403): record
the full relay above with a PDF and see it read correctly.

## Out of scope

Email sending, reminders or due dates, per-message approval workflows.
