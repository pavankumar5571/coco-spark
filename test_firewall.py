"""Paid-call firewall. Designed by ChatGPT, implemented here.

ONE INVARIANT:
    No paid provider method may be invoked unless every deterministic precondition AND
    the full reserved cost have already passed.

The five gates (precheck, schema, camera compile, validate, preflight) are implementation
details. This tests the property they exist to guarantee: can any invalid deterministic
state cross the paid-call boundary?

Every mutation below must finish with paid_calls == 0.
Runs offline. No API key, no network, no cost.
"""
import copy, json, shutil, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

BIBLE = yaml.safe_load((ROOT / "bible.yaml").read_text())
# A fixture, deliberately NOT a production brief. This previously loaded episodes/E01.yaml,
# so the moment a real episode gained a CAMERA_VARIATION requirement the suite's positive
# control started failing — the tests were coupled to content that is supposed to change.
EP = {"id": "T01", "mode": "BEDTIME_STORY", "title": "fixture",
      "location": "cottage_night", "locations": ["cottage_night"],
      "cast": ["coco", "nana"], "shots": 2,
      "idea": "Fixture episode for the planning firewall. Never generated."}


class FakeProvider:
    """Counts paid invocations. Any call at all is a firewall breach."""
    def __init__(self): self.calls = []
    def image(self, *a, **k): self.calls.append("image"); return b"fake"
    def video(self, *a, **k): self.calls.append("video"); return b"fake"


def good_shot(sid, **kw):
    s = {
        "id": sid, "cast": ["coco", "nana"], "coverage_role": "SUBJECT",
        "frame": "f", "motion": "m", "camera": "static",
        "boundary": {"type": "CONTINUOUS"}, "events": [],
        "start_state": {
            "location_id": "cottage_night", "population": ["coco", "nana"],
            "characters": {
                "coco": {"awareness": "AWAKE", "posture": "SITTING_UP", "zone": "BED"},
                "nana": {"awareness": "AWAKE", "posture": "PERCHED", "zone": "CHAIR"}},
            "props": {},
            "visual": {"camera_setup_id": "A", "shot_size": "MEDIUM",
                       "camera_angle": "EYE_LEVEL"}},
    }
    s["end_state"] = copy.deepcopy(s["start_state"])
    s.update(kw)
    return s


def mutations():
    """Each returns (name, shots) where shots MUST be rejected."""
    m = []

    s = good_shot("s01"); s["start_state"]["population"] = ["coco"]
    m.append(("population disagrees with characters", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["nana"]["zone"] = "WINDOW"
    m.append(("zone change, no MOVE event", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["nana"]["zone"] = "WINDOW"
    s["events"] = [{"type": "MOVE", "entity": "nana", "from_zone": "BED", "to_zone": "DOOR"}]
    m.append(("MOVE event with wrong from/to", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["coco"]["awareness"] = "ASLEEP"
    m.append(("material change, no STATE_CHANGE", [s]))

    s = good_shot("s01"); s["end_state"]["props"] = {"apple": "coco"}
    m.append(("prop set changes inside a shot", [s]))

    s = good_shot("s01"); del s["start_state"]["visual"]["camera_setup_id"]
    m.append(("incomplete visual state", [s]))

    s = good_shot("s01"); del s["start_state"]["location_id"]
    m.append(("no location_id", [s]))

    s = good_shot("s01"); s["start_state"]["characters"]["coco"]["awareness"] = "kind of sleepy"
    m.append(("value outside the closed vocabulary", [s]))

    s = good_shot("s01"); s["cast"] = ["coco", "stranger"]
    m.append(("unknown entity in cast", [s]))

    a, b = good_shot("s01"), good_shot("s02")
    a["end_state"]["characters"]["coco"]["awareness"] = "DROWSY"
    a["events"] = [{"type": "STATE_CHANGE", "entity": "coco", "field": "awareness",
                    "from": "AWAKE", "to": "DROWSY"}]
    b["start_state"]["characters"]["coco"]["awareness"] = "ASLEEP"
    m.append(("material jump across a CONTINUOUS cut", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["boundary"] = {"type": "TIME_JUMP", "reason": "later"}
    m.append(("boundary type forbidden by the mode", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["start_state"]["population"] = ["coco", "nana", "pip"]
    b["start_state"]["characters"]["pip"] = {"awareness": "AWAKE", "posture": "STANDING",
                                             "zone": "RUG"}
    b["cast"] = ["coco", "nana", "pip"]
    m.append(("character materialises across the cut", [a, b]))

    # a shot in which nothing changes, coming from a shot it is identical to, is padding
    a, b = good_shot("s01"), good_shot("s02")
    m.append(("shot that changes nothing and is not a resolution", [a, b]))

    return m


def positive_progression_cases():
    """Plans the progression invariant must NOT reject. A rule that blocks padding is
    only useful if it still permits the legitimate ways a shot can hold still."""
    out = []

    a, b = good_shot("s01"), good_shot("s02")
    b["coverage_role"] = "RESOLUTION"
    out.append(("a held closing beat, explicitly typed RESOLUTION", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["start_state"]["visual"]["shot_size"] = "CLOSE"
    b["end_state"]["visual"]["shot_size"] = "CLOSE"
    out.append(("same state but the camera moves in", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["end_state"]["characters"]["coco"]["awareness"] = "ASLEEP"
    b["events"] = [{"type": "STATE_CHANGE", "entity": "coco", "field": "awareness",
                    "from": "AWAKE", "to": "ASLEEP"}]
    out.append(("held framing but the character changes inside the shot", [a, b]))

    return out


def main():
    from validate import validate
    import camera
    provider = FakeProvider()
    failures, checked = [], 0

    for name, shots in mutations():
        checked += 1
        issues = validate(shots, EP, BIBLE, {})
        errs = [i for i in issues if i.severity == "ERROR"]
        if not errs:
            failures.append(f"NOT REJECTED: {name}")
            provider.image()          # simulate what the pipeline would have done
        else:
            print(f"  blocked  {name:46s} {errs[0].code}")

    # the invariant must not reject legitimate stillness
    for name, shots in positive_progression_cases():
        checked += 1
        bad = [i for i in validate(shots, EP, BIBLE, {})
               if i.severity == "ERROR" and i.code == "SHOT_ADDS_NOTHING"]
        if bad:
            failures.append(f"FALSE POSITIVE: {name}")
        else:
            print(f"  passed   {name:46s} not padding")

    # accepted footage is never re-litigated by a rule written after it was made
    checked += 1
    a, b = good_shot("s01"), good_shot("s02")
    if [i for i in validate([a, b], EP, BIBLE, {}, frozen=2)
            if i.code == "SHOT_ADDS_NOTHING"]:
        failures.append("FALSE POSITIVE: frozen shots judged by the progression rule")
    else:
        print(f"  passed   {'frozen shots exempt from progression rule':46s} pre-generation gate only")

    # the image compiler must have no FIELD capable of carrying camera motion.
    # Asserted structurally, not as an English blacklist: whatever prose the planner
    # writes in `frame`, none of it may survive into the compiled still description.
    checked += 1
    import camera as _cam
    poison = ("The camera pulls back smoothly and pans left while zooming out to reveal "
              "a completely different room with a round rug and a picture bookshelf.")
    sp = good_shot("s01")
    sp["frame"] = poison
    sp["cast"] = ["coco"]
    sp["focus"] = {"type": "CHARACTER", "ids": ["coco"]}
    ep_one = dict(EP); ep_one["cast"] = ["coco"]; ep_one["shots"] = 1
    compiled = _cam.assign([sp], ep_one, BIBLE)[0]["frame_compiled"]
    leaked = [w for w in ("pulls back", "pans", "zooming", "round rug", "picture bookshelf")
              if w in compiled]
    if leaked:
        failures.append(f"PLANNER PROSE REACHED THE IMAGE PROMPT: {leaked}")
        provider.image()
    else:
        print(f"  blocked  {'planner camera prose in a still prompt':46s} "
              f"NO_MOTION_FIELD_IN_IMAGE_COMPILER")

    # shot sizes must compile to DIFFERENT compositions, not just different labels.
    # Without this, CLOSE and MEDIUM_WIDE differ by two words and we are merely assuming
    # the generator reads those labels the way we do.
    checked += 1
    import re as _re
    def _compiled(role):
        sh = good_shot("s01")
        sh["cast"] = ["coco"]
        sh["coverage_role"] = role          # role -> size, via mode coverage policy
        sh["focus"] = {"type": "CHARACTER", "ids": ["coco"]}
        e = dict(EP); e["cast"] = ["coco"]; e["shots"] = 1
        return _cam.assign([sh], e, BIBLE)[0]["frame_compiled"]
    close_c, wide_c = _compiled("DETAIL"), _compiled("ESTABLISH")   # CLOSE vs MEDIUM_WIDE
    # strip the size LABEL so only the described composition is compared
    strip = lambda x: _re.sub(r"^[A-Za-z ]+shot", "", x)
    if strip(close_c) == strip(wide_c):
        failures.append("SHOT SIZES COMPILE IDENTICALLY apart from their label")
        provider.image()
    else:
        print(f"  passed   {'CLOSE and MEDIUM_WIDE compile differently':46s} "
              f"beyond the label")

    # GENERIC, not per-episode: every vocabulary value the validator will accept must have
    # English to render it, or some future episode silently emits raw enum labels into a
    # paid prompt. Checking this by hand once is how it stops being true.
    checked += 1
    gaps = []
    ph = BIBLE.get("phrasing") or {}
    for dim, spec in (BIBLE.get("state_vocab") or {}).items():
        gaps += [f"phrasing.{dim}.{v}" for v in spec["values"] if v not in (ph.get(dim) or {})]
    fr = BIBLE.get("framing") or {}
    for dim, vals in (BIBLE.get("visual_vocab") or {}).items():
        gaps += [f"framing.{dim}.{v}" for v in vals if v not in (fr.get(dim) or {})]
    if gaps:
        failures.append(f"VOCABULARY WITHOUT ENGLISH: {gaps}")
    else:
        print(f"  passed   {'every vocabulary value has a phrase':46s} "
              f"no raw enums can reach a prompt")

    # the planner prompt must not name entities that belong to one episode. Showing a
    # single-cast episode examples featuring other characters is how a character
    # materialises in a scene that never cast it.
    checked += 1
    import make as _mk
    prompt_text = _mk.PLANNER_RULES + _mk.SHOT_SCHEMA
    named = [n for n in list(BIBLE.get("cast") or {}) + list(BIBLE.get("locations") or {})
             if n in prompt_text]
    if named:
        failures.append(f"PLANNER PROMPT HARDCODES ENTITIES: {named}")
    else:
        print(f"  passed   {'planner prompt names no specific entity':46s} "
              f"examples are placeholders")

    # unsatisfiable requirement must be caught before planning
    checked += 1
    try:
        camera.precheck({"mode": "SONG", "shots": 1, "cast": ["coco"],
                         "requirements": [{"id": "cv", "type": "CAMERA_VARIATION",
                                           "strength": "MUST",
                                           "params": {"required_sizes": ["WIDE", "CLOSE"]}}]},
                        BIBLE)
        failures.append("NOT REJECTED: unsatisfiable coverage requirement")
        provider.image()
    except camera.Unsatisfiable:
        print(f"  blocked  {'unsatisfiable coverage requirement':46s} UNSATISFIABLE_REQUIREMENT")

    # the control: a valid plan must NOT be rejected
    checked += 1
    a, b = good_shot("s01"), good_shot("s02")
    b["coverage_role"] = "RESOLUTION"     # a held closing beat, not accidental padding
    if [i for i in validate([a, b], EP, BIBLE, {}) if i.severity == "ERROR"]:
        failures.append("FALSE POSITIVE: a valid plan was rejected")
    else:
        print(f"  passed   {'valid plan (control)':46s} clean")

    # ── composition vs physical setup ────────────────────────────────────────
    import camera as _cam
    from make import reference_policy as _pol

    def _s(sid, role, ids, size_role=None):
        import copy
        s = {"id": sid, "cast": ["coco", "nana"], "coverage_role": role,
             "focus": {"type": "CHARACTER", "ids": ids}, "frame": "x", "motion": "m",
             "boundary": {"type": "CONTINUOUS"}, "events": [],
             "start_state": {"location_id": "cottage_night",
                "population": ["coco", "nana"],
                "characters": {
                    "coco": {"awareness": "AWAKE", "posture": "SITTING_UP", "zone": "BED"},
                    "nana": {"awareness": "AWAKE", "posture": "PERCHED", "zone": "CHAIR"}},
                "props": {}}}
        s["end_state"] = copy.deepcopy(s["start_state"])
        return s

    # identical size and angle, DIFFERENT subject -> must not inherit pixels
    ep2 = {"mode": "BEDTIME_STORY", "shots": 2, "cast": ["coco", "nana"],
           "requirements": []}
    pair = _cam.assign([_s("s01", "REACTION", ["coco"]),
                        _s("s02", "REACTION", ["nana"])], ep2, BIBLE)
    v1, v2 = pair[0]["start_state"]["visual"], pair[1]["start_state"]["visual"]
    same_frame = (v1["shot_size"] == v2["shot_size"]
                  and v1["camera_setup_id"] == v2["camera_setup_id"])
    pol = _pol(pair[0], pair[1], BIBLE)[0]
    checked += 1
    if same_frame and pol == "PREDECESSOR_PIXELS":
        failures.append("NOT REJECTED: same size/setup, different subject -> inheritance")
        provider.image()
    else:
        print(f"  blocked  {'CLOSE on coco -> CLOSE on nana (same setup)':46s} "
              f"{pol}")

    # the compiled framing must not contradict the assigned camera
    checked += 1
    compiled = pair[1].get("frame_compiled", "")
    if "identical" in compiled.lower() or not compiled:
        failures.append("NOT REJECTED: compiled frame text missing or self-contradictory")
    else:
        print(f"  passed   {'compiled framing matches assigned camera':46s} "
              f"{compiled[:38]}...")

    print(f"\n  {checked} cases | paid calls made: {len(provider.calls)}")
    if failures or provider.calls:
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("  FIREWALL HELD — no deterministic defect reached a paid call")


if __name__ == "__main__":
    main()
