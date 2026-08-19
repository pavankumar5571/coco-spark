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


def _subject_name(ids, bible):
    """Human-readable subject, never a raw id.

    "framed on coco" and "framed on cottage_night" were internal identifiers leaking into
    text sent to a generator — the same class of defect as the planner's camera prose,
    just quieter.
    """
    names = []
    for i in ids:
        c = (bible.get("cast") or {}).get(i)
        loc = (bible.get("locations") or {}).get(i)
        names.append((c or {}).get("name") or (loc or {}).get("name")
                     or str(i).replace("_", " "))
    if not names:
        return "the scene"
    return " and ".join(names)


def _phrase(bible, dim, value, possessive):
    """One typed value as English, from the bible lexicon. Falls back to the label."""
    tpl = ((bible.get("phrasing") or {}).get(dim) or {}).get(value)
    if not tpl:
        return str(value).replace("_", " ").lower()
    return tpl.replace("{pos}", possessive)


def _suppressed(bible, st):
    """Which dimensions this character's state makes redundant.

    Data, not a special case in code: "asleep, looking sleepy" is not a bug in the
    renderer, it is two fields saying the same thing, and the bible is where that
    relationship belongs.
    """
    out = set()
    for rule in bible.get("phrasing_suppress") or []:
        if all(st.get(k) == v for k, v in (rule.get("when") or {}).items()):
            out.update(rule.get("omit") or [])
    return out


def _compose(shot, size, angle, subj, bible):
    """The composition to produce, rendered deterministically from TYPED state alone.

    Every clause is derived, never quoted from the planner, so nothing here can describe a
    change, a movement or a transition — it only has access to the state at the START of
    the shot. The enums stay the source of truth; the generator gets clean prose, because
    its consumer is a language model rather than a parser.
    """
    who = []
    start = shot.get("start_state") or {}
    chars = start.get("characters") or {}
    for cid in sorted(chars):
        st = chars[cid]
        c = (bible.get("cast", {}).get(cid) or {})
        name = c.get("name", cid)
        pos = c.get("possessive", "their")
        skip = _suppressed(bible, st)

        # posture carries the verb, so it leads; zone attaches to it directly
        parts = []
        if st.get("posture") and "posture" not in skip:
            parts.append(_phrase(bible, "posture", st["posture"], pos))
        if st.get("awareness") and "awareness" not in skip:
            parts.append(_phrase(bible, "awareness", st["awareness"], pos))
        if st.get("zone") and "zone" not in skip:
            parts.append(_phrase(bible, "zone", st["zone"], pos))
        head = f"{name} " + " ".join(parts) if parts else name

        tail = [_phrase(bible, d, st[d], pos)
                for d in ("facing", "expression")
                if st.get(d) and d not in skip]
        who.append(head + (", " + ", ".join(tail) if tail else "") + ".")

    frame = (f"{size.replace('_', ' ').title()} shot, "
             f"{angle.replace('_', ' ').lower()}, framed on {subj}.")
    if who:
        frame += " " + " ".join(who)
    return frame


def assign(shots, ep, bible, frozen=0):
    """Assign visual state to every shot, satisfying MUST coverage requirements.

    `frozen` is a count of leading shots that have ALREADY BEEN GENERATED and accepted.
    Their framing is a fact about footage that exists, not a decision still open, so it is
    read rather than chosen. Reassigning it would change their identity hash and stale
    paid footage — which is precisely what append-only exists to prevent.

    Frozen sizes still COUNT toward coverage requirements. An episode that already opens
    on a WIDE has satisfied its WIDE, and demanding another one from the continuation
    would distort the story to re-prove something already on screen.
    """
    cov = _coverage(bible, ep["mode"])
    default_angle = "EYE_LEVEL"

    # 1. preferred size from each shot's declared role — except frozen shots, whose size
    #    is whatever they were actually generated with
    sizes = []
    for i, s in enumerate(shots):
        if i < frozen:
            sizes.append(((s.get("start_state") or {}).get("visual") or {}).get("shot_size")
                         or "MEDIUM")
            continue
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
                if i < frozen:
                    continue                      # cannot repromote existing footage
                opts = cov.get(s.get("coverage_role") or "SUBJECT") or []
                if want in opts:
                    rank = opts.index(want)
                    if best is None or rank < best[1]:
                        best = (i, rank)
            if best is None:
                raise Unsatisfiable(
                    f"cannot place {want}: no shot's coverage role permits it")
            sizes[best[0]] = want

    # 3. PHYSICAL setup and COMPOSITION are different things and must not be conflated.
    #    'CLOSE on Coco' and 'CLOSE on Pip' share a location, size and angle. Collapsing
    #    them into one id let the continuity compiler conclude nothing had changed and
    #    inherit Coco's pixels into a shot meant to open on Pip — a valid-looking but
    #    objectively wrong frame.
    out = []
    for i, (s, size) in enumerate(zip(shots, sizes)):
        if i < frozen:
            out.append(s)                          # already generated; nothing to decide
            continue
        loc = (s.get("start_state") or {}).get("location_id", "LOC")
        setup = f"{loc}_AXIS_A".upper()                       # physical position
        foc = s.get("focus") or {}
        ftype = foc.get("type", "GROUP")
        fids = "+".join(sorted(foc.get("ids") or s.get("cast") or []))
        composition = f"{ftype}:{fids}".upper()               # what the frame is about
        vis = {"camera_setup_id": setup, "composition_id": composition,
               "shot_size": size, "camera_angle": default_angle}
        for which in ("start_state", "end_state"):
            s.setdefault(which, {})["visual"] = dict(vis)
        subj = _subject_name(foc.get("ids") or s.get("cast") or [], bible)
        s["camera"] = (f"Locked static camera. {size.replace('_',' ').title()} shot at eye "
                       f"level, framed on {subj}.")
        # DESTINATION STATE ONLY. This used to append the planner's free-text `frame`,
        # which is how "The camera pulls back smoothly from the close-up" reached a STILL
        # image generator — in the same prompt that told it to keep the camera identical.
        # Two contradictory instructions, both ours. A still generator needs the composition
        # to arrive at, never the move used to get there, and motion belongs exclusively to
        # the video prompt. The compiler now has no field capable of emitting camera motion,
        # so the defect cannot recur by wording.
        s["frame_compiled"] = _compose(s, size, default_angle, subj, bible)
        out.append(s)
    return out
