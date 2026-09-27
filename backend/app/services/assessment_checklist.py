"""The assessment checklist: a fixed set of questions every department answers.

This is config, not data. The questions are the same for every change and every
project — "does this change alter the cycle time?", "is a 3D change needed?" —
so they live in code where they can be reviewed in a diff, rather than in rows
somebody can quietly edit per department. The activity CATALOG
(AssessmentActivity) stays what it always was: the costing selection list.

Every routed department answers the four COMMON items, then its own list
(DEPARTMENT_ITEMS, from the workbook's department sheets). `GET
/changes/reference/assessment-checklist?department_id=N` serves the resolved
set so the frontend renders from here instead of hardcoding the same list a
second time.
"""

# key -> (label_de, label_en, choices)
# `choices` is None for a plain yes/no item, or a list of options when the
# answer needs a sub-choice as well.
#
# Four COMMON items every routed department judges for its own area; then
# each department's own list, taken from its sheet of the change management
# workbook (D2..D10) where it has one. Keys are stable identifiers: a stored
# answer keeps its key forever (see LEGACY_ITEMS).
COMMON_ITEMS = [
    ("work_instruction_update", "Arbeitsanweisung / Dokumente aktualisieren",
     "Work instruction / document update", None),
    # Two independent ticks, not a choice: a change can rebuild something in
    # house AND send work to a supplier.
    ("modification_internal", "Interne Änderung/Umbau",
     "Internal modification", None),
    ("modification_external", "Externe Änderung/Umbau (Lieferant)",
     "External modification (supplier)", None),
    ("timing_risk", "Terminrisiko (Termin gefährdet)",
     "Timing risk (required date at risk)", None),
]

# Documents a Yes owes before the assessment can be submitted. Only where
# the business says a document is part of the answer: external supplier work
# is presented internally (the change presentation) and priced by the
# supplier (the change RFQ), so a Yes there is not a finished answer until
# both are filed against the assessment. Each document is told apart by its
# attachment kind (the tag chosen at upload), never by its file name; the
# extensions only say which files a slot takes. A draft saves without them:
# only the submit is held. Rows already submitted are not re-judged.
PPT_EXTENSIONS = (".ppt", ".pptx", ".pdf")
# The frontend mirrors both lists in DOCUMENT_EXTENSIONS (ActivityChecklist.tsx)
# for the slots that sit outside a checklist row (the not-feasible deck, the
# bucket's RFQ slot). The change presentation stays PowerPoint or its PDF
# export: a Word file is not the deck the customer is shown.
RFQ_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".doc", ".docx", ".msg", ".eml")

# kind -> (label_de, label_en, allowed extensions)
REQUIRED_DOCUMENTS = {
    "change_ppt": ("Änderungspräsentation", "Change presentation", PPT_EXTENSIONS),
    "rfq": ("Änderungs-RFQ", "Change RFQ", RFQ_EXTENSIONS),
}

# How a missing document is named in the submit refusal.
DOCUMENT_PHRASES = {
    "change_ppt": "the change presentation (PPT)",
    "rfq": "the change RFQ",
}

# checklist key -> the document kinds a Yes owes, in the order they are asked.
REQUIRES_DOCUMENTS = {
    "modification_external": ("change_ppt", "rfq"),
}

# Kept for the evidence state the UI reads (rfq_expected): a Yes on these
# owes the RFQ. Since 2026-09-27 it is also enforced at submit, through
# REQUIRES_DOCUMENTS.
RFQ_EXPECTED_KEYS = {k for k, kinds in REQUIRES_DOCUMENTS.items() if "rfq" in kinds}


def required_documents(key: str) -> list[dict]:
    """The documents a Yes on `key` owes, as the frontend renders the slots."""
    out = []
    for kind in REQUIRES_DOCUMENTS.get(key, ()):
        label_de, label_en, exts = REQUIRED_DOCUMENTS[kind]
        out.append({"kind": kind, "label_de": label_de, "label_en": label_en,
                    "extensions": list(exts)})
    return out


def allowed_extensions(kind: str) -> tuple | None:
    """The file types a required-document kind takes, or None (any file)."""
    doc = REQUIRED_DOCUMENTS.get(kind)
    return doc[2] if doc else None


def missing_documents(impacts, filed_kinds: set,
                      department_name: str | None = None) -> list[str]:
    """What a checklist answer still owes, one sentence per Yes row, e.g.
    "External modification needs the change presentation (PPT) and the
    change RFQ attached before you submit". Empty when nothing is owed.

    `impacts` is the submitted (or stored) checklist; a row counts as Yes by
    its answer, or by `impacted` for rows stored before answers existed."""
    out: list[str] = []
    seen: set = set()
    for entry in impacts or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        yes = (entry.get("answer") == "yes" if entry.get("answer") is not None
               else bool(entry.get("impacted")))
        if not key or not yes or key in seen:
            continue
        seen.add(key)
        owed = [DOCUMENT_PHRASES[k] for k in REQUIRES_DOCUMENTS.get(key, ())
                if k not in filed_kinds]
        if not owed:
            continue
        label = (label_for(key, department_name) or key).split(" (")[0]
        out.append(f"{label} needs {' and '.join(owed)} attached before you submit")
    return out


_DESIGN_CHOICES = [
    {"value": "internal", "label_de": "Intern", "label_en": "Internal"},
    {"value": "customer_given", "label_de": "Kundenvorgabe",
     "label_en": "Customer given"},
]

_CYCLE = ("cycle_time_change", "Zykluszeitänderung", "Cycle time change", None)
_SCRAP = ("scrap_increase", "Ausschusserhöhung", "Scrap increase", None)
_MAINT = ("maintenance_increase", "Erhöhter Wartungsaufwand",
          "Increased maintenance", None)
_SPARE = ("sparepart_required", "Ersatzteil erforderlich", "Spare part required", None)
_NEWPROC = ("new_process", "Neuer Prozess", "New process", None)
_DIM = ("dimensional_risk", "Maßliches Risiko", "Dimensional risk", None)
_VIS = ("visual_risk", "Optisches Risiko", "Visual risk", None)
_3D = ("threed_change", "3D-Änderung erforderlich", "3D change necessary", None)
_PROTO = ("prototyping_required", "Prototypen/Musterbau erforderlich",
          "Prototyping required", None)
_MATCH = ("matching_required", "Abmusterung/Matching erforderlich",
          "Matching/sampling required", None)
_CAPAB = ("capability_study", "MFU / PFU (Maschinen-/Prozessfähigkeit)",
          "Machine / process capability study", None)
_TRIALS = ("trials_required", "Versuche erforderlich", "Trials required", None)

# Department name -> its own items, in the same tuple shape.
DEPARTMENT_ITEMS = {
    "Development": [
        _3D,
        ("article_design_update", "Artikelkonstruktion anpassen",
         "Article design update", _DESIGN_CHOICES),
        ("tolerance_change", "Toleranzen Produkt ändern",
         "Product tolerances change", None),
        _DIM, _VIS, _PROTO,
    ],
    "Tool Engineer": [
        ("tool_modification", "Werkzeug / Werkzeugänderung",
         "Tool / tool modification", None),
        ("moldflow_simulation", "Moldflow-Simulation", "Moldflow simulation", None),
        _MATCH, _MAINT, _SPARE, _SCRAP,
    ],
    "Manufacturing Engineer": [
        _CYCLE,
        ("bom_change", "Stückliste anlegen/ändern", "Bill of materials change", None),
        ("line_layout_change", "Layout ändern", "Line layout change", None),
        ("fixture_change", "Schweiß-/Montagevorrichtungen",
         "Welding / assembly fixtures", None),
        _NEWPROC, _MAINT, _SPARE,
    ],
    "Process Engineer": [
        _CYCLE, _NEWPROC, _SCRAP,
        ("process_parameter_change", "Prozessparameter ändern",
         "Process parameters change", None),
        _CAPAB, _TRIALS,
    ],
    "APQP": [
        ("pfmea_update", "PFMEA aktualisieren", "PFMEA update", None),
        ("control_plan_update", "Control Plan aktualisieren",
         "Control plan update", None),
        ("ppap_resubmission", "Neubemusterung Kunde (EMPB/PPAP)",
         "Customer re-sampling (PPAP)", None),
        ("imds_update", "IMDS-Eintrag ändern", "IMDS entry update", None),
    ],
    # Asked once "packaging impacted?" is Yes (spec §16); "not impacted" is a
    # complete assessment and skips the whole checklist.
    "Packaging Engineer": [
        ("layout_change", "Verpackungslayout ändern", "Packaging layout change", None),
        ("packaging_type_change", "Verpackungsart ändern", "Packaging type change", None),
        ("packaging_modification", "Verpackung modifizieren", "Packaging modification", None),
    ],
    "Quality": [
        ("test_plan_change", "Erprobungspläne ändern", "Testing plans change", None),
        ("inspection_spec_change", "Prüfvorschriften/-verfahren ändern",
         "Inspection instructions change", None),
        ("lab_tests", "Labortests", "Laboratory tests", None),
        ("part_measurement", "Teilevermessung", "Part measurement", None),
        ("gauge_change", "Prüfmittel / Lehren ändern",
         "Gauges / checking fixtures change", None),
        ("msa_required", "MSA 1 / MSA 2 durchführen", "MSA 1 / MSA 2 required", None),
        ("reference_sample", "Rückstellmuster", "Reference sample", None),
        _DIM, _VIS,
    ],
    "Scheduling": [
        ("stock_finished", "Lagerbestand Fertigteile betroffen",
         "Finished-part stock affected", None),
        ("stock_semi_finished", "Lagerbestand Halbfertigteile betroffen",
         "Semi-finished stock affected", None),
        ("stock_components", "Lagerbestand Einzelteile betroffen",
         "Component stock affected", None),
        ("bank_build_needed", "Vorproduktion (Bank Build) nötig",
         "Bank build needed", None),
    ],
    "Sales": [
        ("part_price_change", "Teilepreis / Neukalkulation",
         "Part price / recalculation", None),
        ("quotation_required", "Angebotserstellung", "Quotation to the customer", None),
        ("cost_negotiation", "Kostenverhandlung", "Cost negotiation", None),
        ("po_processing", "Bestellabwicklung", "Purchase order processing", None),
    ],
    "Project Manager": [
        ("timing_plan_update", "Projektterminplan aktualisieren",
         "Project timing plan update", None),
        ("milestone_impact", "Meilenstein / SOP betroffen",
         "Milestone / SOP affected", None),
        ("customer_approval_required", "Kundenfreigabe erforderlich",
         "Customer approval required", None),
    ],
    "Finance": [
        ("capex_required", "Investition (CapEx) erforderlich",
         "Investment (CapEx) required", None),
        ("part_cost_change", "Teilekosten / Kalkulation betroffen",
         "Part cost / calculation affected", None),
        ("stock_write_off", "Abschreibung Altbestand", "Write-off of obsolete stock", None),
    ],
    "Purchasing": [
        ("supplier_offers", "Angebote einholen", "Request supplier offers", None),
        ("supplier_price_negotiation", "Preisverhandlungen durchführen",
         "Supplier price negotiation", None),
        ("material_cost_change", "Materialeinsatz ändert sich",
         "Material cost change", None),
    ],
    "Logistics": [
        ("packaging_extra_cost", "Verpackungsmehrkosten", "Extra packaging cost", None),
        ("labelling_change", "Etikettierung ändern", "Labelling change", None),
        ("interim_storage", "Zwischenlagern und Q-Gate", "Interim storage and Q gate", None),
        ("freight_cost_change", "Zusätzliche Frachtkosten", "Extra freight cost", None),
    ],
    "Production": [
        _CAPAB, _TRIALS,
        ("staff_training", "Schulung Personal", "Staff training", None),
        _CYCLE, _SCRAP,
    ],
}

# Items that are no longer asked of a department (the 13-item common list
# before 2026-09-25) but may sit in a stored answer. A stored row with one of
# these keys stays valid on resubmit and keeps its label and cost-line
# seeding; it is never demanded of a new assessment.
LEGACY_ITEMS = [
    _CYCLE, _SCRAP, _MAINT, _3D, _DIM, _VIS,
    ("work_instruction_update", "Arbeitsanweisung aktualisieren",
     "Work instruction update", None),
    _NEWPROC, _SPARE,
    ("modification_internal", "Interne Änderung/Umbau",
     "Internal modification", None),
    ("modification_external", "Externe Änderung/Umbau (Lieferant)",
     "External modification (supplier)", None),
    _PROTO, _MATCH,
]

# The one item whose cost is per part for the life of the programme; every
# other checked item seeds a one-off line. See CostService.seed_from_checklist.
LIFECYCLE_KEYS = {"cycle_time_change"}


def _entry(item: tuple, extra: bool) -> dict:
    key, label_de, label_en, choices = item
    out = {"key": key, "label_de": label_de, "label_en": label_en,
           "extra": extra}
    if choices:
        out["choices"] = choices
    docs = required_documents(key)
    if docs:
        out["requires_documents"] = docs
    return out


def items_for(department_name: str | None) -> list[dict]:
    """The full checklist a department answers: the common items, then its own.

    An unknown department still gets the common set — a department nobody
    thought to configure has questions to answer just like everyone else.
    """
    items = [_entry(i, False) for i in COMMON_ITEMS]
    items += [_entry(i, True)
              for i in DEPARTMENT_ITEMS.get(department_name or "", [])]
    return items


def keys_for(department_name: str | None) -> set:
    """Keys a department must answer now (the served checklist)."""
    return {i["key"] for i in items_for(department_name)}


def accepted_keys_for(department_name: str | None) -> set:
    """Keys a stored or resubmitted answer may carry: the current checklist
    plus the legacy items, so an answer given before the checklist changed
    is never refused (and never has to be re-answered)."""
    return keys_for(department_name) | {i[0] for i in LEGACY_ITEMS}


def _find(key: str, department_name: str | None) -> dict | None:
    for item in items_for(department_name):
        if item["key"] == key:
            return item
    for item in LEGACY_ITEMS:
        if item[0] == key:
            return _entry(item, False)
    return None


def label_for(key: str, department_name: str | None) -> str | None:
    """English label, used when a checked item becomes a cost line."""
    item = _find(key, department_name)
    return item["label_en"] if item else None


def choices_for(key: str, department_name: str | None) -> list:
    item = _find(key, department_name)
    return [c["value"] for c in item.get("choices", [])] if item else []
