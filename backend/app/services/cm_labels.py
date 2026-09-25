"""Human labels for the change module's codes (spec §16 P2).

Served by GET /changes/reference/labels so every screen, message and audit
row reads "Feasible with conditions", not "feasible_with_conditions". Kept
next to the backend's own vocabulary (models/change.py) so a new code and its
label arrive in the same diff. English and German, like the checklist and the
risk types.
"""

# code -> (label_en, label_de)
STATUS = {
    "captured": ("Captured", "Erfasst"),
    "scoping": ("Scoping", "Klärung"),
    "in_assessment": ("In Assessment", "In Bewertung"),
    "costing": ("Costing", "Kalkulation"),
    "quoting": ("Quote creation", "Angebotserstellung"),
    "quoted": ("Quoted", "Angeboten"),
    "approved": ("Approved", "Freigegeben"),
    "in_implementation": ("Implementing", "Umsetzung"),
    "in_validation": ("Validation", "Validierung"),
    "released": ("Released", "Serienfreigabe"),
    "closed": ("Closed", "Abgeschlossen"),
    "on_hold": ("On Hold", "Angehalten"),
    "rejected": ("Rejected", "Abgelehnt"),
    "cancelled": ("Cancelled", "Storniert"),
}

VERDICT = {
    "pending": ("Pending", "Offen"),
    "feasible": ("Feasible", "Machbar"),
    "feasible_with_conditions": ("Feasible with conditions", "Machbar mit Bedingungen"),
    "not_feasible": ("Not feasible", "Nicht machbar"),
}

CHANGE_TYPE = {
    "physical_part": ("Physical part", "Physisches Bauteil"),
    "tooling": ("Tooling", "Werkzeug"),
    "document_spec": ("Document / specification", "Dokument / Spezifikation"),
    "process_im": ("Process (IM)", "Prozess (IM)"),
    "packaging": ("Packaging", "Verpackung"),
}

PRIORITY = {
    "low": ("Low", "Niedrig"),
    "medium": ("Medium", "Mittel"),
    "high": ("High", "Hoch"),
    "critical": ("Critical", "Kritisch"),
}

CONCERN_KIND = {
    "reject_proposal": ("Cancel vote", "Abbruchvotum"),
    "needs_info": ("Question", "Frage"),
    "risk": ("Risk", "Risiko"),
}

RASIC = {
    "R": ("Responsible", "Verantwortlich"),
    "A": ("Accountable", "Rechenschaftspflichtig"),
    "S": ("Supports", "Unterstützt"),
    "I": ("Informed", "Informiert"),
    "C": ("Consulted", "Konsultiert"),
}

COST_CARRIER = {
    "customer": ("Customer change", "Kundenänderung"),
    "internal": ("Internal change", "Interne Änderung"),
}

SETTLED_AS = {
    "author": ("Withdrawn by author", "Vom Verfasser zurückgezogen"),
    "pm": ("Settled by Project Management", "Vom Projektmanagement geklärt"),
    "department": ("Settled by the department", "Von der Abteilung geklärt"),
}

# My Tasks row kinds (GET /changes/my-tasks), spec §16: human kind labels.
TASK_KIND = {
    "kickoff": ("Hand over to scoping", "An Klärung übergeben"),
    "scoping_wrapup": ("Wrap up scoping", "Klärung abschließen"),
    "impact_confirm": ("Confirm impacted items", "Betroffene Teile bestätigen"),
    "assessment": ("Assessment", "Bewertung"),
    "obtain_info": ("Answer the open question", "Offene Frage beantworten"),
    "close_question": ("Settle the answered question", "Beantwortete Frage abschließen"),
    "send_rejection": ("Send rejection letter", "Absage senden"),
    "costing_input": ("Costing input", "Kalkulationsbeitrag"),
    "costing_update": ("Costing update after scope change", "Kalkulation nach Umfangsänderung"),
    "create_quote": ("Create the quote", "Angebot erstellen"),
    "customer_response": ("Record the customer response", "Kundenantwort erfassen"),
    "offer_expiring": ("Offer expiring", "Angebot läuft ab"),
    "update_quote": ("Update the quote", "Angebot aktualisieren"),
    "bank_build": ("Decide the bank build", "Bankbau entscheiden"),
    "publish_plan": ("Publish the plan", "Plan veröffentlichen"),
    "plan_feedback": ("Confirm the timing", "Zeitplan bestätigen"),
    "progress_report": ("Report progress", "Fortschritt melden"),
    "escalate_risk": ("Escalate the risk", "Risiko eskalieren"),
    "release_check": ("Release checklist", "Freigabe-Checkliste"),
    "info_ack": ("Read and understood", "Gelesen und verstanden"),
    "info_send": ("Send the information", "Information senden"),
    "inform_mother_plant": ("Inform KTX Weissenburg / Solingen",
                            "KTX Weissenburg / Solingen informieren"),
}

GROUPS = {
    "status": STATUS, "verdict": VERDICT, "change_type": CHANGE_TYPE,
    "priority": PRIORITY, "concern_kind": CONCERN_KIND, "rasic": RASIC,
    "cost_carrier": COST_CARRIER, "settled_as": SETTLED_AS,
    "task_kind": TASK_KIND,
}


def label(group: str, code, lang: str = "en") -> str:
    """The label of `code` in `group`; the code itself when unknown, so a
    new value degrades to readable text rather than an error."""
    if code is None:
        return ""
    pair = GROUPS.get(group, {}).get(code)
    if pair is None:
        return str(code).replace("_", " ").capitalize() if group == "task_kind" \
            else str(code)
    return pair[1] if lang == "de" else pair[0]


def reference() -> dict:
    """{group: {code: {"en", "de"}}} for the reference endpoint."""
    return {g: {k: {"en": v[0], "de": v[1]} for k, v in items.items()}
            for g, items in GROUPS.items()}
