"""API-enforced response schema, built from the bible so it stays generic.

JSON Schema guarantees SHAPE. validate.py guarantees MEANING. Provider generation
proves EXECUTION. Three layers, no overlap: semantic rules like
"population == characters.keys()" or "DROWSY -> ASLEEP requires STATE_CHANGE" stay in
deterministic Python and are deliberately NOT encoded here.
"""
from __future__ import annotations


def _enum(values):
    return {"type": "string", "enum": list(values)}


def shot_plan_schema(bible, ep):
    vocab = bible.get("state_vocab", {})
    visual = bible.get("visual_vocab", {})
    cast = list(ep["cast"])
    locations = ep.get("locations") or [ep["location"]]

    char_props = {d: _enum(v["values"]) for d, v in vocab.items()}
    character = {"type": "object", "properties": char_props,
                 "required": [d for d in ("awareness", "posture", "zone") if d in vocab]}

    state = {
        "type": "object",
        "properties": {
            "location_id": _enum(locations),
            "population": {"type": "array", "items": _enum(cast)},
            "characters": {"type": "object",
                           "properties": {c: character for c in cast}},
            "props": {"type": "object"},
        },
        "required": ["location_id", "population", "characters", "props"],
    }

    event = {
        "type": "object",
        "properties": {
            "type": _enum(["ENTER", "EXIT", "MOVE", "TRANSFER", "STATE_CHANGE"]),
            "entity": {"type": "string"},
            "object": {"type": "string"},
            "field": {"type": "string"},
            "from": {"type": "string"},
            "to": {"type": "string"},
            "from_zone": {"type": "string"},
            "to_zone": {"type": "string"},
        },
        "required": ["type"],
    }

    shot = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "cast": {"type": "array", "items": _enum(cast)},
            "frame": {"type": "string"},
            "motion": {"type": "string"},
            "coverage_role": _enum(bible.get("coverage_roles", ["SUBJECT"])),
            # WHAT MUST VISIBLY CHANGE, as semantic intent. The planner declares the
            # requirement; code picks the renderer that can satisfy it most cheaply. A
            # planner that could name its own renderer would name the expensive one.
            "visual_change": _enum(list(bible.get("visual_change", {}))
                                   or ["CHARACTER_DEFORMATION"]),
            "focus": {"type": "object", "properties": {
                "type": _enum(bible.get("focus_types", ["GROUP"])),
                "ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["type", "ids"]},
            "boundary": {
                "type": "object",
                "properties": {
                    "type": _enum(["CONTINUOUS", "TIME_JUMP", "LOCATION_CHANGE", "MONTAGE"]),
                    "reason": {"type": "string"},
                },
                "required": ["type"],
            },
            "events": {"type": "array", "items": event},
            "start_state": state,
            "end_state": state,
        },
        "required": ["id", "cast", "frame", "motion", "coverage_role", "visual_change",
                     "focus", "boundary", "events", "start_state", "end_state"],
    }

    return {
        "type": "object",
        "properties": {
            "shots": {"type": "array", "items": shot},
            "requirement_results": {
                "type": "object",
                "properties": {r["id"]: {
                    "type": "object",
                    "properties": {"status": _enum(["SATISFIED", "DECLINED"]),
                                   "reason": {"type": "string"}},
                    "required": ["status"],
                } for r in (ep.get("requirements") or [])},
            },
        },
        "required": ["shots"],
    }
