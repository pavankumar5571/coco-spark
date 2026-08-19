#!/usr/bin/env python3
"""Generic episode pipeline. Nothing here is specific to one episode.

    make.py plan     E01    LLM: brief + bible -> out/E01/shots.json   (~Rs 1)
    make.py portraits       canonical identity anchors, channel-wide, generated once
    make.py frames   E01    first frames                               (~Rs 3.5 each)
    make.py video    E01    clips from frames                          (~Rs 18 each)
    make.py assemble E01    -> out/E01/episode.mp4

Every stage resumes: an artifact that exists is never regenerated, so a failure costs
only the stage that broke. Spend is tracked append-only against a hard cap.

The continuity rules learned from production are enforced in the PLANNER prompt, so
every episode gets them automatically rather than by hand-editing shots.
"""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

import yaml

import config as C
import camera
import qc
from compile_prompt import veo_constraint_clause
from schema import shot_plan_schema
from validate import validate, report

ROOT = Path(__file__).parent
OUT = ROOT / "out"
BIBLE = yaml.safe_load((ROOT / "bible.yaml").read_text())
PORTRAITS = OUT / "portraits"
PORTRAITS.mkdir(parents=True, exist_ok=True)
LEDGER = OUT / "ledger.json"


SOURCE_FILES = ("make.py", "validate.py", "camera.py", "schema.py", "config.py",
                "bible.yaml")


def build_revision():
    """Identify the exact executable logic authorising a paid call.

    Not part of continuity — part of accountability. After a bad generation we must be
    able to say which code approved it. A green test suite on tree A means nothing if the
    provider call ran from tree B.
    """
    import subprocess
    def git(*a):
        try:
            return subprocess.run(("git", *a), cwd=ROOT, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    # DIRTY means the EXECUTABLE LOGIC differs from the commit — not that generated
    # artifacts changed. Checking the whole tree conflated the two and blocked a paid run
    # simply because the pipeline had just produced the frame it was about to use.
    src_dirty = bool(git("status", "--porcelain", "--", *SOURCE_FILES))
    return {
        "commit": git("rev-parse", "HEAD") or "unknown",
        "dirty": src_dirty,
        "tag": git("describe", "--tags", "--exact-match") or None,
        "sources": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()[:16]
                    for f in SOURCE_FILES if (ROOT / f).exists()},
    }


def input_hash(**parts):
    """Identity of the inputs that produced an artifact. If any changes, the artifact
    is stale and must be recomputed — existence alone proves nothing."""
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def sha_file(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def write_atomic(dest: Path, data: bytes):
    """A process dying mid-write must never look like a completed artifact."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    if tmp.stat().st_size == 0:
        tmp.unlink(); raise RuntimeError(f"refusing to commit empty artifact {dest.name}")
    tmp.replace(dest)


def usable(dest: Path, prov_path: Path, expect_hash: str):
    """Resume requires ALL of: artifact exists, provenance COMPLETE, input hash matches,
    checksum matches. Anything else recomputes."""
    if not dest.exists() or not prov_path.exists():
        return False, "no artifact/provenance"
    try:
        pv = json.loads(prov_path.read_text())
    except Exception:
        return False, "unreadable provenance"
    if pv.get("status") != "COMPLETE":
        return False, f"status={pv.get('status')}"
    if pv.get("input_hash") != expect_hash:
        return False, "inputs changed since it was made"
    if pv.get("sha") != sha_file(dest):
        return False, "checksum mismatch (partial or altered file)"
    return True, "valid"


class RefResolution:
    """One resolution, consumed by BOTH the identity hash and the paid request.

    Previously frame_identity() chose the predecessor source by existence while
    stage_frames() independently PROVED usability. A stale-but-present tail was therefore
    hashed as the reference while the actual request used the predecessor frame — the
    provenance described a request that never happened. Same class as the duplicated
    preflight hash: duplicated decisions drift. The duplicated decision here was which
    predecessor artifact is authoritative.
    """
    def __init__(self, paths, ref_ids, error=None):
        self.paths, self.ref_ids, self.error = paths, ref_ids, error


def resolve_frame_refs(d, shots, idx, bible, loc, policy):
    """Resolve the exact ordered references for one shot, proving each one."""
    shot = shots[idx]
    paths, ref_ids = [], []

    for key in shot["cast"]:                                # identity anchors FIRST
        pth = PORTRAITS / f"{key}.png"
        ok, why = usable(pth, PORTRAITS / f"{key}.provenance.json",
                         input_hash(character=bible["cast"][key],
                                    style=bible["style_lock"], model=C.IMAGE_MODEL,
                                    aspect=C.IMAGE_ASPECT))
        if not ok:
            return RefResolution([], [], f"portrait '{key}' not provably current ({why})")
        paths.append(pth); ref_ids.append(("identity", key, sha_file(pth)))

    if idx == 0 or policy == "CANONICAL_ONLY":
        return RefResolution(paths, ref_ids)

    prev_id = shots[idx - 1]["id"]
    tail = d / "transitions" / f"{prev_id}_LAST.png"
    src_clip = d / "clips" / f"{prev_id}.mp4"
    tail_ok, tail_why = usable(
        tail, d / "transitions" / f"{prev_id}_LAST.provenance.json",
        input_hash(source_clip_sha=sha_file(src_clip) if src_clip.exists() else None,
                   extractor="ffmpeg-sseof-0.1-v1"))

    if policy == "PREDECESSOR_PIXELS":
        # FAIL CLOSED. The compiler concluded this frame carries no new information and
        # should BE the predecessor pixels. Silently generating an independent
        # replacement reintroduces the very cut drift this policy exists to remove.
        if not tail_ok:
            return RefResolution([], [], f"PREDECESSOR_PIXELS requires the exact "
                                         f"predecessor tail, which is unavailable "
                                         f"({tail_why}). Render or repair {prev_id} first.")
        return RefResolution(paths, ref_ids + [("inherited", prev_id, sha_file(tail))])

    # TEMPORAL_REFERENCE may fall back to a PROVEN predecessor frame
    if tail_ok:
        paths.append(tail); ref_ids.append(("temporal", prev_id, sha_file(tail)))
        return RefResolution(paths, ref_ids)
    pframe = d / "frames" / f"{prev_id}.png"
    _, pwant = frame_identity_from(shots, idx - 1, d, bible, loc)
    pok, pwhy = usable(pframe, d / "frames" / f"{prev_id}.provenance.json", pwant)
    if not pok:
        return RefResolution([], [], f"no proven temporal reference (tail {tail_why}; "
                                     f"{prev_id} frame {pwhy})")
    paths.append(pframe); ref_ids.append(("temporal", prev_id, sha_file(pframe)))
    return RefResolution(paths, ref_ids)


# Only the parts of the bible that can change a FIRST FRAME. visual_constraints and the
# per-mode video policy affect the video prompt and cannot alter an image, so hashing them
# invalidated valid frames — the same over-broad-guard mistake as checking the whole
# working tree for source cleanliness.
FRAME_BIBLE_KEYS = ("cast", "locations", "style_lock", "state_vocab", "visual_vocab")


def frame_identity(shot, bible, loc, ref_ids):
    """Identity of a first frame as a paid request. Takes ALREADY-RESOLVED references."""
    return input_hash(shot=shot,
                      bible={k: bible.get(k) for k in FRAME_BIBLE_KEYS},
                      model=C.IMAGE_MODEL, aspect=C.IMAGE_ASPECT, loc=loc,
                      refs=ref_ids, compiler=C.FRAME_COMPILER_VERSION)


def frame_identity_from(shots, idx, d, bible, loc):
    """Convenience: resolve then hash, for callers that only need the expected hash."""
    pol = reference_policy(shots[idx - 1] if idx else None, shots[idx], bible)[0]
    r = resolve_frame_refs(d, shots, idx, bible, loc, pol)
    return r, frame_identity(shots[idx], bible, loc, r.ref_ids)


def ep_dir(eid): 
    d = OUT / eid
    for sub in ("frames", "clips", "transitions"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def load_ep(eid):
    p = ROOT / "episodes" / f"{eid}.yaml"
    if not p.exists():
        sys.exit(f"no brief at {p}")
    return yaml.safe_load(p.read_text())


def client():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not set")
    genai, _, _ = _sdk()
    return genai.Client(api_key=key)


def _sdk():
    """Import the paid-call SDKs on demand.

    Reporting stages (`verify`, `costs`) and QC must run on any machine — including one
    with no provider SDK installed. Importing google-genai/Pillow at module scope made
    reading the ledger depend on the ability to spend money.
    """
    from google import genai
    from google.genai import types
    from PIL import Image
    return genai, types, Image


def ledger():
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {"spent_inr": 0.0, "ops": []}


SHARED_KINDS = {"portrait"}          # channel-wide assets, generated once, used by every episode


def op_episode(op):
    """Attribute one ledger op to an episode, from data the op already carries.

    Deterministic and convention-free: it reads the structure of `detail`, never a list of
    known episode names, so a new episode id needs no code change. Legacy rows written
    before episodes existed resolve to UNATTRIBUTED rather than being silently folded into
    whichever episode happens to be reported.
    """
    if op.get("episode"):
        return op["episode"]
    what, _, rest = op.get("detail", "").partition(":")
    if what in SHARED_KINDS:
        return "SHARED"
    head, slash, _ = rest.partition("/")
    if slash:                                # frame:E01/s01, clip:E01/s01
        return head
    if op.get("kind") == "llm" and rest:     # plan:E01
        return rest
    return "UNATTRIBUTED"


def op_spent(op):
    """What this op currently commits. A released hold commits nothing."""
    return 0.0 if op.get("state") == "RELEASED" else float(op.get("inr", 0.0))


def reserve(kind, detail, inr):
    """Hold the FULL safety-margined cost BEFORE the provider is invoked.

    The previous pattern checked a raw estimate, called Google, and applied the safety
    margin afterwards — so a call could be authorised, billed by the provider, and only
    then discovered to exceed the cap. Money must be committed locally before it can be
    committed remotely.
    """
    worst = inr * getattr(C, "SAFETY_MARGIN", 1.0)
    L = ledger()
    if L["spent_inr"] + worst > C.BUDGET_INR:
        sys.exit(f"  BUDGET STOP: reserving {worst:.2f} on top of {L['spent_inr']:.2f} "
                 f"would exceed the cap {C.BUDGET_INR}. Provider NOT called.")
    L["spent_inr"] += worst
    op = {"kind": kind, "detail": detail, "inr": worst, "reserved": worst,
          "state": "RESERVED", "at": time.strftime("%F %T")}
    op["episode"] = op_episode(op)
    L["ops"].append(op)
    LEDGER.write_text(json.dumps(L, indent=2))
    print(f"    reserved {worst:.2f}   total {L['spent_inr']:.2f}/{C.BUDGET_INR}")
    return len(L["ops"]) - 1


def settle(idx, actual=None):
    """Mark a reservation spent at its ACTUAL cost, releasing the unused safety margin.

    The margin exists to guarantee the cap is never breached in the window between
    authorising a call and learning what it cost. Once the call has completed that window
    is closed, so continuing to hold the margin is not caution — it is a phantom charge.
    Left uncorrected it burned 1.5x the real cost of every op against the cap, and made
    "how much did this episode cost" unanswerable.
    """
    L = ledger()
    op = L["ops"][idx]
    if actual is None:                       # call failed -> give the whole hold back
        L["spent_inr"] -= op["inr"]
        op["inr"], op["state"] = 0.0, "RELEASED"
    else:
        L["spent_inr"] += actual - op["inr"]
        op["inr"], op["state"] = actual, "SPENT"
    LEDGER.write_text(json.dumps(L, indent=2))


def charge(kind, detail, inr):
    """Reserve-then-settle in one step, for calls that cannot partially fail."""
    idx = reserve(kind, detail, inr)
    settle(idx, inr)


def gen_image(cl, prompt, refs, dest, kind="image", detail=""):
    """Reserve BEFORE the provider is invoked. The image path previously called Google
    first and charged afterwards — the same budget race already fixed for video."""
    res_idx = reserve(kind, detail or dest.name, C.INR_PER_IMAGE)
    try:
        return _gen_image_inner(cl, prompt, refs, dest, res_idx)
    except BaseException:
        settle(res_idx, None)          # any failure releases the hold
        raise


def _gen_image_inner(cl, prompt, refs, dest, res_idx):
    _, types, Image = _sdk()
    resp = cl.models.generate_content(
        model=C.IMAGE_MODEL,
        contents=[Image.open(p) for p in refs] + [prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=C.IMAGE_ASPECT),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None):
            write_atomic(dest, part.inline_data.data)
            settle(res_idx, C.INR_PER_IMAGE)
            print(f"    -> {dest.name}  {Image.open(dest).size}")
            return
    raise RuntimeError(f"no image returned for {dest.name}")


# ─────────────────────────────── plan ────────────────────────────────
PLANNER_RULES = """
HARD CONSTRAINTS. These come from production failures.

1. CONNECTED STATES, NOT PICTURES. The shots are one continuous scene. Each shot must
   begin exactly where the previous one ended.
2. EVERY CHANGE NEEDS AN EVENT. State says what is true; events say why it changed.
   A character appearing needs ENTER. Leaving needs EXIT. Changing zone needs MOVE.
   A prop changing hands needs TRANSFER. Any other material change needs STATE_CHANGE.
   The event must match the exact from/to of the state change it explains.
3. MATERIAL TRANSITIONS HAPPEN INSIDE SHOTS. Never across a cut. If a character falls
   asleep, some shot must SHOW them falling asleep. A CONTINUOUS boundary forbids any
   material difference between one shot's end and the next shot's start.
4. RESPECT FIXED GEOGRAPHY. Never mirror or rearrange the location.
5. PERSISTENT PROPS ONLY. The set of props may not change; anything present must be
   present throughout.
6. ONE DOMINANT ACTION per shot, small and achievable.
7. DO NOT choose camera framing. Declare each shot's coverage_role — what the shot is
   FOR — and deterministic code will assign shot size, angle and camera setup from the
   mode's coverage policy.
   Also declare focus: which entity the frame is organised around.
     {"type": "CHARACTER", "ids": ["coco"]}  or  {"type": "GROUP", "ids": [...]}
   Two shots at the same size and angle but focused on DIFFERENT subjects are different
   compositions, and the system relies on that to avoid reusing the wrong pixels.

     ESTABLISH  set the scene        GROUP      all characters together
     SUBJECT    one character acts   REACTION   a character responds
     DETAIL     a small important thing         RESOLUTION  the settling beat
"""


SHOT_SCHEMA = """
Return ONLY a JSON array, no prose, no code fence. Each element:
{
  "id": "s01",
  "cast": ["<cast keys in this shot>"],
  "frame": "<the FIRST FRAME: camera, shot size, where each character is, landmark
             positions. Restate that framing is identical to the other shots.>",
  "motion": "<the single action during the clip. No camera direction here.>",
  "camera": "<camera instruction only, e.g. 'Locked static camera. No movement.'>",
  "start_state": {...}, "end_state": {...},
  "boundary": {"type": "CONTINUOUS"}
}

BOUNDARY declares how this shot joins the PREVIOUS one. Default and strongly preferred is
CONTINUOUS. Only if the mode permits it may you use TIME_JUMP, LOCATION_CHANGE or MONTAGE,
and then you must supply "reason". Do not use a non-continuous boundary to avoid showing a
transition — that is the defect this rule exists to prevent.

STATE uses ONLY the closed vocabulary below. Never invent values, never use prose.

  "environment": "<location id>"
  "population":  ["<cast keys present>"]
  "characters":  { "<cast key>": { "<dimension>": "<VALUE>", ... } }
  "props":       { "<object>": "<VALUE>" }
  "visual":      { "camera_setup_id": "<STABLE_ID>", "shot_size": "<VALUE>",
                   "camera_angle": "<VALUE>" }
  "location_id": "<one of the episode's declared locations>"

EVENTS explain WHY state changed. State says what is true; events say why.
Every discontinuity must be evented, in the shot that contains it:

  "events": [
    {"type": "ENTER",        "entity": "nana",  "from_zone": "OFFSCREEN", "to_zone": "CHAIR"},
    {"type": "EXIT",         "entity": "pip",   "from_zone": "DOOR", "to_zone": "OFFSCREEN"},
    {"type": "MOVE",         "entity": "nana",  "from_zone": "CHAIR", "to_zone": "WINDOW"},
    {"type": "TRANSFER",     "object": "apple", "from": "coco", "to": "pip"},
    {"type": "STATE_CHANGE", "entity": "door",  "field": "open_state",
     "from": "CLOSED", "to": "OPEN"}
  ]

RULES: population change -> ENTER/EXIT. zone change -> MOVE. prop owner change ->
TRANSFER. prop condition change -> STATE_CHANGE. A change with no event is REJECTED.
camera_setup_id is a stable label for a physical camera position (e.g. BEDROOM_AXIS_A);
reuse the same id whenever the camera has not moved.

VOCABULARY (dimension -> allowed values):
{vocab}

VISUAL vocabulary (per shot, in state.visual):
{visual}

THE CUT RULE — the most important constraint.
A dimension marked MATERIAL may NOT differ between one shot's end_state and the next
shot's start_state. A material change must be SHOWN, inside a shot, by that shot's motion.

  WRONG: s02.end awareness=DROWSY, s03.start awareness=ASLEEP
         (falling asleep happened in the cut; the viewer never sees it)
  RIGHT: s02.end awareness=DROWSY, s03.start awareness=DROWSY,
         s03.motion "Coco's eyes close and he falls asleep", s03.end awareness=ASLEEP

Plan the material transitions INSIDE shots. Non-material dimensions (facing, expression)
may drift freely.
"""


def inherit_predecessor_pixels(prev_shot, shot, bible):
    """True when the next first frame carries no new information at all.

    Requires VISUAL-state continuity, not merely material-state continuity. A continuous
    story moment can legitimately cut wide -> close, or eye-level -> over-shoulder, while
    every material state is identical; inheriting pixels there would discard a composition
    the planner intended. So camera and shot size must match too.

    When composition DOES change on a continuous boundary, we generate a new frame and the
    predecessor becomes a temporal reference while the canonical portraits and plates
    remain the identity and world authority.
    """
    if (shot.get("boundary") or {}).get("type", "CONTINUOUS") != "CONTINUOUS":
        return False
    # visual state must be unchanged
    pv = (prev_shot.get("end_state") or {}).get("visual") or {}
    sv = (shot.get("start_state") or {}).get("visual") or {}
    # Redundant with the validator ON PURPOSE. This is the only function whose failure
    # mode is a valid-looking but WRONG frame rather than a missing one, so it re-proves
    # every precondition rather than trusting an upstream guarantee.
    req = list(bible.get("visual_vocab", {})) + ["camera_setup_id", "composition_id"]
    if not pv or not sv:
        return False                      # unknown composition -> never assume sameness
    for dim in req:
        if not pv.get(dim) or not sv.get(dim):
            return False                  # incomplete visual contract -> never inherit
        if pv[dim] != sv[dim]:
            return False
    pes, sss = prev_shot.get("end_state") or {}, shot.get("start_state") or {}
    if pes.get("location_id") != sss.get("location_id"):
        return False
    if set(pes.get("population") or []) != set(sss.get("population") or []):
        return False
    if (pes.get("props") or {}) != (sss.get("props") or {}):
        return False
    material = {k for k, v in bible.get("state_vocab", {}).items() if v.get("material")}
    a = (prev_shot.get("end_state") or {}).get("characters") or {}
    b = (shot.get("start_state") or {}).get("characters") or {}
    if set(a) != set(b) or not a:
        return False
    for who in a:
        for dim in material:
            if (a[who] or {}).get(dim) != (b[who] or {}).get(dim):
                return False
    return True


def visual_block():
    return "\n".join(f"  {k}: {', '.join(v)}"
                     for k, v in BIBLE.get("visual_vocab", {}).items())


def vocab_block():
    return "\n".join(
        f"  {k}: {'MATERIAL' if v.get('material') else 'free'} -> {', '.join(v['values'])}"
        for k, v in BIBLE["state_vocab"].items())


def stage_plan(eid):
    d = ep_dir(eid)
    dest = d / "shots.json"
    ep = load_ep(eid)
    ihash = input_hash(ep=ep, bible=BIBLE, model=C.PLANNER_MODEL, rules=PLANNER_RULES,
                       schema=SHOT_SCHEMA, contract=C.PLAN_CONTRACT_VERSION)
    ok, why = usable(dest, d / "shots.provenance.json", ihash)
    if ok:
        print(f"  shots.json valid ({len(json.loads(dest.read_text()))} shots), skipping")
        return
    if dest.exists():
        print(f"  REPLANNING — {why}")
    mode = BIBLE["modes"][ep["mode"]]
    loc = BIBLE["locations"][ep["location"]]
    cast_lines = "\n".join(
        f"  {k} = {BIBLE['cast'][k]['name']}: {BIBLE['cast'][k]['features']}" for k in ep["cast"])

    demands = camera.required_roles(ep, BIBLE)
    role_demand = ""
    if demands:
        lines = ["COVERAGE REQUIREMENTS. This episode MUST include shots with these",
                 "coverage_roles, or the plan is rejected:"]
        for size, roles in demands:
            lines.append(f"  at least one of {roles}   (so a {size} shot can be assigned)")
        role_demand = "\n".join(lines) + "\n\n"

    prompt = f"""You are a storyboard director for a preschool animation channel.

EPISODE: {ep['title']}  (mode: {ep['mode']})
IDEA: {ep['idea']}
SHOT COUNT: exactly {ep['shots']}

{role_demand}MODE DIRECTION
  allowed boundaries: {', '.join(mode.get('allowed_boundaries', ['CONTINUOUS']))}
  pacing: {mode['pacing']}
  camera allowed: {', '.join(mode['camera_allowed'])}
  camera avoid: {', '.join(mode['camera_avoid'])}
  {mode['rules']}

CAST (use only these, by these exact names)
{cast_lines}

LOCATION: {loc['name']}
{loc['description']}
{loc['geography']}

STYLE: {BIBLE['style_lock']}
{PLANNER_RULES}
{SHOT_SCHEMA.replace("{vocab}", vocab_block()).replace("{visual}", visual_block())}"""

    # Prove the request is satisfiable before spending anything at all.
    try:
        camera.precheck(ep, BIBLE)
    except camera.Unsatisfiable as e:
        sys.exit(f"  UNSATISFIABLE_REQUIREMENT: {e}\n  Nothing planned, nothing spent.")
    schema = shot_plan_schema(BIBLE, ep)
    cl = client()

    def call(extra=""):
        # The invariant is universal: no paid provider call before reservation. Planning
        # is cheap, but tolerating the exception here preserves the exact defect class
        # that caused the overdraft.
        res_idx = reserve("llm", f"plan:{eid}", C.PLANNER_MAX_INR)
        try:
            return _call_inner(extra, res_idx)
        except BaseException:
            settle(res_idx, None); raise

    def _call_inner(extra, res_idx):
        _, types, _ = _sdk()
        r = cl.models.generate_content(
            model=C.PLANNER_MODEL, contents=prompt + extra,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema))
        u = getattr(r, "usage_metadata", None)
        actual = (((u.prompt_token_count / 1e6) * 0.10 +
                   (u.candidates_token_count / 1e6) * 0.40) * 88) if u else 1.0
        settle(res_idx, actual)          # reconcile the conservative hold
        d = json.loads(r.text)
        shots_ = d.get("shots", [])
        try:
            shots_ = camera.assign(shots_, ep, BIBLE)
            return shots_, d.get("requirement_results", {}), None
        except camera.Unsatisfiable as e:
            return shots_, d.get("requirement_results", {}), str(e)

    print(f"  planning {ep['shots']} shots for {eid} (schema-enforced)...")
    shots, results, cam_err = call()
    issues = validate(shots, ep, BIBLE, results)
    if cam_err:
        from validate import Issue
        issues.append(Issue("ERROR", "COVERAGE_ROLES_INSUFFICIENT", "-", "coverage_role",
            f"{cam_err}. Choose coverage_roles that permit the required sizes."))
    errs = report(issues)

    # EXACTLY ONE repair. An unbounded loop is the retry pathology that began this project.
    if errs:
        print(f"  {errs} error(s) — one bounded repair attempt")
        payload = json.dumps([{"code": i.code, "shot_id": i.shot_id, "path": i.path,
                               "message": i.message}
                              for i in issues if i.severity == "ERROR"], indent=2)
        shots, results, cam_err = call(
            "\n\nYour previous plan was REJECTED by a deterministic validator. Here is "
            "the machine-readable issue list. Fix exactly these and change nothing else.\n"
            + payload + "\n\nPrevious plan:\n" + json.dumps(shots, indent=2))
        issues = validate(shots, ep, BIBLE, results)
        if cam_err:
            from validate import Issue
            issues.append(Issue("ERROR", "COVERAGE_ROLES_INSUFFICIENT", "-",
                "coverage_role", cam_err))
        if report(issues):
            (d / "shots.rejected.json").write_text(json.dumps(shots, indent=2))
            sys.exit("\n  PLAN REJECTED after one repair. Nothing generated, nothing "
                     "spent on images or video. Rejected plan saved for inspection.")
        print("  repair succeeded")

    dest.write_text(json.dumps(shots, indent=2))
    (d / "shots.provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "input_hash": ihash, "sha": sha_file(dest),
         "model": C.PLANNER_MODEL, "requirement_results": results}, indent=2))
    print(f"  -> {dest}  ({len(shots)} shots)")
    for s in shots:
        print(f"     {s['id']}: {s['motion'][:70]}")


# ──────────────────────── reference compiler ─────────────────────────
def reference_policy(prev_shot, shot, bible):
    """One compiler, three outcomes. Replaces derive_continuity, which was LIVE AND STALE:
    it still read the prose-era keys spatial/appearance/possession/physical, none of which
    exist in the typed schema, so it silently reported "no transient state carried" for
    every shot regardless of content.

      PREDECESSOR_PIXELS  nothing changed at all -> the frame IS the previous last frame
      TEMPORAL_REFERENCE  continuous, but composition or state moved -> generate, using
                          the predecessor as a temporal hint plus canonical authority
      CANONICAL_ONLY      deliberate discontinuity -> canonical references only
    """
    if prev_shot is None:
        return "CANONICAL_ONLY", "first shot"
    btype = (shot.get("boundary") or {}).get("type", "CONTINUOUS")
    if btype != "CONTINUOUS":
        return "CANONICAL_ONLY", f"deliberate {btype}"
    if inherit_predecessor_pixels(prev_shot, shot, bible):
        return "PREDECESSOR_PIXELS", "continuous, nothing changed across the edit"
    return "TEMPORAL_REFERENCE", "continuous, but composition or state changed"


# ───────────────────────────── portraits ─────────────────────────────
def stage_portraits(only=None):
    """`only` limits regeneration to named cast keys, so a controlled probe does not pay
    to refresh characters it will never render."""
    cl = client()
    wanted = set((only or "").split(",")) if only else None
    for key, c in BIBLE["cast"].items():
        if wanted and key not in wanted:
            continue
        dest = PORTRAITS / f"{key}.png"
        prov_p = PORTRAITS / f"{key}.provenance.json"
        # A portrait is identity authority for every frame downstream. Reusing one made
        # from an older bible or style silently poisons the whole episode.
        ihash = input_hash(character=c, style=BIBLE["style_lock"], model=C.IMAGE_MODEL,
                           aspect=C.IMAGE_ASPECT)
        ok, why = usable(dest, prov_p, ihash)
        if ok:
            print(f"  {key}: valid, skipping"); continue
        if dest.exists():
            print(f"  {key}: REGENERATING — {why}")
        print(f"  {key}: generating canonical portrait")
        gen_image(cl, f"{BIBLE['style_lock']}\n\nFull-body character reference sheet on a "
                      f"plain white background. Front view, neutral standing pose, neutral "
                      f"expression, even lighting, no shadows, no props, no scenery.\n\n"
                      f"CHARACTER: {c['features']}", [], dest,
                      kind="image", detail=f"portrait:{key}")
        prov_p.write_text(json.dumps(
            {"status": "COMPLETE", "source": "GENERATED", "input_hash": ihash,
             "sha": sha_file(dest), "model": C.IMAGE_MODEL,
             "cost_inr": C.INR_PER_IMAGE}, indent=2))


# ────────────────────────────── frames ───────────────────────────────
def stage_frames(eid, only=None):
    d = ep_dir(eid); ep = load_ep(eid)
    shots = json.loads((d / "shots.json").read_text())
    if report(validate(shots, ep, BIBLE)):
        sys.exit("  plan has continuity errors — fix or replan before spending")
    loc = BIBLE["locations"][ep["location"]]
    cl = client()
    policy = [reference_policy(shots[i-1] if i else None, s, BIBLE)
              for i, s in enumerate(shots)]
    for s, (mode, why) in zip(shots, policy):
        print(f"  {s['id']}: {mode:19s} — {why}")

    # regenerating frames invalidates everything derived from them
    for stale in list((d / "clips").glob("*.mp4")) + list((d / "transitions").glob("*.png")):
        if not (d / "frames" / f"{stale.stem.split('_')[0]}.png").exists():
            stale.unlink(); print(f"  invalidated {stale.name}")

    prev = None
    for idx, shot in enumerate(shots):
        if only and shot["id"] != only:
            # A skipped predecessor may still become a reference. Record it, but the
            # proof happens where it is consumed, not here.
            prev = d / "frames" / f"{shot['id']}.png"; continue
        dest = d / "frames" / f"{shot['id']}.png"
        prov_p = d / "frames" / f"{shot['id']}.provenance.json"
        res = resolve_frame_refs(d, shots, idx, BIBLE, loc, policy[idx][0])
        if res.error:
            sys.exit(f"  {shot['id']}: {res.error}")
        refs, ref_ids = res.paths, res.ref_ids
        legend = []
        for i_, (role, key, _sha) in enumerate(ref_ids):
            if role == "identity":
                legend.append(f"Image {i_}: canonical reference for "
                              f"{BIBLE['cast'][key]['name']}")
            elif role == "temporal":
                legend.append(f"Image {i_}: the previous shot. Continue directly from it: "
                              f"identical camera, geometry and lighting.")

        ihash = frame_identity(shot, BIBLE, loc, ref_ids)
        ok, why = usable(dest, prov_p, ihash)
        if ok:
            print(f"  {shot['id']}: valid, skipping"); prev = dest; continue
        if dest.exists():
            print(f"  {shot['id']}: RECOMPUTING — {why}")

        if policy[idx][0] == "PREDECESSOR_PIXELS":
            tail = d / "transitions" / f"{shots[idx-1]['id']}_LAST.png"
            write_atomic(dest, tail.read_bytes())
            prov_p.write_text(json.dumps(
                {"status": "COMPLETE", "source": "PREDECESSOR_PIXELS", "from": tail.name,
                 "input_hash": ihash, "sha": sha_file(dest), "ref_ids": ref_ids,
                 "reason": "CONTINUOUS boundary, material + visual state unchanged",
                 "cost_inr": 0}, indent=2))
            print(f"  {shot['id']}: INHERITED from {tail.name} (free, pixel-exact)")
            prev = dest; continue

        prompt = ("\n".join(legend) + f"\n\n{BIBLE['style_lock']}\n\n"
                  f"LOCATION (identical in every shot): {loc['description']}\n\n"
                  f"{loc['geography']}\n\n"
                  f"SHOT: {shot.get('frame_compiled') or shot['frame']}\n\n"
                  "Characters must match their canonical reference images exactly: same "
                  "colour, clothing, proportions and face. Only the characters named above "
                  "are present. No text or lettering.")
        print(f"  {shot['id']}: generating first frame ({len(refs)} refs)")
        gen_image(cl, prompt, refs, dest, kind="image", detail=f"frame:{eid}/{shot['id']}")
        prov_p.write_text(json.dumps(
            {"status": "COMPLETE", "source": "GENERATED", "model": C.IMAGE_MODEL,
             "aspect": C.IMAGE_ASPECT, "input_hash": ihash, "sha": sha_file(dest),
             "refs": [str(r.relative_to(OUT)) for r in refs], "ref_ids": ref_ids,
             "revision": build_revision(),
             "cost_inr": C.INR_PER_IMAGE}, indent=2))
        prev = dest


# ─────────────────────────────── video ───────────────────────────────
def preflight(eid, shots, d, targets=None):
    """`shots` is ALWAYS the full episode plan. `targets` names which shots are about to
    make paid calls. Truncating the plan would make shot 2 look like shot 1 and therefore
    CANONICAL_ONLY, silently miscomputing frame identity on the normal interleaved path."""
    """Everything provable for free, asserted before a single rupee is spent."""
    print("  PREFLIGHT")
    fail = []
    ep = load_ep(eid)
    loc = BIBLE["locations"][(ep.get("locations") or [ep["location"]])[0]]
    policy = [reference_policy(shots[i - 1] if i else None, s, BIBLE)
              for i, s in enumerate(shots)]
    for i, s in enumerate(shots):
        if targets and s["id"] not in targets:
            continue
        f = d / "frames" / f"{s['id']}.png"
        prov = d / "frames" / f"{s['id']}.provenance.json"
        _, want = frame_identity_from(shots, i, d, BIBLE, loc)
        ok, why = usable(f, prov, want)
        if not ok:
            fail.append(f"{s['id']}: frame not provably current ({why})")
    if C.VIDEO_SECONDS not in (4, 6, 8):
        fail.append(f"duration {C.VIDEO_SECONDS}s is not a provider-supported value")
    n_target = len([s for s in shots if not targets or s["id"] in targets])
    worst = n_target * C.INR_PER_VID_SEC * C.VIDEO_SECONDS * getattr(C, "SAFETY_MARGIN", 1.0)
    spent = ledger()["spent_inr"]
    if spent + worst > C.BUDGET_INR:
        fail.append(f"WORST-CASE Rs {worst:.2f} (margin applied) would exceed the cap "
                    f"{C.BUDGET_INR} at Rs {spent:.2f} spent")
    rev = build_revision()
    print(f"    revision: {rev['commit'][:12]}"
          f"{' TAG=' + rev['tag'] if rev['tag'] else ''}"
          f"{'  DIRTY' if rev['dirty'] else '  clean'}")
    if rev["dirty"] and getattr(C, "REQUIRE_CLEAN_TREE", True):
        fail.append("working tree is DIRTY — the executable logic is not the committed "
                    "logic, so a paid result could not be attributed to a revision")
    print(f"    contract: {C.PROVIDER_SURFACE} / {C.VIDEO_MODEL} / {C.VIDEO_RES} / "
          f"{C.VIDEO_SECONDS}s / audio-in-prompt=NO")
    print(f"    cost:     {n_target} clips, worst case Rs {worst:.2f} with margin "
          f"(spent {spent:.2f}/{C.BUDGET_INR})")
    for f in fail:
        print(f"    x {f}")
    if fail:
        sys.exit("  PREFLIGHT FAILED — nothing generated, nothing spent")
    print("    ok — only stochastic model behaviour remains untested")


def stage_video(eid, only=None):
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    if report(validate(shots, load_ep(eid), BIBLE)):
        sys.exit("  plan has continuity errors")
    # full plan for context, targets for scope — never truncate continuity context
    preflight(eid, shots, d, targets=[only] if only else None)
    if only:
        shots = [s for s in shots if s["id"] == only]
    cl = client()
    for shot in shots:
        frame = d / "frames" / f"{shot['id']}.png"
        dest = d / "clips" / f"{shot['id']}.mp4"
        prov_p = d / "clips" / f"{shot['id']}.provenance.json"
        if not frame.exists(): sys.exit(f"missing frame {frame}")
        chash = input_hash(shot=shot, frame_sha=sha_file(frame), model=C.VIDEO_MODEL,
                           res=C.VIDEO_RES, secs=C.VIDEO_SECONDS)
        ok, why = usable(dest, prov_p, chash)
        if ok:
            print(f"  {shot['id']}: clip valid, skipping"); continue
        if dest.exists():
            print(f"  {shot['id']}: RE-RENDERING — {why}")
        # no audio direction: the audio spine is separate
        prompt = (f"ACTION: {shot['motion']}\nCAMERA: {shot['camera']}\n"
                  f"STYLE: {BIBLE['style_lock']}\n"
                  f"{veo_constraint_clause(BIBLE, load_ep(eid)['mode'])}")
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        print(f"  {shot['id']}: generating clip")
        res_idx = reserve("video", f"clip:{eid}/{shot['id']}",
                          C.INR_PER_VID_SEC * C.VIDEO_SECONDS)
        settled = False
        try:
            _, types, _ = _sdk()
            op = cl.models.generate_videos(
                model=C.VIDEO_MODEL, prompt=prompt,
                image=types.Image.from_file(location=str(frame)),
                config=types.GenerateVideosConfig(
                    resolution=C.VIDEO_RES, aspect_ratio=C.VIDEO_ASPECT,
                    duration_seconds=C.VIDEO_SECONDS),
            )
            while not op.done:
                time.sleep(5); op = cl.operations.get(op)
            if op.error:
                raise RuntimeError(f"provider error: {op.error}")
            v = op.response.generated_videos[0]
            cl.files.download(file=v.video)
            write_atomic(dest, v.video.video_bytes)
            settle(res_idx, C.INR_PER_VID_SEC * C.VIDEO_SECONDS); settled = True

            prov_p.write_text(json.dumps(
                {"status": "COMPLETE", "qc": "PENDING_QC",
                 "video_prompt": prompt, "video_prompt_sha": prompt_sha,
                 "input_hash": chash, "sha": sha_file(dest),
                 "model": C.VIDEO_MODEL, "res": C.VIDEO_RES, "secs": C.VIDEO_SECONDS,
                 "revision": build_revision()},
                indent=2))
            tail = d / "transitions" / f"{shot['id']}_LAST.png"
            os.system(f'ffmpeg -v error -y -sseof -0.1 -i "{dest}" -frames:v 1 '
                      f'"{tail}" 2>/dev/null')
            if tail.exists():
                (d / "transitions" / f"{shot['id']}_LAST.provenance.json").write_text(
                    json.dumps({"status": "COMPLETE", "sha": sha_file(tail),
                                "from_clip": dest.name,
                                "input_hash": input_hash(source_clip_sha=sha_file(dest),
                                    extractor="ffmpeg-sseof-0.1-v1")}, indent=2))
            print(f"    -> {dest.name}")
        except Exception as e:
            print(f"    FAILED: {e}")
        finally:
            if not settled:
                settle(res_idx, None)      # deterministic ledger state on ANY exception


# ────────────────────────────── assemble ─────────────────────────────
def stage_assemble(eid):
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    clips = []
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        ok, why = usable(c, d / "clips" / f"{s['id']}.provenance.json",
                         input_hash(shot=s, frame_sha=sha_file(d / "frames" / f"{s['id']}.png"),
                                    model=C.VIDEO_MODEL, res=C.VIDEO_RES,
                                    secs=C.VIDEO_SECONDS)) if c.exists() else (False, "missing")
        if not ok:
            sys.exit(f"  refusing to assemble: {s['id']} clip is not provably current ({why})")
        verdict = json.loads((d / "clips" / f"{s['id']}.provenance.json").read_text()
                             ).get("qc", "PENDING_QC")
        if verdict != "ACCEPTED":
            sys.exit(f"  refusing to assemble: {s['id']} is {verdict}. QC failure is "
                     f"terminal — it never triggers regeneration.")
        clips.append(c)
    if not clips: sys.exit(f"no clips in {d/'clips'}")
    final = d / "episode.mp4"
    x = C.CROSSFADE_SECONDS
    if len(clips) == 1 or x <= 0:
        lst = d / "concat.txt"
        lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
        rc = os.system(f'ffmpeg -y -f concat -safe 0 -i "{lst}" -c copy "{final}" 2>/dev/null')
    else:
        inputs = " ".join(f'-i "{c}"' for c in clips)
        parts, prev, off = [], "0:v", 0.0
        for i in range(1, len(clips)):
            off += C.VIDEO_SECONDS - x
            parts.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={x}:offset={off}[v{i}]")
            prev = f"v{i}"
        rc = os.system(f'ffmpeg -y {inputs} -filter_complex "{";".join(parts)}" '
                       f'-map "[{prev}]" -c:v libx264 -preset medium -crf 20 '
                       f'-pix_fmt yuv420p "{final}" 2>/dev/null')
    if rc != 0: sys.exit("ffmpeg failed (brew install ffmpeg)")
    print(f"  -> {final}  ({len(clips)} clips, crossfade {x}s)")


def stage_episode(eid):
    """Interleaved shot-by-shot run.

    Predecessor-pixel inheritance only works if clip N exists before frame N+1 is
    resolved, so frames and clips must alternate rather than run as separate passes.
    Each shot: resolve its first frame (inherit free, or generate), then render it.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    if report(validate(shots, load_ep(eid), BIBLE)):
        sys.exit("  plan has continuity errors")
    for i, s in enumerate(shots):
        print(f"\n── {s['id']} ({i+1}/{len(shots)}) ──")
        stage_frames(eid, only=s["id"])
        stage_video(eid, only=s["id"])
    stage_assemble(eid)


def stage_verify(_=None):
    """Print the attestation ChatGPT asked for: exactly which tree would run."""
    rev = build_revision()
    print(f"  commit : {rev['commit']}")
    print(f"  tag    : {rev['tag'] or '(none)'}")
    print(f"  tree   : {'DIRTY — will refuse to spend' if rev['dirty'] else 'clean'}")
    print("  sources:")
    for f, h in rev["sources"].items():
        print(f"    {h}  {f}")
    L = ledger()
    print(f"  ledger : Rs {L['spent_inr']:.2f} reserved/spent, cap Rs {C.BUDGET_INR}")


def reconcile(before, after, note=""):
    """Record a real account-balance movement against what the ledger predicted.

    The ledger can only ever say what we THINK we spent. Without periodic anchoring to an
    actual balance that belief drifts silently — which is precisely how the previous
    project ran for three months with cost tracking that was never once checked against
    money. One measured datapoint beats any amount of estimating.
    """
    L = ledger()
    spent = round(before - after, 2)
    L.setdefault("reconciliations", []).append(
        {"at": time.strftime("%F %T"), "balance_before": before, "balance_after": after,
         "actual_inr": spent, "ledger_inr": L["spent_inr"], "note": note})
    LEDGER.write_text(json.dumps(L, indent=2))
    return spent


def stage_costs(episode=None):
    """What each episode cost. Pass an episode id to itemise it.

    Every number here is OUR estimate at settlement time, not a provider invoice. The
    ledger is an authorisation record; it is not billing truth, and the gap between the
    two is exactly what went unnoticed for three months. Reconcile against the console.
    """
    L = ledger()
    ops = L["ops"]
    if not ops:
        print("  ledger empty"); return

    by_ep, kinds = {}, {}
    for op in ops:
        ep = op_episode(op)
        amt = op_spent(op)
        by_ep.setdefault(ep, {"total": 0.0, "n": 0, "kinds": {}})
        by_ep[ep]["total"] += amt
        by_ep[ep]["n"] += 1
        by_ep[ep]["kinds"][op["kind"]] = by_ep[ep]["kinds"].get(op["kind"], 0.0) + amt
        kinds[op["kind"]] = kinds.get(op["kind"], 0.0) + amt

    if episode:
        e = by_ep.get(episode)
        if not e:
            print(f"  no ops recorded for {episode}")
            print(f"  known: {', '.join(sorted(by_ep))}")
            return
        print(f"  {episode}   Rs {e['total']:.2f}   ({e['n']} ops)\n")
        for op in ops:
            if op_episode(op) != episode:
                continue
            st = op.get("state", "SPENT")
            flag = "  (released)" if st == "RELEASED" else ("  (held)" if st == "RESERVED" else "")
            print(f"    {op['at']}  {op['kind']:6} {op['detail']:22} "
                  f"Rs {op_spent(op):7.2f}{flag}")
        print(f"\n    by kind: " + "  ".join(f"{k}={v:.2f}" for k, v in sorted(e["kinds"].items())))
        return

    print(f"  {'episode':14} {'ops':>4} {'Rs':>9}   breakdown")
    for ep in sorted(by_ep, key=lambda k: -by_ep[k]["total"]):
        e = by_ep[ep]
        bd = " ".join(f"{k}={v:.2f}" for k, v in sorted(e["kinds"].items()))
        print(f"  {ep:14} {e['n']:>4} {e['total']:>9.2f}   {bd}")

    held = sum(op_spent(o) for o in ops if o.get("state") == "RESERVED")
    rel = sum(1 for o in ops if o.get("state") == "RELEASED")
    print(f"\n  total     Rs {L['spent_inr']:.2f} of cap Rs {C.BUDGET_INR} "
          f"(Rs {C.BUDGET_INR - L['spent_inr']:.2f} left)")
    print("  by kind   " + "  ".join(f"{k}={v:.2f}" for k, v in sorted(kinds.items())))
    if held:
        print(f"  WARNING   Rs {held:.2f} still RESERVED — a run died before settling")
    if rel:
        print(f"  {rel} released hold(s) excluded — failed calls cost nothing")
    print("\n  SHARED = channel-wide assets (portraits), not charged to any one episode.")
    print("  Estimates at settlement, NOT a provider invoice.")
    rs = L.get("reconciliations") or []
    if rs:
        r = rs[-1]
        print(f"  Last checked against a real balance on {r['at'][:10]}: "
              f"Rs {r['actual_inr']:.2f} actually left the account.")
        if r.get("note"):
            print(f"    {r['note']}")
    else:
        print("  NEVER checked against a real balance — treat every figure above as unverified.")


STAGES = {"verify": stage_verify, "plan": stage_plan, "portraits": stage_portraits, "frames": stage_frames,
          "video": stage_video, "assemble": stage_assemble, "episode": stage_episode, "costs": stage_costs}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("episode", nargs="?", help="episode id, e.g. E01 (not needed for portraits)")
    a = ap.parse_args()
    if a.stage not in ("portraits", "verify", "costs") and not a.episode:
        sys.exit(f"`{a.stage}` needs an episode id, e.g. make.py {a.stage} E01")
    print(f"stage: {a.stage} {a.episode or ''}   spent: Rs {ledger()['spent_inr']:.2f}"
          f"/{C.BUDGET_INR}\n")
    STAGES[a.stage](a.episode)
