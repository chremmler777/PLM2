"""Mother-plant changes (spec 2026-09-25 §14): the configuration.

Some changes are engineered and commercially handled by the mother plant. We
run no feasibility and no quote for them: the team is informed what was done,
the mother plant's timing is taken over, and the change goes straight into
bank-build planning and implementation.

The mother plants are a short list kept here, in code, so a new one is one
line. The change stores the NAME string (not an id): the list is config, not
master data, and a renamed plant must not rewrite old changes.
"""

# Where a change comes from. `customer` and `internal` mirror the existing
# customer_relevant flag (backfilled by migration 093); `mother_plant` is the
# side track.
ORIGINS = ("customer", "internal", "mother_plant")
MOTHER_PLANT = "mother_plant"

# The default first: nearly every mother-plant change comes from Weissenburg.
MOTHER_PLANTS = (
    "KTX Weissenburg (WUG)",
    "KTX Solingen",
)
DEFAULT_MOTHER_PLANT = MOTHER_PLANTS[0]

# The only on-path statuses a mother-plant change ever takes. The feasibility
# and quote stages do not exist for it: the mother plant did that work.
MOTHER_PLANT_FLOW = (
    "captured", "scoping", "approved", "in_implementation", "in_validation",
    "released", "closed",
)
MOTHER_PLANT_SKIPPED = ("in_assessment", "costing", "quoting", "quoted")

# The attachment kind of the mother plant's own timing (MS Project XML). It
# seeds the detailed plan when the change enters `approved`.
TIMING_ATTACHMENT_KIND = "mother_plant_timing"

# The release deadline's reason when it is taken from the mother plant's SOP.
SOP_REASON = "Mother plant timing"


def is_mother_plant(change) -> bool:
    return getattr(change, "origin", None) == MOTHER_PLANT
