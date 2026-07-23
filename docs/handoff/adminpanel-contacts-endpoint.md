# Handoff → AdminPanel chat: `/api/v1/contacts` for PLM2 attendee autofill

**Context.** PLM2's scoping panel autofills meeting attendees. PLM2 already
ships the consuming side: a proxy `GET /api/v1/contacts` (forwards the caller's
SSO cookie to the hub) and a datalist autocomplete. Today it falls back to
PLM2's local users. This handoff is the **hub side** that makes it serve the
signed-in user's real Outlook people, fetched **live** (no daily cache). **Do
not expose the whole directory** — use the user's own delegated token, so no
`User.Read.All` app permission and no DENWERIT directory grant.

**Why hub-side (not browser MSAL.js):** the hub already performs the Entra token
exchange, so reading `/me/people` reuses it. A browser-direct MSAL.js approach
would additionally require registering a Single-Page-App redirect URI on the app
registration and running a second token flow in the frontend — more Entra change
and more moving parts for the same result. The one shared prerequisite either
way is adding the delegated `People.Read` scope.

Everything below is work in the `adminpanel` repo + Entra config. PLM2 needs no
further change once the contract is met.

## Response contract (must match exactly)

`GET /api/v1/contacts` → `200`, JSON array:

```json
[{ "name": "Dana Lee", "email": "dana.lee@ktx.group", "source": "entra" }]
```

- Auth: `get_current_user` (any valid SSO user). **Not** `require_superuser` —
  PLM2 forwards a normal user's shared cookie.
- `source`: `"entra"` when from Graph, `"local"` for the dev fallback.

## Implementation

1. **Scopes.** In `auth_microsoft.py`, add delegated scopes to `SCOPES`:
   `openid profile email User.Read People.Read offline_access`
   (`offline_access` gives a refresh token so Graph can be called after the
   initial access token expires without forcing re-login; use `Contacts.Read`
   instead of / with `People.Read` if saved contacts are preferred over
   relevance-ranked colleagues).

2. **Keep the Graph token.** The callback currently reads only `id_token` and
   discards `token_resp`. Capture `access_token` and `refresh_token` from that
   same response and store them per user (encrypted at rest, or in Redis keyed
   by user id). This is the only new persistence.

3. **Endpoint** `GET /api/v1/contacts` — **fetch live, no 24h cache** (product
   decision: attendee list should reflect the current mailbox, not a daily
   snapshot):
   - When `settings.entra_enabled`: get a valid Graph access token (refresh via
     the stored refresh token if the cached one is expired), then
     `GET https://graph.microsoft.com/v1.0/me/people?$top=100&$select=displayName,scoredEmailAddresses`
     (or `/me/contacts?$select=displayName,emailAddresses`). Map each to
     `{name: displayName, email: <first email>, source: "entra"}`. Follow
     `@odata.nextLink` if present. Return directly — do **not** cache the result.
     An optional very-short in-process cache (≤60 s, keyed by user) is fine only
     to absorb rapid re-opens; anything longer defeats the "live" intent.
   - When **not** `entra_enabled` (local dev): return the hub's local `users`
     table as `{name: full_name or username, email, source: "local"}` so the
     chain works without Entra.
   - On Graph error (e.g. consent missing → 403): fall back to local users
     rather than 500, and log it. PLM2 already degrades gracefully too.

   Note: PLM2's frontend already keeps a light per-session query cache, so live
   fetching here is not called on every keystroke — only when a scoping form is
   first opened in a session.

## Consent caveat (flag to the user, not a code task)

`People.Read` / `Contacts.Read` are **delegated** and low-privilege. If the
tenant allows user consent, each user approves once at their next login and IT
does nothing. If the tenant blocks user consent (locked-down orgs), an admin
grants consent **once** for the app registration — a single click, still **no**
directory-wide `User.Read.All`.

## PLM2 side (already done — for reference)

- Proxy: `backend/app/api/v1/accounts/contacts.py` — GETs `{hub_api_base}/api/v1/contacts`
  forwarding the `access_token` cookie; local-users fallback on empty base or error.
- Config: `hub_api_base` (empty in dev). Set it to the hub's internal URL in the
  PLM2 server env (e.g. the compose service name) to switch the proxy on.
- Frontend: `src/api/contacts.ts` + datalist autocomplete in `ScopingPanel.tsx`.
