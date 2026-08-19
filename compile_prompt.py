"""Provider-specific prompt compilation from generic visual constraints.

The planner never authors provider negatives. The channel/world/mode contract declares
generic constraints; this translates them for one provider. PREVENTION only — it does not
replace QC, because a provider may ignore any instruction.
"""
from __future__ import annotations

# The positive clause DESCRIBES the wanted world; the negative TERMS name the unwanted
# things. They are different jobs and the provider consumes them through different
# channels: prose in the prompt body vs the negative_prompt parameter. Deriving both from
# the SAME bible constraint keeps them from drifting apart.
_VEO_NEGATIVE = {
    ("ambient_effects", "NONE"):
        "floating particles, dust motes, sparkles, glows, bokeh, light shafts, haze, "
        "falling dust, glitter, embers, fireflies",
    ("background_entities", "NONE"):
        "extra people, extra animals, extra toys, extra furniture, extra decorations",
    ("text_overlay", "NONE"): "text, letters, numbers, captions, subtitles, watermarks, logos",
    ("weather_effects", "NONE"): "rain, snow, fog, mist, wind",
}

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


def veo_negative_prompt(bible, mode):
    """Terms for the provider's negative_prompt PARAMETER.

    Prose in the prompt body asking for no particles failed on 3 of 4 clips, so it is not
    a control. This is the same intent expressed through the channel the provider actually
    documents for exclusion, compiled from the same bible entry as the positive clause.
    """
    c = effective_constraints(bible, mode)
    parts = [_VEO_NEGATIVE[(k, v)] for k, v in c.items() if (k, v) in _VEO_NEGATIVE]
    return ", ".join(parts)
