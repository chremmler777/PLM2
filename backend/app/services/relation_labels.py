"""Shared relation-type vocabulary and human-readable labels.

Lives here (not in app.api.v1.items.part_relations) so that services can
import it without pulling in the API router module, which would otherwise
risk a circular import back through app.api.v1.
"""

VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related",
                        "serves", "feeds", "mirror_of"}

# Human-readable labels per direction
RELATION_LABELS = {
    "produces": ("produces", "produced by"),
    "checks": ("checks", "checked by"),
    "assembles": ("assembles", "assembled by"),
    "related": ("related to", "related to"),
    # serves: equipment -> every tool it covers (see equipment_numbering.py).
    # feeds: tool -> downstream tool whose station consumes its parts.
    "serves": ("serves", "served by"),
    "feeds": ("feeds", "fed by"),
    "mirror_of": ("mirror of", "mirrored by"),
}
