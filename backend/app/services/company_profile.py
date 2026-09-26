"""The issuing company as printed on customer documents (the offer PDF).

Defaults are the KTX Toccoa site (ktx.group/en/contact). Every field can be
overridden through an environment variable; an unset or empty variable keeps
the default (docker-compose.prod.yml passes them all, empty by default). A
field that ends up empty is simply left off the document: no placeholder text
is ever printed.

    KTX_COMPANY_LEGAL_NAME       legal name (letterhead, footer, signature)
    KTX_COMPANY_ADDRESS          address lines, separated by '|'
    KTX_COMPANY_PHONE            phone number
    KTX_COMPANY_FAX              fax number
    KTX_COMPANY_EMAIL            e-mail address
    KTX_COMPANY_WEBSITE          website
    KTX_COMPANY_FOOTER           extra footer lines, separated by '|'
    KTX_COMPANY_SIGNATURE_NAME   optional override of the signer's name
    KTX_COMPANY_SIGNATURE_TITLE  optional override of the signer's function,
                                 printed as "<legal name> | <title>"

Sales signs the customer offer (decision 2026-09-25): the sender is frozen as
signer when they are in Sales; anyone else who sends gets the project's Sales
responsible, or the Sales role line alone. A draft previews exactly what a send
by the viewer would freeze (see OfferService.draft_signer); offer_signer()
builds it.
The two signature variables are no longer needed; when set they still win
over the person, for a site that wants one fixed name on every offer.

When the legal name ends up empty the organisation name from the database
stands in for it.
"""
from __future__ import annotations

import os

DEFAULTS: dict = {
    "legal_name": "KTX Group US Corp.",
    "address_lines": ["325 Hammerstone Drive", "Toccoa, GA 30577",
                      "United States of America"],
    "phone": "+1 706 963 1110",
    "fax": "+1 706 963 1052",
    "email": "ktx_info@us.ktx.group",
    "website": "ktx.group",
    "footer_lines": ["IATF 16949:2016 certified site", "A company of the KTX Group"],
    "signature_name": "",
    "signature_title": "Sales",
}

ENV = {
    "legal_name": "KTX_COMPANY_LEGAL_NAME",
    "address_lines": "KTX_COMPANY_ADDRESS",
    "phone": "KTX_COMPANY_PHONE",
    "fax": "KTX_COMPANY_FAX",
    "email": "KTX_COMPANY_EMAIL",
    "website": "KTX_COMPANY_WEBSITE",
    "footer_lines": "KTX_COMPANY_FOOTER",
    "signature_name": "KTX_COMPANY_SIGNATURE_NAME",
    "signature_title": "KTX_COMPANY_SIGNATURE_TITLE",
}

LIST_FIELDS = ("address_lines", "footer_lines")


def _lines(v: str) -> list[str]:
    return [x.strip() for x in v.split("|") if x.strip()]


def company_profile(org_name: str | None = None, env: dict | None = None,
                    defaults: dict | None = None) -> dict:
    """The profile: defaults, then the non-empty environment overrides; the
    legal name falls back to `org_name` when empty. `env` defaults to
    os.environ; `defaults` to DEFAULTS."""
    env = os.environ if env is None else env
    base = {**DEFAULTS, **(defaults or {})}
    out: dict = {}
    for field, default in base.items():
        raw = (env.get(ENV[field]) or "").strip()
        if not raw:
            out[field] = list(default) if field in LIST_FIELDS else default
        elif field in LIST_FIELDS:
            out[field] = _lines(raw)
        else:
            out[field] = raw
    if not out["legal_name"]:
        out["legal_name"] = (org_name or "").strip()
    return out


def contact_line(profile: dict) -> str:
    """Phone, fax, e-mail and website on one line, the empty ones left out."""
    parts = []
    for label, key in (("Phone", "phone"), ("Fax", "fax"), ("", "email"),
                       ("", "website")):
        v = (profile.get(key) or "").strip()
        if v:
            parts.append(f"{label} {v}".strip())
    return "  |  ".join(parts)


def signature_line(profile: dict) -> str:
    """ "<legal name> | <title>", either part left out when empty."""
    return " | ".join(x for x in ((profile.get("legal_name") or "").strip(),
                                    (profile.get("signature_title") or "").strip()) if x)


SIGNER_TITLE = "Sales"


def offer_signer(user_name: str | None = None, user_title: str | None = None,
                 env: dict | None = None) -> dict:
    """{"name", "title"} printed at the foot of the offer: the Sales person's
    name and title ("Sales" unless the person carries a title of their own).
    KTX_COMPANY_SIGNATURE_NAME / _TITLE, when set, override either. A missing
    person leaves the name empty: the PDF then prints the role line only."""
    env = os.environ if env is None else env
    name = (env.get(ENV["signature_name"]) or "").strip() or (user_name or "").strip()
    title = ((env.get(ENV["signature_title"]) or "").strip()
             or (user_title or "").strip() or SIGNER_TITLE)
    return {"name": name, "title": title}
