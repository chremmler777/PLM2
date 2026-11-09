"""2026-11-09 night: the customer offer carries customer numbers only (no KTX
article number in its title, no KTX project number in part names), and a
bank build never prints fixed dates."""
from datetime import date

from app.services.offer_service import customer_name, customer_title


def test_customer_name_drops_the_project_number():
    assert customer_name("1864 OPMOBILITY VW426 LOWER CLADDING", "1864") == "OPMOBILITY VW426 LOWER CLADDING"
    assert customer_name("OPMOBILITY GRILL", "1864") == "OPMOBILITY GRILL"
    assert customer_name("18640 X", "1864") == "18640 X"
    assert customer_name(None, "1864") == ""


def test_customer_title_is_customer_number_and_name():
    items = [{"number": "3CR.807.532.A", "name": "OPMOBILITY VW426 LOWER CLADDING"},
             {"number": "3CR.807.531.A", "name": "UPPER"}]
    assert customer_title(items) == "3CR.807.532.A - OPMOBILITY VW426 LOWER CLADDING +1"
    assert customer_title(items[:1]) == "3CR.807.532.A - OPMOBILITY VW426 LOWER CLADDING"
    assert customer_title([]) == ""
    assert "20-3453" not in customer_title(items)


def test_bank_build_prints_estimate_not_dates():
    from reportlab.graphics.shapes import String
    from app.services import offer_pdf
    tasks = [{"name": "Bank build (estimate, floats with the PO)", "lane": "Logistics",
              "kind": "bank_build", "idea": True,
              "start": date(2026, 11, 19), "end": date(2026, 11, 29), "duration": 10},
             {"name": "Tool change", "lane": "Tool Engineer", "kind": "work",
              "start": date(2026, 11, 29), "end": date(2026, 12, 10), "duration": 11}]
    drawings = offer_pdf._plan_charts(tasks, 500, "en")
    texts = []

    def walk(g):
        for c in getattr(g, "contents", []):
            if isinstance(c, String):
                texts.append(c.text)
            walk(c)
    for d in drawings:
        walk(d)
    assert texts.count("estimate") == 2
