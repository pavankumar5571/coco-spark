"""Provider-specific prompt compilation from generic visual constraints.

The planner never authors provider negatives. The channel/world/mode contract declares
generic constraints; this translates them for one provider. PREVENTION only — it does not
replace QC, because a provider may ignore any instruction.
"""
from __future__ import annotations

_VEO = {
    ("ambient_effects", "NONE"):
        "clean still air, no floating particles, dust motes, sparkles or glows",
    ("ambient_effects", "SUBTLE"): "at most very faint ambient atmosphere",
    ("background_entities", "NONE"):
        "only the specified characters and objects are present, no additional people, "
        "animals, toys or decorations",
    ("text_overlay", "NONE"): "no text, letters, numbers, captions or watermarks",
    ("weather_effects", "NONE"): "no rain, snow, fog or wind effects",
}


def effective_constraints(bible, mode):
    """Mode overrides the channel default; anything unset inherits."""
    base = dict(bible.get("visual_constraints") or {})
    base.update((bible.get("modes", {}).get(mode) or {}).get("visual_constraints") or {})
    return base


def veo_constraint_clause(bible, mode):
    c = effective_constraints(bible, mode)
    parts = [_VEO[(k, v)] for k, v in c.items() if (k, v) in _VEO]
    return ("CONSTRAINTS: " + "; ".join(parts) + ".") if parts else ""
