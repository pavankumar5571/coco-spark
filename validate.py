"""Deterministic shot-plan validator. No model calls, no cost.

State says WHAT IS TRUE. Events say WHY IT CHANGED. Every discontinuity must be
explained by a typed event, never inferred from prose — no English keywords, no regex,
no language dependence. This matters because the audience is 48% India / 14% Bangladesh
and Hindi and Bengali episodes are a near-term requirement.

A plan that fails here never reaches image generation, so the failure costs nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

EVENT_TYPES = ("ENTER", "EXIT", "TRANSFER", "MOVE", "STATE_CHANGE")
BOUNDARY_TYPES = ("CONTINUOUS", "TIME_JUMP", "LOCATION_CHANGE", "MONTAGE")


@dataclass
class Issue:
    severity: str      # ERROR | WARN
    code: str          # stable, machine-readable
    shot_id: str
    path: str          # where in the plan
    message: str       # for humans


def _pop(s):
    return set((s or {}).get("population") or [])


def _chars(s):
    return (s or {}).get("characters") or {}


def _props(s):
    return (s or {}).get("props") or {}


def _events(shot):
    return shot.get("events") or []


def _has(shot, **match):
    for e in _events(shot):
        if all(str(e.get(k, "")).lower() == str(v).lower() for k, v in match.items()):
            return True
    return False


def check_vocab(shots, bible):
    out, vocab = [], bible.get("state_vocab", {})
    for s in shots:
        for which in ("start_state", "end_state"):
            for who, dims in _chars(s.get(which)).items():
                for dim, val in (dims or {}).items():
                    allowed = vocab.get(dim, {}).get("values")
                    if allowed and val not in allowed:
                        out.append(Issue("ERROR", "VOCAB_VIOLATION", s.get("id"),
                            f"{which}.characters.{who}.{dim}",
                            f"'{val}' is not in {allowed}"))
        for e in _events(s):
            if e.get("type") not in EVENT_TYPES:
                out.append(Issue("ERROR", "UNKNOWN_EVENT_TYPE", s.get("id"),
                    "events", f"'{e.get('type')}' not in {list(EVENT_TYPES)}"))
    return out


def check_events_explain_changes(shots, bible):
    """Every state discontinuity must be explained by a typed event in the shot that
    contains it, or across the boundary by an explicit non-CONTINUOUS boundary."""
    out = []
    material = {k for k, v in bible.get("state_vocab", {}).items() if v.get("material")}

    for i, s in enumerate(shots):
        sid = s.get("id")
        ss, es = s.get("start_state") or {}, s.get("end_state") or {}

        # WITHIN a shot: changes are expected, but must be evented
        for who in _pop(ss) | _pop(es):
            if who in _pop(es) - _pop(ss) and not _has(s, type="ENTER", entity=who):
                out.append(Issue("ERROR", "POPULATION_CHANGE_WITHOUT_EVENT", sid,
                    f"end_state.population.{who}",
                    f"{who} appears during the shot with no ENTER event"))
            if who in _pop(ss) - _pop(es) and not _has(s, type="EXIT", entity=who):
                out.append(Issue("ERROR", "POPULATION_CHANGE_WITHOUT_EVENT", sid,
                    f"end_state.population.{who}",
                    f"{who} leaves during the shot with no EXIT event"))

        for who in set(_chars(ss)) & set(_chars(es)):
            a, b = _chars(ss)[who] or {}, _chars(es)[who] or {}
            if a.get("zone") != b.get("zone"):
                if not _has(s, type="MOVE", entity=who,
                            from_zone=a.get("zone"), to_zone=b.get("zone")):
                    out.append(Issue("ERROR", "EVENT_DOES_NOT_EXPLAIN_DELTA", sid,
                        f"characters.{who}.zone",
                        f"{who} moves {a.get('zone')} -> {b.get('zone')} but no MOVE event "
                        f"matches that exact from/to"))
            # every OTHER material dimension also needs a typed event (Option B)
            for dim in material:
                if dim == "zone":
                    continue
                if a.get(dim) and b.get(dim) and a[dim] != b[dim]:
                    if not _has(s, type="STATE_CHANGE", entity=who, field=dim,
                                **{"from": a[dim], "to": b[dim]}):
                        out.append(Issue("ERROR", "EVENT_DOES_NOT_EXPLAIN_DELTA", sid,
                            f"characters.{who}.{dim}",
                            f"{who}.{dim} {a[dim]} -> {b[dim]} with no matching "
                            f"STATE_CHANGE event"))

        # the prop SET may not change: no CREATE/REMOVE event exists in v1
        if set(_props(ss)) != set(_props(es)):
            out.append(Issue("ERROR", "PROP_SET_CHANGED", sid, "props",
                f"props appear/disappear within the shot "
                f"({sorted(set(_props(ss)) ^ set(_props(es)))}); v1 has no CREATE/REMOVE "
                f"event, so the prop set must be constant"))
        for obj in set(_props(ss)) & set(_props(es)):
            a, b = _props(ss)[obj], _props(es)[obj]
            if a != b and not (_has(s, type="TRANSFER", object=obj, **{"from": a, "to": b})
                               or _has(s, type="STATE_CHANGE", entity=obj,
                                       **{"from": a, "to": b})):
                out.append(Issue("ERROR", "EVENT_DOES_NOT_EXPLAIN_DELTA", sid,
                    f"props.{obj}",
                    f"{obj} changes {a} -> {b} but no TRANSFER/STATE_CHANGE event "
                    f"matches that exact from/to"))

        # ACROSS the boundary into this shot
        if i == 0:
            continue
        prev = shots[i - 1]
        pe = prev.get("end_state") or {}
        btype = (s.get("boundary") or {}).get("type", "CONTINUOUS")
        if btype != "CONTINUOUS":
            continue

        for who in _pop(ss) - _pop(pe):
            if not _has(s, type="ENTER", entity=who):
                out.append(Issue("ERROR", "POPULATION_CHANGE_WITHOUT_EVENT", sid,
                    f"start_state.population.{who}",
                    f"{who} is absent at {prev.get('id')} end and present here with no "
                    f"ENTER event — this is a materialisation"))
        for who in _pop(pe) - _pop(ss):
            if not _has(prev, type="EXIT", entity=who):
                out.append(Issue("ERROR", "POPULATION_CHANGE_WITHOUT_EVENT", sid,
                    f"start_state.population.{who}",
                    f"{who} vanishes between {prev.get('id')} and here with no EXIT event"))

        for who in set(_chars(pe)) & set(_chars(ss)):
            a, b = _chars(pe)[who] or {}, _chars(ss)[who] or {}
            for dim in material:
                if a.get(dim) and b.get(dim) and a[dim] != b[dim]:
                    out.append(Issue("ERROR", "MATERIAL_JUMP_ACROSS_CUT", sid,
                        f"characters.{who}.{dim}",
                        f"{who}.{dim} {a[dim]} -> {b[dim]} across a CONTINUOUS cut. "
                        f"The transition is never shown; it must happen inside a shot."))
        if set(_props(pe)) != set(_props(ss)):
            out.append(Issue("ERROR", "PROP_SET_CHANGED", sid, "props",
                f"prop set changes across a CONTINUOUS cut "
                f"({sorted(set(_props(pe)) ^ set(_props(ss)))})"))
        for obj in set(_props(pe)) & set(_props(ss)):
            if _props(pe)[obj] != _props(ss)[obj]:
                out.append(Issue("ERROR", "MATERIAL_JUMP_ACROSS_CUT", sid,
                    f"props.{obj}",
                    f"prop '{obj}' {_props(pe)[obj]} -> {_props(ss)[obj]} across a cut"))
    return out


def check_boundaries(shots, bible, ep):
    out = []
    allowed = set(bible["modes"][ep["mode"]].get("allowed_boundaries", ["CONTINUOUS"]))
    for s in shots[1:]:
        b = s.get("boundary") or {}
        t = b.get("type", "CONTINUOUS")
        if t not in BOUNDARY_TYPES:
            out.append(Issue("ERROR", "UNKNOWN_BOUNDARY", s.get("id"), "boundary.type",
                f"'{t}' is not a boundary type"))
        elif t not in allowed:
            out.append(Issue("ERROR", "BOUNDARY_NOT_PERMITTED", s.get("id"),
                "boundary.type", f"'{t}' not allowed in {ep['mode']} ({sorted(allowed)})"))
        elif t != "CONTINUOUS" and not (b.get("reason") or "").strip():
            out.append(Issue("ERROR", "BOUNDARY_WITHOUT_REASON", s.get("id"),
                "boundary.reason", f"'{t}' requires a narrative reason"))
        elif t != "CONTINUOUS":
            out.append(Issue("WARN", "DELIBERATE_DISCONTINUITY", s.get("id"),
                "boundary", f"{t}: {b['reason'][:60]}"))
    return out


REQUIRED_CHAR_DIMS = ("awareness", "posture", "zone")


def check_completeness(shots, ep, bible):
    """A plan must not pass by saying LESS. Every representation of who is present must
    agree: shot.cast, population, characters.keys() and events[].entity."""
    out = []
    req_visual = set(bible.get("visual_vocab", {})) | {"camera_setup_id"}
    for s in shots:
        sid = s.get("id")
        for which in ("start_state", "end_state"):
            st = s.get(which) or {}
            pop, chars = _pop(st), _chars(st)
            if not st.get("location_id"):
                out.append(Issue("ERROR", "SHOT_WITHOUT_LOCATION_ID", sid,
                    f"{which}.location_id", "location is continuity authority; it is required"))
            if pop != set(chars):
                out.append(Issue("ERROR", "REPRESENTATION_MISMATCH", sid,
                    f"{which}.population", f"population {sorted(pop)} != "
                    f"characters {sorted(chars)}"))
            if not pop:
                out.append(Issue("ERROR", "EMPTY_POPULATION", sid,
                    f"{which}.population", "no characters declared"))
            for who, dims in chars.items():
                missing = [d for d in REQUIRED_CHAR_DIMS if not (dims or {}).get(d)]
                if missing:
                    out.append(Issue("ERROR", "INCOMPLETE_CHARACTER_STATE", sid,
                        f"{which}.characters.{who}", f"missing {missing}"))
            vis = st.get("visual") or {}
            missing_v = [k for k in req_visual if not vis.get(k)]
            if missing_v:
                out.append(Issue("ERROR", "INCOMPLETE_VISUAL_STATE", sid,
                    f"{which}.visual", f"missing {missing_v}"))
        # everyone referenced anywhere must be a declared episode cast member
        referenced = set(s.get("cast") or []) | _pop(s.get("start_state")) | \
                     _pop(s.get("end_state")) | \
                     {e.get("entity") for e in _events(s) if e.get("entity")}
        for who in referenced - set(ep["cast"]):
            if who in bible.get("cast", {}) or who not in (bible.get("props") or {}):
                out.append(Issue("ERROR", "ENTITY_NOT_IN_EPISODE_CAST", sid, "cast/state/events",
                    f"'{who}' is referenced but not in the episode cast {ep['cast']}"))
    return out


def check_entities(shots, ep, bible):
    out, known = [], set(bible["cast"])
    for s in shots:
        for k in s.get("cast", []):
            if k not in known:
                out.append(Issue("ERROR", "UNKNOWN_CAST", s.get("id"), "cast",
                    f"'{k}' is not in the bible"))
            elif k not in ep["cast"]:
                out.append(Issue("ERROR", "CAST_NOT_IN_EPISODE", s.get("id"), "cast",
                    f"'{k}' is not in this episode's cast"))
        if not s.get("start_state") or not s.get("end_state"):
            out.append(Issue("ERROR", "MISSING_STATE", s.get("id"), "state",
                "missing start_state or end_state"))
    return out


def check_locations(shots, ep):
    """v1 limitation, enforced explicitly rather than assumed by the schema."""
    out = []
    declared = ep.get("locations") or ([ep["location"]] if ep.get("location") else [])
    seen = set()
    for s in shots:
        lid = (s.get("start_state") or {}).get("location_id")
        if not lid:
            out.append(Issue("WARN", "SHOT_WITHOUT_LOCATION_ID", s.get("id"),
                "start_state.location_id", "shot does not declare its location"))
            continue
        seen.add(lid)
        if declared and lid not in declared:
            out.append(Issue("ERROR", "LOCATION_NOT_DECLARED", s.get("id"),
                "start_state.location_id", f"'{lid}' not in episode locations {declared}"))
    if len(seen) > 1:
        out.append(Issue("ERROR", "MULTI_LOCATION_NOT_SUPPORTED", "-", "locations",
            f"v1 supports one location per episode; found {sorted(seen)}"))
    return out


def check_requirements(shots, ep, results):
    """Prove each brief requirement from the PLAN, never from the planner's claim.

    The planner declares SATISFIED or DECLINED; we verify independently. Asking the
    planner to decide what must be audited while also asking it to pass the audit is how
    R02 returned four WIDE shots against a brief demanding camera variety.
    """
    out = []
    results = results or {}
    for r in ep.get("requirements") or []:
        rid, rtype = r["id"], r["type"]
        claim = (results.get(rid) or {}).get("status")
        params = r.get("params") or {}
        proven, detail = None, ""

        if rtype == "CAMERA_VARIATION":
            need = set(params.get("required_sizes") or [])
            actual = {(s.get("start_state") or {}).get("visual", {}).get("shot_size")
                      for s in shots}
            proven = need <= actual
            detail = f"required {sorted(need)}, plan has {sorted(a for a in actual if a)}"
        elif rtype == "PROP_TRANSFER":
            obj, frm, to = params.get("object"), params.get("from"), params.get("to")
            proven = any(e.get("type") == "TRANSFER" and e.get("object") == obj
                         and e.get("from") == frm and e.get("to") == to
                         for s in shots for e in _events(s))
            detail = f"required TRANSFER {obj} {frm}->{to}"
        elif rtype == "CHARACTER_PRESENT":
            who = params.get("entity")
            proven = any(who in _pop(s.get("start_state")) for s in shots)
            detail = f"required {who} to appear"
        else:
            out.append(Issue("WARN", "REQUIREMENT_TYPE_UNKNOWN", "-", f"requirements.{rid}",
                f"no verifier for type '{rtype}'"))
            continue

        if claim == "SATISFIED" and not proven:
            out.append(Issue("ERROR", "REQUIREMENT_FALSE_CLAIM", "-", f"requirements.{rid}",
                f"planner claimed SATISFIED but the plan does not show it: {detail}"))
        elif proven and claim == "DECLINED":
            out.append(Issue("WARN", "REQUIREMENT_UNDERCLAIMED", "-", f"requirements.{rid}",
                f"declined but actually satisfied: {detail}"))
        elif not proven and r.get("strength", "MUST") == "MUST":
            reason = (results.get(rid) or {}).get("reason", "")
            out.append(Issue("ERROR", "REQUIREMENT_NOT_MET", "-", f"requirements.{rid}",
                f"MUST requirement unmet: {detail}"
                + (f" (planner said: {reason[:60]})" if reason else
                   " and the planner did not declare it declined")))
    return out


def validate(shots, ep, bible, requirement_results=None):
    return (check_completeness(shots, ep, bible)
            + check_entities(shots, ep, bible)
            + check_vocab(shots, bible)
            + check_boundaries(shots, bible, ep)
            + check_events_explain_changes(shots, bible)
            + check_locations(shots, ep)
            + check_requirements(shots, ep, requirement_results))


def report(issues):
    for i in issues:
        mark = "x" if i.severity == "ERROR" else "!"
        print(f"  {mark} {i.severity:5s} {i.code:34s} {i.shot_id}: {i.message}")
    if not issues:
        print("  ok  plan is continuity-clean")
    return sum(1 for i in issues if i.severity == "ERROR")
