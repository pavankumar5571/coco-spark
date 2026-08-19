"""Deterministic camera compiler.

The planner declares narrative INTENT — what each shot is FOR (coverage_role). This
assigns shot_size, camera_angle and camera_setup_id from mode policy plus explicit
requirements.

Rationale, learned at a cost of Rs 0.41: given a MUST CAMERA_VARIATION requirement, an
enum restricting shot_size, and a repair prompt naming the exact failure and listing the
required values, Gemini returned MEDIUM and MEDIUM_WIDE twice. Individually legal, and
never satisfying the cross-shot coverage constraint. "Among N shots include at least one
WIDE and one CLOSE" is arithmetic, not storytelling. Code owns it now, so the requirement
cannot be forgotten: the same function that assigns cameras is responsible for meeting it.
"""
from __future__ import annotations


class Unsatisfiable(Exception):
    pass


def _coverage(bible, mode):
    return bible["modes"][mode].get("coverage", {})


def precheck(ep, bible):
    """Prove the request is satisfiable BEFORE planning or generation."""
    cov = _coverage(bible, ep["mode"])
    n = ep["shots"]
    for r in ep.get("requirements") or []:
        if r["type"] != "CAMERA_VARIATION":
            continue
        need = set((r.get("params") or {}).get("required_sizes") or [])
        if len(need) > n:
            raise Unsatisfiable(
                f"requirement '{r['id']}' needs {len(need)} distinct sizes {sorted(need)} "
                f"but the episode has only {n} shots")
        reachable = {s for sizes in cov.values() for s in sizes}
        missing = need - reachable
        if missing:
            raise Unsatisfiable(
                f"requirement '{r['id']}' needs {sorted(missing)}, which no coverage role "
                f"in mode {ep['mode']} can produce (reachable: {sorted(reachable)})")


def required_roles(ep, bible):
    """Translate coverage arithmetic into the semantic choice the planner CAN make.

    The planner cannot reliably satisfy 'include a CLOSE shot'. It can reliably choose
    'this shot is a REACTION'. So code computes which roles yield the required sizes and
    asks for those instead. Arithmetic stays in code; intent stays with the LLM.
    """
    cov = _coverage(bible, ep["mode"])
    out = []
    for r in ep.get("requirements") or []:
        if r["type"] != "CAMERA_VARIATION":
            continue
        for size in (r.get("params") or {}).get("required_sizes") or []:
            roles = sorted(role for role, sizes in cov.items() if size in sizes)
            if roles:
                out.append((size, roles))
    return out


def assign(shots, ep, bible):
    """Assign visual state to every shot, satisfying MUST coverage requirements."""
    cov = _coverage(bible, ep["mode"])
    default_angle = "EYE_LEVEL"

    # 1. preferred size from each shot's declared role
    sizes = []
    for s in shots:
        role = s.get("coverage_role") or "SUBJECT"
        opts = cov.get(role) or ["MEDIUM"]
        sizes.append(opts[0])

    # 2. satisfy MUST coverage by promoting the shot whose role best tolerates it
    for r in ep.get("requirements") or []:
        if r["type"] != "CAMERA_VARIATION" or r.get("strength", "MUST") != "MUST":
            continue
        for want in (r.get("params") or {}).get("required_sizes") or []:
            if want in sizes:
                continue
            best = None
            for i, s in enumerate(shots):
                opts = cov.get(s.get("coverage_role") or "SUBJECT") or []
                if want in opts:
                    rank = opts.index(want)
                    if best is None or rank < best[1]:
                        best = (i, rank)
            if best is None:
                raise Unsatisfiable(
                    f"cannot place {want}: no shot's coverage role permits it")
            sizes[best[0]] = want

    # 3. camera_setup_id: a stable label per (location, size, angle). Same physical
    #    setup keeps the same id, which is what gates predecessor-pixel inheritance.
    out = []
    for s, size in zip(shots, sizes):
        loc = (s.get("start_state") or {}).get("location_id", "LOC")
        setup = f"{loc}_{size}_{default_angle}".upper()
        vis = {"camera_setup_id": setup, "shot_size": size,
               "camera_angle": default_angle}
        for which in ("start_state", "end_state"):
            s.setdefault(which, {})["visual"] = dict(vis)
        s["camera"] = f"Locked static camera. {size.replace('_',' ').title()} shot, eye level."
        out.append(s)
    return out
