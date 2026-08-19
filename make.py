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
from compile_prompt import veo_constraint_clause, veo_negative_prompt
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
                         portrait_identity(bible["cast"][key], bible))
        if not ok:
            return RefResolution([], [], f"portrait '{key}' not provably current ({why})")
        paths.append(pth); ref_ids.append(("identity", key, sha_file(pth)))

    # 2. WORLD-FORM AUTHORITY — mandatory on every frame, exactly like portraits.
    #    Prose controls arrangement and cannot control appearance: s04 obeyed every
    #    position in FIXED LAYOUT and still reinvented the rug, the shelf and the walls.
    location_id = shot_location(shot)
    if not location_id:
        return RefResolution([], [], "shot has no location_id in its start_state")
    world_path, world_ref_id, world_error = resolve_location_plate(location_id)
    if world_error:
        return RefResolution([], [], world_error)
    paths.append(world_path); ref_ids.append(world_ref_id)

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
        # Identity here is the INHERITED PIXELS and nothing else. Portraits and the world
        # plate are references for GENERATION; this frame is byte-copied, so neither
        # caused a single pixel of it. Binding them in would stale an inherited frame
        # whenever canon changed, for a frame the change provably could not have touched.
        # Provenance says what CAUSED an artifact; whether canon has since moved is a
        # policy question and does not belong in a cache key.
        return RefResolution([], [("inherited", prev_id, sha_file(tail)),
                                  ("inheritance_contract", INHERITANCE_CONTRACT_VERSION,
                                   "")])

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
6b. DECLARE WHAT MUST VISIBLY CHANGE. Every shot states a visual_change — the SEMANTIC
   requirement, never a choice of renderer:
     NONE                   nothing changes; the image is held
     CAMERA_ONLY            only the viewpoint moves
     CHARACTER_DEFORMATION  a body or face changes shape
     CHARACTER_TRANSLATION  a character moves through the space
     OBJECT_DEFORMATION     a thing changes shape or state
     WORLD_CHANGE           the place itself changes
   Declare the SMALLEST requirement that is honestly true for the beat. Deterministic code
   then picks the cheapest renderer that can satisfy it, and a beat needing NONE or
   CAMERA_ONLY is rendered for free from an accepted still. Claiming a bigger change than
   the beat needs does not make the shot better; it makes it cost Rs 32 and risk a room
   that will not hold still.
7. DO NOT choose camera framing. Declare each shot's coverage_role — what the shot is
   FOR — and deterministic code will assign shot size, angle and camera setup from the
   mode's coverage policy.
   Also declare focus: which entity the frame is organised around.
     {"type": "CHARACTER", "ids": ["<a cast id from the CAST list>"]}  or  {"type": "GROUP", "ids": [...]}
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
    {"type": "ENTER",        "entity": "<cast id>", "from_zone": "OFFSCREEN", "to_zone": "<zone>"},
    {"type": "EXIT",         "entity": "<cast id>", "from_zone": "<zone>", "to_zone": "OFFSCREEN"},
    {"type": "MOVE",         "entity": "<cast id>", "from_zone": "<zone>", "to_zone": "<zone>"},
    {"type": "TRANSFER",     "object": "<prop id>", "from": "<cast id>", "to": "<cast id>"},
    {"type": "STATE_CHANGE", "entity": "<entity id>", "field": "<state field>",
     "from": "<old value>", "to": "<new value>"}
  ]

RULES: population change -> ENTER/EXIT. zone change -> MOVE. prop owner change ->
TRANSFER. prop condition change -> STATE_CHANGE. A change with no event is REJECTED.
VOCABULARY (dimension -> allowed values):
{vocab}

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


def vocab_block():
    return "\n".join(
        f"  {k}: {'MATERIAL' if v.get('material') else 'free'} -> {', '.join(v['values'])}"
        for k, v in BIBLE["state_vocab"].items())


INHERITANCE_CONTRACT_VERSION = "1"

LOCATION_PLATES = OUT / "location_plates"
LOCATION_PLATES.mkdir(parents=True, exist_ok=True)
LOCATION_PLATE_CONTRACT_VERSION = "1"


# A POSITIVE contract: exactly which cast fields can affect the generated pixels.
#
# This was a blacklist ("everything except possessive") for one commit and that shape
# rots: the next language-only field someone adds is silently causal, and every portrait
# is re-bought for a word that cannot change a pixel. An allow-list fails the other way
# — a genuinely visual field left off is ignored — which is the safe direction, because
# it is caught by the artifact looking wrong rather than by a silent invoice.
#
# `name` is in this list and is NOT causal: the portrait prompt uses features and
# style_lock only. It stays because removing it changes the hash of portraits already
# paid for, and regenerating them would swap the canonical identity anchor for a
# character mid-channel — a continuity risk, not just Rs 15. Moving to a nested `visual:`
# block per GPT's proposal is the right end state and is a deliberate contract-version
# bump with that cost attached, not a refactor to slip in unpriced.
PORTRAIT_VISUAL_KEYS = ("name", "features")
PORTRAIT_CONTRACT_VERSION = "1"


def portrait_identity(character, bible):
    """What a canonical portrait was generated FROM. One definition, every call site."""
    visual = {k: character[k] for k in PORTRAIT_VISUAL_KEYS if k in character}
    return input_hash(character=visual, style=bible["style_lock"],
                      model=C.IMAGE_MODEL, aspect=C.IMAGE_ASPECT)


def shot_location(shot):
    """Where this shot happens. location_id lives in the typed STATE, not on the shot."""
    return ((shot.get("start_state") or {}).get("location_id")) or None


def location_version(location_id):
    """Which VERSION of a place this is. Canon belongs to (location_id, version).

    Recorded now, deliberately ahead of the machinery that will use it, because
    provenance is immutable: a plate written today without a version can never gain one,
    and the first real redesign would then have no way to say which world an old episode
    was filmed in. Version SELECTION is not built — there is exactly one version of
    everything — and will not be until a second version actually exists.

    Explicit, never derived from prose. Changing punctuation must not create a new world.
    """
    return (BIBLE["locations"].get(location_id) or {}).get("version", 1)


def location_plate_paths(location_id):
    """Where a location's canonical plate lives. PURE — creates nothing.

    This used to mkdir as a side effect, so merely ASKING whether a plate existed created
    a directory for it, including for locations that do not exist. An accessor that
    mutates the filesystem makes "does this exist?" unanswerable, because asking creates
    the answer. Directories are created at write time only.

    One immutable canonical plate per location: a visual redesign must become a NEW
    VERSION rather than silently changing what already-published episodes meant.
    """
    base = LOCATION_PLATES / location_id
    return base / "canonical.png", base / "canonical.provenance.json"


def prove_location_plate(location_id):
    """A plate is world authority, so existence is not enough.

    Deliberately does NOT compare against the bible's location prose. Once accepted the
    plate is immutable visual canon; editing prose later must not silently redefine the
    pixels earlier episodes established.
    """
    if location_id not in BIBLE["locations"]:
        return False, f"unknown location '{location_id}'", None, None
    plate, prov_path = location_plate_paths(location_id)
    if not plate.exists() or not prov_path.exists():
        return False, "canonical location plate/provenance missing", plate, None
    try:
        pv = json.loads(prov_path.read_text())
    except Exception:
        return False, "unreadable location-plate provenance", plate, None
    if pv.get("status") != "COMPLETE":
        return False, f"status={pv.get('status')}", plate, pv
    if pv.get("kind") != "LOCATION_PLATE":
        return False, f"wrong artifact kind={pv.get('kind')}", plate, pv
    if pv.get("location_id") != location_id:
        return False, (f"plate belongs to location '{pv.get('location_id')}', "
                       f"not '{location_id}'"), plate, pv
    if pv.get("canonical") is not True:
        return False, "plate is not marked canonical", plate, pv
    want_v = location_version(location_id)
    got_v = pv.get("location_version")
    if got_v is not None and got_v != want_v:
        return False, (f"plate is for {location_id} v{got_v}, the bible now declares "
                       f"v{want_v}"), plate, pv
    if pv.get("sha") != sha_file(plate):
        return False, "location plate checksum mismatch", plate, pv
    return True, "valid", plate, pv


def approve_plate_attempt(location_id, attempt):
    """Promote a QC-ACCEPTED candidate to canonical authority. Free.

    SUPERSEDING, not overwriting. GPT's design made canon immutable, which is right, and
    its own later caveat is the missing half: accepted must not mean immortal. Our plate
    QC proved the promoted-frame plate inadequate — bookshelf cropped, a character in it —
    so "canon can never change" would have frozen a known-weak asset into every future
    episode. The old plate is not deleted or rewritten; it is moved aside with its reason,
    and the chain stays walkable.

    A VERSION BUMP would be the wrong mechanism here: the place has not been redesigned.
    Only our authority for it has improved.
    """
    d = plate_attempt_dir(location_id, attempt)
    plate, prov_p = location_plate_paths(location_id)
    qc_p = d / "qc.json"
    if not (d / "plate.png").exists():
        sys.exit(f"  no attempt {attempt:03d} for {location_id}")
    if not qc_p.exists():
        sys.exit(f"  attempt {attempt:03d} has no QC verdict. Generation creates a "
                 f"candidate; QC creates acceptance. Judge it first.")
    v = json.loads(qc_p.read_text())
    if v.get("status") != "ACCEPTED":
        sys.exit(f"  attempt {attempt:03d} is {v.get('status')}. A bare approve cannot "
                 f"override a QC verdict.")

    # Every probe must have been ANSWERED, and answered PASS. An omitted probe is not a
    # pass; a verdict that can authorise canon by staying silent is not a contract.
    complete, why = qc.plate_probe_completeness(v.get("probes"))
    if not complete:
        sys.exit(f"  attempt {attempt:03d} cannot become canon — " + "; ".join(why))

    # CANON_AGREEMENT is BLOCKING and is RECOMPUTED here from the per-object judgements,
    # never trusted as a summary word. A plate that contradicts footage the audience has
    # already seen is worse than no plate: canon wins for every future frame.
    declared = persistent_objects(location_id)
    if not declared:
        sys.exit(f"  '{location_id}' declares no persistent_objects, so CANON_AGREEMENT "
                 f"cannot be judged. Declare them in the bible before approving canon.")
    status, reasons = qc.canon_agreement(declared, v.get("canon_agreement"))
    if status != v["probes"]["CANON_AGREEMENT"]:
        sys.exit(f"  attempt {attempt:03d}: recorded CANON_AGREEMENT="
                 f"{v['probes']['CANON_AGREEMENT']} but the per-object judgements say "
                 f"{status} — " + "; ".join(reasons or ["no objection"]))
    if status != "PASS":
        sys.exit(f"  attempt {attempt:03d} cannot become canon — " + "; ".join(reasons))
    # the verdict must name the pixels it judged, or it can authorise different ones
    if v.get("plate_sha") != sha_file(d / "plate.png"):
        sys.exit(f"  attempt {attempt:03d} has changed since it was judged "
                 f"(qc names {v.get('plate_sha')}, file is {sha_file(d / 'plate.png')})")
    cand = json.loads((d / "provenance.json").read_text())
    if cand.get("location_id") != location_id:
        sys.exit(f"  attempt belongs to '{cand.get('location_id')}', not '{location_id}'")
    if cand.get("location_version") != location_version(location_id):
        sys.exit(f"  attempt is for v{cand.get('location_version')}, bible declares "
                 f"v{location_version(location_id)}")

    plate.parent.mkdir(parents=True, exist_ok=True)
    superseded = None
    if plate.exists():
        old_sha = sha_file(plate)
        if old_sha == sha_file(d / "plate.png"):
            print(f"  {location_id}: canonical plate already is attempt "
                  f"{attempt:03d}, skipping")
            return
        keep = plate.parent / "superseded" / old_sha
        keep.mkdir(parents=True, exist_ok=True)
        write_atomic(keep / "canonical.png", plate.read_bytes())
        old_prov = json.loads(prov_p.read_text()) if prov_p.exists() else {}
        old_prov.update({"status": "SUPERSEDED", "canonical": False,
                         "superseded_at": time.strftime("%F %T"),
                         "superseded_by": f"attempt {attempt:03d}",
                         "superseded_reason": v.get("supersedes_reason",
                                                    "replaced by a purpose-built plate")})
        (keep / "canonical.provenance.json").write_text(json.dumps(old_prov, indent=2))
        for extra in ("canonical.qc.json",):
            src = plate.parent / extra
            if src.exists():
                (keep / extra).write_text(src.read_text())
        superseded = old_sha
        print(f"  {location_id}: previous canon {old_sha} moved to superseded/, not deleted")

    write_atomic(plate, (d / "plate.png").read_bytes())
    prov_p.write_text(json.dumps(
        {**cand, "status": "COMPLETE", "kind": "LOCATION_PLATE", "canonical": True,
         "approved_at": time.strftime("%F %T"), "approved_by": "HUMAN",
         "from_attempt": attempt, "qc_verdict_sha": sha_file(qc_p),
         "supersedes": superseded, "sha": sha_file(plate)}, indent=2))
    (plate.parent / "canonical.qc.json").write_text(json.dumps(v, indent=2))
    print(f"  {location_id}: attempt {attempt:03d} is now CANONICAL authority")


def resolve_location_plate(location_id):
    """Deterministic world-authority resolver. No camera heuristic in v1.

    Temporal pixels answer "where did we just come from". Portraits answer "who are
    these characters". This answers "what does this world look like".
    """
    ok, why, plate, _pv = prove_location_plate(location_id)
    if not ok:
        return None, None, (f"location '{location_id}' has no provably current canonical "
                            f"world plate ({why})")
    return plate, ("world", location_id, sha_file(plate)), None


PLATE_COMPILER_VERSION = "4"


def persistent_objects(location_id):
    """PURE. The objects that persist in a place, as declared — never inferred from prose.

    Lives outside `locations` in the bible on purpose: it is judgement data that reaches
    no prompt, and `locations` is hashed into every frame's identity.
    """
    return tuple((BIBLE.get("persistent_objects") or {}).get(location_id) or ())


def location_environment(location_id):
    """PURE. The environmental PROPERTIES of a place — lighting and the like.

    Kept separate from persistent_objects on purpose, and the separation was paid for:
    attempt 002 put a physical lantern on the floor because "lamp light" was in the object
    list and the prompt asked it to preserve that object's materials and proportions.
    Properties are described as properties, or the model draws them as things.
    """
    return dict((BIBLE.get("environment") or {}).get(location_id) or {})


def plate_attempt_dir(location_id, n):
    """PURE. Immutable numbered attempts: a paid candidate is never overwritten."""
    return LOCATION_PLATES / location_id / "attempts" / f"{n:03d}"


def next_plate_attempt(location_id):
    """Attempts count COMPLETED ARTIFACTS, not network calls.

    A provider failure that produces nothing is an execution failure, not a creative
    attempt — the reservation releases and the number is not consumed.
    """
    base = LOCATION_PLATES / location_id / "attempts"
    if not base.exists():
        return 1
    used = [int(d.name) for d in base.iterdir()
            if d.is_dir() and d.name.isdigit() and (d / "plate.png").exists()]
    return max(used) + 1 if used else 1


def compile_plate_completion_prompt(location_id, occupants=()):
    """The SMALLEST transformation that fixes the defect, and nothing else.

    Deliberately does NOT ask for a wider viewpoint. Every additional transformation we
    request is another degree of freedom for the model to redesign something with, and
    attempt 001 proved it will use any freedom it is given. Two changes only: remove the
    characters the source frame happens to contain, and extend past the existing edges so
    nothing is cropped.

    The objects to preserve are compiled from the SAME declared persistent_objects list
    that CANON_AGREEMENT judges the result against, and the occupants from the source
    shot's own cast. Nothing about a particular room or a particular bear is written here:
    a prompt that names what only one episode contains cannot be reused by the next one,
    and a prompt that preserves a different list from the one QC checks is asking for one
    thing and grading another.
    """
    objs = persistent_objects(location_id)
    if not objs:
        sys.exit(f"  '{location_id}' declares no persistent_objects, so there is nothing "
                 f"to tell the model to preserve. Declare them in the bible first.")
    keep = ", ".join(objs[:-1]) + (" and " + objs[-1] if len(objs) > 1 else "")
    env = location_environment(location_id)
    light = ""
    if env.get("lighting"):
        light = f"The light is {env['lighting']}. Keep it exactly as it falls in "
        light += "Image 0. Lighting is a property of this place, not an object in it"
        light += (" — the source is not visible in Image 0 and must not be drawn."
                  if env.get("source_visible") is False else ".")
        light += "\n\n"
    names = [BIBLE["cast"][c]["name"] for c in occupants if c in BIBLE["cast"]]
    if names:
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        removal = (f"1. Remove {who} completely, leaving the place exactly as it would "
                   f"look unoccupied.\n")
    else:
        removal = ("1. Leave the place unoccupied — no characters of any kind.\n")
    return ("Image 0 is the established look of this place, taken from accepted footage.\n\n"
            "Keep the established viewpoint, perspective, lighting and mood, and the "
            "visible design, materials, shape and proportions of every object, exactly as "
            f"shown in Image 0 — {keep}.\n\n"
            f"{light}"
            "For any object currently cut off by a frame edge, preserve its visible "
            "portion exactly and extend only the previously unseen portion needed to "
            "complete it.\n\n"
            "Make exactly two changes and nothing else:\n"
            f"{removal}"
            "2. Extend the picture outward beyond its current edges so that every object "
            "sits fully inside the frame with clear space around it and nothing is cut off "
            "by an edge.\n\n"
            "Do not redesign, restyle or replace anything. Do not add people, animals, "
            "furniture, decoration or props. No text or lettering.")


def compile_plate_prompt(location_id):
    """The plate shows the PLACE, and only the place.

    Compiled from the same location entry every frame prompt uses, so plate and prompt
    cannot describe different worlds. No characters: a world plate carrying a character
    hands every downstream frame a picture of someone in a fixed posture, which is the
    defect our own QC found in the promoted-frame plate. Every persistent object must be
    FULLY in frame, because the promoted plate cropped the bookshelf and was therefore
    weak authority for the one object that had already mutated.
    """
    loc = BIBLE["locations"][location_id]
    return (f"{BIBLE['style_lock']}\n\n"
            f"A single wide establishing view of an EMPTY room, photographed straight on "
            f"with nothing cropped.\n\n"
            f"WORLD: {loc['description']}\n\n"
            f"WORLD GEOGRAPHY: {loc['geography']}\n\n"
            f"Every object named above must be COMPLETELY visible within the frame, "
            f"including its full shape and design. Nothing may touch or extend beyond the "
            f"frame edges. No people, no animals, no characters of any kind. No text or "
            f"lettering. This image defines what this place looks like.")


def stage_plate_candidate(location_id, source=None, override=None):
    """Generate ONE candidate plate for a location. Paid, reserved before invoked.

    Generation creates a candidate. QC creates acceptance. Promotion creates authority.
    Three separate operations, and this is only the first.
    """
    if location_id not in BIBLE["locations"]:
        sys.exit(f"  unknown location '{location_id}'")
    rev = build_revision()
    if rev["dirty"] and getattr(C, "REQUIRE_CLEAN_TREE", True):
        sys.exit("  working tree is DIRTY — a paid result could not be attributed to a "
                 "revision. Commit first.")
    n = next_plate_attempt(location_id)
    if n > 1:
        prev = plate_attempt_dir(location_id, n - 1) / "qc.json"
        if not prev.exists():
            sys.exit(f"  attempt {n-1:03d} has no recorded QC verdict. One candidate per "
                     f"location: judge the last one before buying another.")
        # A RECORDED REJECTION IS NOT PERMISSION TO BUY ANOTHER. The guard used to stop
        # only at "the last one was never judged", which let a duplicate attempt through
        # on stale state after 002 had already been rejected — Rs 5 for nothing. Rejection
        # is the normal outcome; it must not silently authorise the next purchase.
        if not override:
            sys.exit(f"  attempt {n-1:03d} exists and was judged. Buying attempt {n:03d} "
                     f"needs an explicit reason:\n"
                     f"    make.py plate-candidate {location_id} --override \"why\"\n"
                     f"  Check whether another session already produced what you need.")
    # Deriving from ACCEPTED footage is stronger CONDITIONING, not a guarantee: the model
    # can still redesign things while removing the character, which is what QC must catch.
    # Attempt 001 established why prose alone cannot work — it pins arrangement and not
    # form, so it obeyed the geography exactly and invented a different rug and chair from
    # the episode already accepted. A plate that disagrees with published footage is worse
    # than no plate, because the plate wins for every future frame.
    refs, src_meta = [], {}
    if source:
        eid, _, sid = source.partition("/")
        sd = ep_dir(eid)
        sframe = sd / "frames" / f"{sid}.png"
        if not sframe.exists():
            sys.exit(f"  no frame at {sframe}")
        if clip_verdict(sd, sid) != "ACCEPTED":
            sys.exit(f"  {source} is {clip_verdict(sd, sid)}. A plate may only be derived "
                     f"from footage a human has ACCEPTED.")
        refs = [sframe]
        src_meta = {"derived_from": source, "source_frame_sha": sha_file(sframe)}
        # who to remove comes from the SOURCE SHOT's own cast, so this works for any
        # episode, any location and any character rather than for one bear in one room
        try:
            sshots = json.loads((sd / "shots.json").read_text())
            occupants = next(x for x in sshots if x["id"] == sid).get("cast") or []
        except Exception:
            sys.exit(f"  cannot read the cast of {source}; refusing to guess who is in "
                     f"the frame we are paying to clear")
        prompt = compile_plate_completion_prompt(location_id, occupants)
        origin = "DERIVED_FROM_ACCEPTED_FRAME"
    else:
        prompt = compile_plate_prompt(location_id)
        origin = "GENERATED_LOCATION_PLATE"

    d = plate_attempt_dir(location_id, n)
    d.mkdir(parents=True, exist_ok=True)
    print(f"  {location_id}: generating plate candidate {n:03d} ({origin})")
    gen_image(client(), prompt, refs, d / "plate.png", kind="image",
              detail=f"plate:{location_id}/{n:03d}")
    (d / "provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "kind": "LOCATION_PLATE_CANDIDATE", "canonical": False,
         "location_id": location_id, "location_version": location_version(location_id),
         "attempt": n, "source": origin, **src_meta,
         "override_reason": override,
         "image_prompt": prompt,
         "image_prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
         "sha": sha_file(d / "plate.png"),
         "model": C.IMAGE_MODEL, "aspect": C.IMAGE_ASPECT,
         "compiler": PLATE_COMPILER_VERSION,
         "revision": rev, "cost_inr": C.INR_PER_IMAGE}, indent=2))
    print(f"    -> {d / 'plate.png'}")
    print(f"    QC it, then: make.py plate-approve {location_id} --attempt {n}")


def promote_location_plate(eid, shot_id):
    """Canonicalise an ALREADY ACCEPTED frame as location visual authority. Rs 0.

    Provenance says exactly what happened — CANONICALIZED_FROM_ACCEPTED_FRAME — rather
    than pretending a lucky generation was always canon.
    """
    d = ep_dir(eid); ep = load_ep(eid)
    shots = json.loads((d / "shots.json").read_text())
    try:
        shot = next(s for s in shots if s["id"] == shot_id)
    except StopIteration:
        sys.exit(f"  no shot '{shot_id}' in {eid}")
    location_id = shot_location(shot)
    if not location_id:
        sys.exit(f"  {eid}/{shot_id}: no location_id")
    if location_id not in BIBLE["locations"]:
        sys.exit(f"  {eid}/{shot_id}: unknown location '{location_id}'")

    frame = d / "frames" / f"{shot_id}.png"
    frame_prov = d / "frames" / f"{shot_id}.provenance.json"
    clip = d / "clips" / f"{shot_id}.mp4"
    clip_prov = d / "clips" / f"{shot_id}.provenance.json"
    if not frame.exists() or not frame_prov.exists():
        sys.exit(f"  {eid}/{shot_id}: source frame/provenance missing")
    try:
        fpv = json.loads(frame_prov.read_text())
    except Exception:
        sys.exit(f"  {eid}/{shot_id}: unreadable frame provenance")
    if fpv.get("status") != "COMPLETE":
        sys.exit(f"  {eid}/{shot_id}: source frame status={fpv.get('status')}")
    if fpv.get("sha") != sha_file(frame):
        sys.exit(f"  {eid}/{shot_id}: source frame checksum mismatch")

    # The accepted CLIP proves this exact frame participated in footage a human judged
    # acceptable. Do not canonicalise an unreviewed still because its PNG looks plausible.
    cok, cwhy = usable(clip, clip_prov, clip_identity(shot, frame, ep["mode"]))
    if not cok:
        sys.exit(f"  {eid}/{shot_id}: source clip is not provably current ({cwhy})")
    if clip_verdict(d, shot_id) != "ACCEPTED":
        sys.exit(f"  {eid}/{shot_id}: clip verdict is {clip_verdict(d, shot_id)}, "
                 f"not ACCEPTED")

    dest, dest_prov = location_plate_paths(location_id)
    source_sha = sha_file(frame)
    if dest.exists() or dest_prov.exists():
        ok, why, existing, _pv = prove_location_plate(location_id)
        if not ok:
            sys.exit(f"  existing location plate for '{location_id}' is invalid ({why}); "
                     f"refusing to overwrite canon")
        if sha_file(existing) == source_sha:
            print(f"  {location_id}: canonical plate already matches {eid}/{shot_id}, "
                  f"skipping")
            return
        sys.exit(f"  {location_id}: canonical plate already exists with DIFFERENT pixels. "
                 f"Canon is immutable; create an explicit new version instead.")

    dest.parent.mkdir(parents=True, exist_ok=True)     # creation belongs to the writer
    write_atomic(dest, frame.read_bytes())
    payload = {
        "status": "COMPLETE", "kind": "LOCATION_PLATE", "canonical": True,
        "location_id": location_id,
        "location_version": location_version(location_id),
        "source": "CANONICALIZED_FROM_ACCEPTED_FRAME",
        "source_episode": eid, "source_shot": shot_id,
        "source_frame_sha": source_sha,
        "source_frame_provenance_sha": sha_file(frame_prov),
        "source_clip_sha": sha_file(clip),
        "source_clip_provenance_sha": sha_file(clip_prov),
        "source_clip_verdict": "ACCEPTED",
        "input_hash": input_hash(location_id=location_id, source_frame_sha=source_sha,
                                 source_clip_sha=sha_file(clip),
                                 contract=LOCATION_PLATE_CONTRACT_VERSION),
        "sha": sha_file(dest),
        "contract_version": LOCATION_PLATE_CONTRACT_VERSION,
        "revision": build_revision(),
        "canonicalized_at": time.strftime("%F %T"),
        "cost_inr": 0,
    }
    write_atomic(dest_prov, json.dumps(payload, indent=2).encode())
    try:
        shown = dest.relative_to(ROOT)
    except ValueError:
        shown = dest              # a plate store outside the repo is legitimate
    print(f"  {location_id}: CANONICALIZED_FROM_ACCEPTED_FRAME {eid}/{shot_id} "
          f"-> {shown}  Rs 0")


def clip_verdict(d, sid):
    """The recorded QC verdict for one shot's clip, or PENDING_QC if there is none."""
    prov = d / "clips" / f"{sid}.provenance.json"
    if not prov.exists():
        return "PENDING_QC"
    return json.loads(prov.read_text()).get("qc", "PENDING_QC")


def frozen_prefix(eid, shots):
    """How many leading shots are ACCEPTED, current, and therefore IMMUTABLE INVENTORY.

    Footage that has been paid for and passed QC is not a draft. Replanning an episode to
    make it longer must not rewrite it, because rewriting changes its identity hash and
    silently demands that we buy the same seconds twice — the exact behaviour the resume
    system exists to prevent.

    A PREFIX, deliberately. Accepted shots after a rejected one are not appendable
    inventory: continuity runs forward, so the frozen region has to be unbroken from the
    start or the continuation contract has nothing to attach to.
    """
    d = ep_dir(eid)
    n = 0
    for s in shots:
        clip = d / "clips" / f"{s['id']}.mp4"
        frame = d / "frames" / f"{s['id']}.png"
        if not (clip.exists() and frame.exists()):
            break
        ok, _ = usable(clip, d / "clips" / f"{s['id']}.provenance.json",
                       clip_identity(s, frame, load_ep(eid)["mode"]))
        if not ok or clip_verdict(d, s["id"]) != "ACCEPTED":
            break
        n += 1
    return n


def continuation_contract(last_shot):
    """What the first NEW shot must begin from, stated as a hard constraint.

    The planner is not asked to remember or re-derive the frozen footage. It is handed the
    exact end state of the last accepted shot and told that its first shot starts there.
    """
    end = last_shot.get("end_state") or {}
    vis = end.get("visual") or {}
    body = {k: v for k, v in end.items() if k != "visual"}
    return (
        "CONTINUATION. This episode ALREADY HAS accepted, published-quality footage. You "
        "are writing what happens NEXT, not rewriting what exists.\n\n"
        f"The last existing shot is {last_shot['id']}. It ENDS in exactly this state:\n"
        f"{json.dumps(body, indent=2)}\n\n"
        f"Its final framing was: {json.dumps(vis, indent=2)}\n\n"
        "HARD RULES FOR THE CONTINUATION:\n"
        f"  1. Your FIRST shot's start_state must equal that end state EXACTLY, field for "
        f"field. {last_shot['id']} has already been generated and cannot change.\n"
        "  2. Number your shots continuing from the existing ones. Do not restart at s01.\n"
        "  3. Do not re-describe or re-tell what already happened. Continue forward.\n"
        "  4. Every rule about showing transitions inside shots still applies across this "
        "boundary: nothing may change between the last existing shot and your first one.\n\n"
    )


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

    # APPEND-ONLY. Accepted footage is inventory, not a draft.
    existing = json.loads(dest.read_text()) if dest.exists() else []
    frozen = existing[:frozen_prefix(eid, existing)] if existing else []
    n_new = ep["shots"] - len(frozen)
    if frozen:
        print(f"  {len(frozen)} shot(s) FROZEN — accepted, paid for, will not be replanned")
        for f_ in frozen:
            print(f"    {f_['id']}: {f_['motion'][:62]}")
        if n_new <= 0:
            sys.exit(f"  brief asks for {ep['shots']} shots and {len(frozen)} are already "
                     f"accepted. Raise `shots:` in episodes/{eid}.yaml to extend.")
        print(f"  planning {n_new} NEW shot(s) to continue from {frozen[-1]['id']}")
    elif dest.exists():
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

    contract_block = continuation_contract(frozen[-1]) if frozen else ""
    next_n = len(frozen) + 1
    count_line = (f"SHOT COUNT: exactly {n_new} NEW shots, numbered s{next_n:02d} onward"
                  if frozen else f"SHOT COUNT: exactly {ep['shots']}")

    prompt = f"""You are a storyboard director for a preschool animation channel.

EPISODE: {ep['title']}  (mode: {ep['mode']})
IDEA: {ep['idea']}
{count_line}

{contract_block}{role_demand}MODE DIRECTION
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
{SHOT_SCHEMA.replace("{vocab}", vocab_block())}"""

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
        shots_ = frozen + d.get("shots", [])
        try:
            # frozen shots keep the framing they were GENERATED with; reassigning them
            # would change their identity and stale the footage we are protecting
            shots_ = camera.assign(shots_, ep, BIBLE, frozen=len(frozen))
            return shots_, d.get("requirement_results", {}), None
        except camera.Unsatisfiable as e:
            return shots_, d.get("requirement_results", {}), str(e)

    if not frozen:
        print(f"  planning {ep['shots']} shots for {eid} (schema-enforced)...")
    shots, results, cam_err = call()
    issues = validate(shots, ep, BIBLE, results, frozen=len(frozen))
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
        issues = validate(shots, ep, BIBLE, results, frozen=len(frozen))
        if cam_err:
            from validate import Issue
            issues.append(Issue("ERROR", "COVERAGE_ROLES_INSUFFICIENT", "-",
                "coverage_role", cam_err))
        if report(issues):
            (d / "shots.rejected.json").write_text(json.dumps(shots, indent=2))
            sys.exit("\n  PLAN REJECTED after one repair. Nothing generated, nothing "
                     "spent on images or video. Rejected plan saved for inspection.")
        print("  repair succeeded")

    # The whole point of append-only: prove the protected region came through unchanged.
    # A single altered field here would restale paid, accepted footage.
    if shots[:len(frozen)] != frozen:
        (d / "shots.rejected.json").write_text(json.dumps(shots, indent=2))
        sys.exit("  FROZEN_SHOTS_MODIFIED: planning altered already-accepted shots. "
                 "Nothing written, nothing spent. Rejected plan saved for inspection.")

    dest.write_text(json.dumps(shots, indent=2))
    (d / "shots.provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "input_hash": ihash, "sha": sha_file(dest),
         "model": C.PLANNER_MODEL, "requirement_results": results,
         "frozen_shots": [f_["id"] for f_ in frozen]}, indent=2))
    print(f"  -> {dest}  ({len(shots)} shots)")
    for s in shots:
        print(f"     {s['id']}: {s['motion'][:70]}")


# ──────────────────────── reference compiler ─────────────────────────
def clip_identity(shot, frame, mode):
    """One definition of what a clip was generated FROM, consumed by both the resume check
    and the paid request — the same single-source-of-truth rule as frame_identity.

    The generation PARAMETERS belong in here, not just the prompt. Without them, resume
    would treat a clip produced under an older contract as current, silently keeping
    rejected footage after the contract that produced it had changed.
    """
    # Hash what the request ACTUALLY carries, not what we would like it to carry. A
    # parameter this surface refuses is never sent, so it is not part of what produced the
    # clip and must not change its identity — otherwise every clip we already paid for
    # goes stale the moment we merely ATTEMPT an unsupported parameter.
    extra = {}
    neg = veo_negative_prompt(BIBLE, mode)
    if neg and C.VIDEO_NEGATIVE_PROMPT_SUPPORTED:
        extra["negative"] = neg
    if C.VIDEO_ENHANCE_PROMPT is not None:
        extra["enhance"] = C.VIDEO_ENHANCE_PROMPT
    if C.VIDEO_SEED is not None:
        extra["seed"] = C.VIDEO_SEED
    return input_hash(shot=shot, frame_sha=sha_file(frame), model=C.VIDEO_MODEL,
                      res=C.VIDEO_RES, secs=C.VIDEO_SECONDS, **extra)


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
        ihash = portrait_identity(c, BIBLE)
        ok, why = usable(dest, prov_p, ihash)
        if ok:
            print(f"  {key}: valid, skipping"); continue
        if dest.exists():
            print(f"  {key}: REGENERATING — {why}")
        print(f"  {key}: generating canonical portrait")
        prompt = (f"{BIBLE['style_lock']}\n\nFull-body character reference sheet on a "
                  f"plain white background. Front view, neutral standing pose, neutral "
                  f"expression, even lighting, no shadows, no props, no scenery.\n\n"
                  f"CHARACTER: {c['features']}")
        gen_image(cl, prompt, [], dest, kind="image", detail=f"portrait:{key}")
        prov_p.write_text(json.dumps(
            {"status": "COMPLETE", "source": "GENERATED", "input_hash": ihash,
             "sha": sha_file(dest), "model": C.IMAGE_MODEL,
             "image_prompt": prompt,
             "image_prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
             "cost_inr": C.INR_PER_IMAGE}, indent=2))


# ────────────────────────────── frames ───────────────────────────────
def stage_frames(eid, only=None):
    d = ep_dir(eid); ep = load_ep(eid)
    shots = json.loads((d / "shots.json").read_text())
    if report(validate(shots, ep, BIBLE, frozen=frozen_prefix(eid, shots))):
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

        # A frame under an ACCEPTED clip is paid, judged footage. Its identity may go
        # stale for reasons that cannot change what is already on disk — a new mandatory
        # reference, a bible edit — and regenerating it would rewrite the exact pixels the
        # accepted clip was rendered from, invalidating the clip too. stage_episode already
        # skipped these; entering through stage_frames directly did not, which left roughly
        # Rs 111 of accepted E01 footage one command away from being destroyed.
        if clip_verdict(d, shot["id"]) == "ACCEPTED" and dest.exists():
            print(f"  {shot['id']}: frame is under an ACCEPTED clip — protected, skipping")
            prev = dest; continue

        res = resolve_frame_refs(d, shots, idx, BIBLE, loc, policy[idx][0])
        if res.error:
            sys.exit(f"  {shot['id']}: {res.error}")
        refs, ref_ids = res.paths, res.ref_ids
        legend = []
        for i_, (role, key, _sha) in enumerate(ref_ids):
            if role == "identity":
                legend.append(f"Image {i_}: canonical reference for "
                              f"{BIBLE['cast'][key]['name']}")
            elif role == "world":
                legend.append(f"Image {i_}: canonical visual reference for "
                              f"{BIBLE['locations'][key]['name']}. Preserve the visual "
                              f"form, materials, proportions and design of the persistent "
                              f"environment objects shown in it. Use WORLD GEOGRAPHY below "
                              f"for their spatial arrangement.")
            elif role == "temporal":
                # NOT "identical camera". TEMPORAL_REFERENCE exists precisely BECAUSE the
                # composition is allowed to change; demanding an identical camera here
                # contradicted the new framing the camera compiler had just assigned.
                # Freeze what this reference is actually authoritative for.
                # "every ... object in it" was still too strong: a new composition may
                # legitimately crop objects out. Preserve FORM, not visibility.
                legend.append(f"Image {i_}: the previous moment in this same scene. "
                              f"Preserve the visual identity and form of characters and "
                              f"persistent objects, the room layout, and the lighting "
                              f"continuity. Recompose the scene according to the new shot "
                              f"described below.")

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

        # "identical in every shot" claimed an authority the words cannot carry. Pixel
        # identity comes from references, not adjectives, and asserting it in prose only
        # created false confidence when auditing prompts. State the invariants; let the
        # reference images be the ones that promise sameness.
        prompt = ("\n".join(legend) + f"\n\n{BIBLE['style_lock']}\n\n"
                  f"WORLD: {loc['description']}\n\n"
                  f"WORLD GEOGRAPHY: {loc['geography']}\n\n"
                  f"SHOT: {shot.get('frame_compiled') or shot['frame']}\n\n"
                  "Characters must match their canonical reference images exactly: same "
                  "colour, clothing, proportions and face. Only characters listed for this "
                  "shot may be visible. No visible text or lettering.")
        print(f"  {shot['id']}: generating first frame ({len(refs)} refs)")
        gen_image(cl, prompt, refs, dest, kind="image", detail=f"frame:{eid}/{shot['id']}")
        prov_p.write_text(json.dumps(
            {"status": "COMPLETE", "source": "GENERATED", "model": C.IMAGE_MODEL,
             # Record what we actually SENT. The clip path stored its prompt from the
             # start and the frame path never did, so every image we had paid for was
             # unauditable: we could see which references went in but not the words. A
             # diagnosis you cannot check against the real request is a guess.
             "image_prompt": prompt,
             "image_prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
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
          f"{C.VIDEO_SECONDS}s / audio-in-prompt=NO / "
          f"enhance_prompt={C.VIDEO_ENHANCE_PROMPT} / seed={C.VIDEO_SEED} / "
          f"negative_prompt=YES")
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
    if report(validate(shots, load_ep(eid), BIBLE,
                       frozen=frozen_prefix(eid, shots))):
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
        negative = veo_negative_prompt(BIBLE, load_ep(eid)["mode"])
        chash = clip_identity(shot, frame, load_ep(eid)["mode"])
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
                    duration_seconds=C.VIDEO_SECONDS,
                    **({"negative_prompt": negative} if negative
                       and C.VIDEO_NEGATIVE_PROMPT_SUPPORTED else {}),
                    **({"enhance_prompt": C.VIDEO_ENHANCE_PROMPT}
                       if C.VIDEO_ENHANCE_PROMPT is not None else {}),
                    **({"seed": C.VIDEO_SEED} if C.VIDEO_SEED is not None else {})),
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
                 "negative_prompt": negative,
                 "enhance_prompt": C.VIDEO_ENHANCE_PROMPT, "seed": C.VIDEO_SEED,
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


CAMERA_LOCK_VERSION = "1"


def _grey_crop(path, box):
    from PIL import Image
    return Image.open(path).convert("L").crop(box)


def _mean_abs_diff(a, b):
    from PIL import ImageChops
    h = ImageChops.difference(a, b).histogram()
    return sum(i * c for i, c in enumerate(h)) / max(1, sum(h))


def measure_camera_lock(clip, search=12, step=2, grid=3, structure_only=False):
    """How far the WORLD moved between a clip's first and last frame. Free, deterministic.

    Whole-frame alignment does not work, and finding that out cost nothing: the subject
    moves too, so its pixels drag the best-fit offset toward a compromise that describes
    neither the camera nor the bear. E01/s01 measured 0,-4 whole-frame and +8,+6 on the
    static wall alone.

    So measure TILES. A camera move shifts every tile by the same amount; a subject move
    shifts one or two. The median offset across tiles is the camera, and the fraction of
    tiles that agree with it is how much to believe it. That is generic — it needs no
    knowledge of where the subject is, which is exactly the knowledge we do not have.

    Returns dx, dy, the agreement fraction, and whether the camera held still.
    """
    tmp = Path(str(clip) + ".lockcheck")
    tmp.mkdir(exist_ok=True)
    f0, f1 = tmp / "first.png", tmp / "last.png"
    os.system(f'ffmpeg -nostdin -v error -y -i "{clip}" -vf "select=eq(n\\,0)" '
              f'-frames:v 1 "{f0}" 2>/dev/null')
    os.system(f'ffmpeg -nostdin -v error -y -sseof -0.1 -i "{clip}" -frames:v 1 '
              f'"{f1}" 2>/dev/null')
    if not (f0.exists() and f1.exists()):
        shutil_rmtree(tmp)
        return None
    from PIL import Image, ImageChops, ImageFilter
    A = Image.open(f0).convert("L")
    B = Image.open(f1).convert("L")
    if structure_only:
        # STRUCTURE, not sparkle. The particles we just proved pervasive are small, bright
        # and moving — exactly the signal a translation search locks onto. Blur them away
        # and what is left is walls, window, bed and floor. If a shot is still unstable
        # after this, the WORLD is moving, which is a far more serious finding than motes.
        A = A.filter(ImageFilter.GaussianBlur(3)).resize(
            (A.width // 2, A.height // 2), Image.LANCZOS)
        B = B.filter(ImageFilter.GaussianBlur(3)).resize(
            (B.width // 2, B.height // 2), Image.LANCZOS)
        search = max(4, search // 2)
    w, h = A.size
    tw, th = w // grid, h // grid
    offsets = []
    for gy in range(grid):
        for gx in range(grid):
            box = (gx * tw, gy * th, (gx + 1) * tw, (gy + 1) * th)
            a, b = A.crop(box), B.crop(box)
            inner = (search + 2, search + 2, a.width - search - 2, a.height - search - 2)
            if inner[2] <= inner[0] or inner[3] <= inner[1]:
                continue
            ref = a.crop(inner)
            # A FEATURELESS tile — a flat wooden wall — has no alignment signal at all:
            # every offset fits equally, it votes 0,0 by default, and it would make a
            # close-up on a plain wall look like the steadiest shot we ever made. Only
            # textured tiles get a vote.
            hist = ref.histogram()
            total = sum(hist) or 1
            mean = sum(i * c for i, c in enumerate(hist)) / total
            var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
            if var < 120:
                continue
            best = None
            for dy in range(-search, search + 1, step):
                for dx in range(-search, search + 1, step):
                    e = _mean_abs_diff(ref, ImageChops.offset(b, dx, dy).crop(inner))
                    if best is None or e < best[0]:
                        best = (e, dx, dy)
            offsets.append((best[1], best[2]))
    shutil_rmtree(tmp)
    if not offsets:
        return None
    # FIT A ZOOM before calling anything unstable. Tiles that disagree wildly are not
    # necessarily a deforming world: under a slow push-in every tile moves AWAY from the
    # centre, so the offsets are inconsistent as translations and perfectly consistent as
    # one scale change. Fitting it is the difference between "the room is dissolving" and
    # "the camera crept forward 2%", and only one of those is repairable.
    centres = [((gx + 0.5) * tw - w / 2, (gy + 0.5) * th - h / 2)
               for gy in range(grid) for gx in range(grid)]
    centres = centres[:len(offsets)] if len(centres) >= len(offsets) else centres
    num = sum(rx * dx + ry * dy for (rx, ry), (dx, dy) in zip(centres, offsets))
    den = sum(rx * rx + ry * ry for rx, ry in centres)
    c = num / den if den else 0.0
    raw_err = sum(abs(dx) + abs(dy) for dx, dy in offsets) / len(offsets)
    zoom_err = sum(abs(dx - c * rx) + abs(dy - c * ry)
                   for (rx, ry), (dx, dy) in zip(centres, offsets)) / len(offsets)

    xs = sorted(o[0] for o in offsets); ys = sorted(o[1] for o in offsets)
    mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
    # agreement WITHIN A TOLERANCE, not exact equality. Tiles land a pixel or two apart
    # because generated particles add noise to every window; demanding identical offsets
    # would report disagreement on a camera move that every tile actually saw.
    agree = sum(1 for dx, dy in offsets
                if abs(dx - mx) <= 2 and abs(dy - my) <= 2) / len(offsets)
    # a zoom is only claimed when modelling it EXPLAINS most of the motion. Otherwise the
    # honest answer stays "no single motion explains this".
    explains = (raw_err - zoom_err) / raw_err if raw_err > 0.5 else 0.0
    scale = round((1 - c) * 100, 2)          # >100 = pushed in, <100 = pulled back
    return {"dx": mx, "dy": my, "tiles": len(offsets), "grid_tiles": grid * grid,
            "structure_only": structure_only,
            "zoom_percent": scale, "zoom_explains": round(explains, 2),
            "is_zoom": explains >= 0.35 and abs(scale - 100) >= 0.5,
            "agreement": round(agree, 2),
            "per_tile": offsets,
            "still": (mx, my) == (0, 0),
            # a shift most tiles agree on is the CAMERA; one or two tiles disagreeing is
            # the subject, which is exactly what a locked camera shot should look like
            "confident": agree >= 0.5}


def shutil_rmtree(p):
    import shutil as _sh
    _sh.rmtree(p, ignore_errors=True)


STABILIZER_VERSION = "1"


def stabilized_identity(source_sha, zoom_percent):
    return input_hash(source_clip_sha=source_sha, zoom_percent=zoom_percent,
                      stabilizer=STABILIZER_VERSION)


def stage_stabilize(eid):
    """Remove the camera move nobody asked for. Rs 0, deterministic, reversible.

    Veo adds a slow push-in to shots specified as locked cameras — measured at 2.2% on
    E01/s01 and 2.9% on s04 over four seconds. It is RIGID, which is the whole point: a
    rigid motion can be undone by an equal and opposite one, and the picture underneath is
    the picture we paid for.

    The paid clip is NEVER touched. A stabilised copy is written alongside it with
    provenance naming the source and the correction, exactly like the closing hold. Accepted
    inventory stays byte-identical; what changes is which file the master is cut from.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    out_dir = d / "stabilized"
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        if not c.exists() or clip_verdict(d, s["id"]) != "ACCEPTED":
            continue
        m = measure_camera_lock(c)
        if not m:
            print(f"  {s['id']}: could not measure")
            continue
        # MEASURE -> CLASSIFY -> CORRECT ONLY IF RIGID. A correction applied to motion the
        # model does not explain would distort genuine character movement to flatten a
        # number, which is the worst thing an automatic fix can do.
        if not m.get("is_zoom"):
            why = ("no unrequested zoom to remove" if abs(m["zoom_percent"] - 100) < 0.5
                   else f"motion is not confidently rigid — a fitted zoom explains only "
                        f"{int(m['zoom_explains'] * 100)}% of it, so nothing is corrected")
            print(f"  {s['id']}: {why}")
            continue
        k = m["zoom_percent"] / 100.0 - 1.0
        secs = media_duration(c)
        w, h, fps = video_geometry(c)
        n = max(2, int(round(secs * fps)))
        dest = out_dir / f"{s['id']}.mp4"
        prov = out_dir / f"{s['id']}.provenance.json"
        ident = stabilized_identity(sha_file(c), m["zoom_percent"])
        ok, _why = usable(dest, prov, ident)
        if ok:
            print(f"  {s['id']}: already stabilised and current")
            continue
        # start zoomed in by exactly the drift and ease back to 1.0, so the two motions
        # cancel and the delivered frame is the same size it always was
        z = f"(1+{k})/(1+{k}*on/{n - 1})"
        vf = (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s={w}x{h}:fps={fps}")
        rc = os.system(f'ffmpeg -nostdin -y -i "{c}" -vf "{vf}" -c:v libx264 -crf 20 '
                       f'-preset medium -pix_fmt yuv420p -an "{dest}" 2>/dev/null')
        if rc != 0 or not dest.exists():
            print(f"  {s['id']}: ffmpeg could not stabilise")
            continue
        after = measure_camera_lock(dest)
        prov.write_text(json.dumps(
            {"status": "COMPLETE", "kind": "STABILIZED_CLIP", "episode": eid,
             "shot": s["id"], "origin": "DERIVED_FROM_ACCEPTED_CLIP",
             "source_clip_sha": sha_file(c), "removed_zoom_percent": m["zoom_percent"],
             "before": {"zoom_percent": m["zoom_percent"], "agreement": m["agreement"]},
             "after": {"zoom_percent": after["zoom_percent"],
                       "agreement": after["agreement"]},
             "input_hash": ident, "sha": sha_file(dest), "cost_inr": 0,
             "stabilizer": STABILIZER_VERSION, "revision": build_revision()}, indent=2))
        print(f"  {s['id']}: removed a {m['zoom_percent'] - 100:+.1f}% push-in — "
              f"tile agreement {m['agreement']:.2f} -> {after['agreement']:.2f}")


def provable_stabilized(eid, sid):
    """The stabilised copy of a clip, only if it provably came from the CURRENT paid one."""
    d = ep_dir(eid)
    dest = d / "stabilized" / f"{sid}.mp4"
    prov = d / "stabilized" / f"{sid}.provenance.json"
    src = d / "clips" / f"{sid}.mp4"
    if not (dest.exists() and prov.exists() and src.exists()):
        return None
    try:
        pv = json.loads(prov.read_text())
    except Exception:
        return None
    ok, _why = usable(dest, prov,
                      stabilized_identity(sha_file(src), pv.get("removed_zoom_percent")))
    return dest if ok else None


def stage_lock(eid):
    """Measure camera lock on every clip. Rs 0.

    "Locked static camera" is a sentence we send to a provider that has ignored five other
    sentences. This is the first camera instruction we can actually CHECK.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        if not c.exists():
            continue
        wanted = "static" in json.dumps(s.get("camera") or "").lower()
        m = measure_camera_lock(c)
        if not m:
            print(f"  {s['id']}: could not measure")
            continue
        if m.get("is_zoom"):
            direction = "PUSHED IN" if m["zoom_percent"] > 100 else "PULLED BACK"
            verdict = (f"{direction} {abs(m['zoom_percent'] - 100):.1f}% "
                       f"({int(m['zoom_explains'] * 100)}% of the motion is that zoom)")
        elif not m["confident"]:
            # tiles disagreeing means NO single translation explains the frame. That is
            # not a camera drift and must not be reported as one — it is an unstable
            # picture, and saying which kind it is needs eyes, not arithmetic.
            verdict = "UNSTABLE — no single camera motion explains it"
        elif m["still"]:
            verdict = "LOCKED"
        else:
            verdict = f"DRIFTS {m['dx']:+d},{m['dy']:+d} px"
        flag = ("" if (m["confident"] and m["still"]) or not wanted
                else "   <- asked for a LOCKED camera")
        print(f"  {s['id']}: {verdict}  ({int(m['agreement'] * 100)}% of "
              f"{m['tiles']} textured tiles agree, "
              f"{m['grid_tiles'] - m['tiles']} too flat to vote){flag}")


CONTACT_SHEET_VERSION = "1"


def contact_sheet(clip, dest, samples=12, cols=4):
    """A grid of uniformly spaced frames from a clip. Free, offline, deterministic.

    Three samples — first, mid, last — is what our QC has always looked at, and it is how a
    generated effect that BUILDS over a shot escapes judgement: sparse at the start, all
    over the room by the end, and the middle frame ambiguous. A shot is judged over time or
    it is not judged.
    """
    secs = media_duration(clip)
    if not secs:
        return None
    rate = samples / secs
    rc = os.system(f'ffmpeg -nostdin -y -i "{clip}" -vf '
                   f'"fps={rate:.4f},scale=480:-2,tile={cols}x{-(-samples // cols)}" '
                   f'-frames:v 1 "{dest}" 2>/dev/null')
    return dest if rc == 0 and dest.exists() else None


def stage_contact(eid):
    """Contact sheets for every clip that exists. Rs 0. Look at these before judging."""
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    out_dir = d / "qcframes"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        if not c.exists():
            continue
        sheet = contact_sheet(c, out_dir / f"{s['id']}_sheet.png")
        if sheet:
            made.append(sheet)
            print(f"  {s['id']}: 12 samples -> {sheet}  ({clip_verdict(d, s['id'])})")
    if not made:
        print("  no clips to sample")


RELEASE_BUILDER_VERSION = "1"


def release_gate(eid):
    """Everything that must be TRUE before an episode is handed to a platform. Rs 0.

    A release gate is not a quality opinion — it is the set of failures that are cheaper to
    catch here than after an upload: no audio, audio that stops before the picture, a
    programme nobody measured, footage that is not provably accepted.
    """
    d = ep_dir(eid)
    final = d / "episode.mp4"
    problems = []
    if not final.exists():
        return final, ["no assembled episode — run assemble"]
    rep_p = d / "audio.json"
    if not rep_p.exists():
        problems.append("no audio.json — run `audio` and let the arithmetic judge the mix")
    else:
        rep = json.loads(rep_p.read_text())
        if rep.get("sha_of_episode") not in (None, sha_file(final)):
            problems.append("audio.json describes a different cut than episode.mp4")
        for probe, result in (rep.get("probes") or {}).items():
            if result == "FAIL":
                problems.append(f"{probe}: {rep.get('detail', {}).get(probe, 'FAIL')}")
    shots = json.loads((d / "shots.json").read_text())
    if not any(clip_verdict(d, s["id"]) == "ACCEPTED" for s in shots):
        problems.append("no ACCEPTED footage in this episode")
    return final, problems


def stage_release(eid):
    """Build the release folder: master, thumbnail, metadata, and what a human must do.

    Deliberately stops short of uploading. Publishing is an outward-facing, hard-to-undo
    act on Pavan's own channel, and it needs his account, his judgement and his consent —
    not a script that already has the credentials. What this stage removes is every excuse
    that is not consent.
    """
    d = ep_dir(eid)
    ep = load_ep(eid)
    final, problems = release_gate(eid)
    rel = d / "release"
    rel.mkdir(parents=True, exist_ok=True)
    if problems:
        print(f"  {eid} is NOT releasable yet:")
        for p in problems:
            print(f"    - {p}")
        return

    # the thumbnail comes from footage a human ACCEPTED, never from a rejected or
    # unreviewed frame — a thumbnail is the one frame most people will ever see
    shots = json.loads((d / "shots.json").read_text())
    accepted = [s["id"] for s in shots if clip_verdict(d, s["id"]) == "ACCEPTED"]
    src = d / "frames" / f"{accepted[0]}.png"
    thumb = rel / "thumbnail.png"
    w, h, _fps = video_geometry(d / "clips" / f"{accepted[0]}.mp4")
    os.system(f'ffmpeg -nostdin -y -i "{src}" -vf '
              f'"scale=1280:-2:flags=lanczos" "{thumb}" 2>/dev/null')

    picture = stream_duration(final, "v") or media_duration(final)
    audio_rep = json.loads((d / "audio.json").read_text())
    meta = {
        "kind": "EPISODE_RELEASE", "episode": eid, "builder": RELEASE_BUILDER_VERSION,
        "title": ep["title"],
        "description": (
            f"{ep['title']} — a calm bedtime moment from Coco Spark TV.\n\n"
            f"Original characters, original music, and every second reviewed by hand "
            f"before it was published.\n"),
        "tags": ["coco spark", "bedtime", "preschool", "calm", "sleep", "story time"],
        "made_for_kids": True,
        "category_hint": "Education (27) or Entertainment (24) — Pavan's call",
        "privacy_at_upload": "unlisted",
        "altered_or_synthetic_disclosure": {
            "decision": "REVIEW",
            "why": ("YouTube requires disclosure for meaningfully altered or synthetic "
                    "content that could be MISTAKEN FOR REAL. This is stylised preschool "
                    "animation with no real person, place or event depicted, so the "
                    "requirement does not obviously apply — but the decision is Pavan's "
                    "to make at upload, not a script's to assume."),
        },
        "runtime_seconds": picture,
        "delivered_lufs": audio_rep.get("delivered_lufs"),
        "geometry": {"w": w, "h": h},
        "aspect": "16:9 — publish as a NORMAL video, not a Short. Shorts are the vertical "
                  "upload path; a horizontal master should not be aimed at it.",
        "master_sha": sha_file(final),
        "thumbnail_sha": sha_file(thumb) if thumb.exists() else None,
        "revision": build_revision(),
    }
    (rel / "metadata.json").write_text(json.dumps(meta, indent=2))
    (rel / "CHECKLIST.md").write_text(
        f"# Releasing {eid} — {ep['title']}\n\n"
        f"Master: `{final}`  ({picture}s, {w}x{h}, "
        f"{audio_rep.get('delivered_lufs')} LUFS)\n"
        f"Thumbnail: `{thumb}`\n\n"
        "## Before uploading — the two things arithmetic cannot do\n\n"
        "1. WATCH it end to end. Not the frames, the film.\n"
        "2. LISTEN to it on headphones AND on a speaker. The mix measures -14.0 LUFS, "
        "which says nothing about whether the chord is pleasant, irritating, ominous or "
        "simply amateur. If it sounds synthetic and cheap, say so — the bed is a "
        "prototype, not a decision.\n\n"
        "## At upload\n\n"
        "- Visibility: UNLISTED first. Public is a separate, later decision.\n"
        "- Audience: YES, made for kids. This removes comments, notifications, cards, "
        "end screens and personalised ads — do not design around any of them.\n"
        "- Altered or synthetic content: decide per metadata.json; the honest answer for "
        "stylised animation with no real people is probably no, but it is your call.\n"
        "- Title, description and tags: metadata.json, edit freely.\n\n"
        "## After it processes\n\n"
        "- Play it back ON YouTube, on phone and on a TV if you can.\n"
        "- Check the volume against another kids' video. YouTube normalises loud material "
        "on playback; ours is quiet and should not be touched.\n"
        "- Note every defect the platform introduced or revealed, and bring them back — "
        "that list is the only reason this upload exists.\n")
    print(f"  {eid} is releasable.")
    print(f"    master     {final}  ({picture}s)")
    print(f"    thumbnail  {thumb}")
    print(f"    metadata   {rel / 'metadata.json'}")
    print(f"    checklist  {rel / 'CHECKLIST.md'}")
    print("  This stage does NOT upload. Publishing is yours to do, with your account "
          "and your judgement.")


def renderer_for(requirement):
    """PURE. The cheapest renderer PROVEN to satisfy a visual-change requirement.

    One definition, and every consumer calls it: the estimator that prices an episode, the
    validator that refuses a paid call nothing needs, and eventually the stage that renders
    it. Two copies of this rule would price one episode and render a different one.

    Returns (renderer, cost_class, why).
    """
    table = BIBLE.get("renderers") or {}
    free = [(k, v) for k, v in table.items()
            if requirement in (v.get("satisfies") or []) and v.get("cost") == "FREE"]
    if free:
        # cheapest first, and among free renderers the simplest wins
        order = ["STILL_HOLD", "PROGRAMMED_CAMERA"]
        free.sort(key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
        k, v = free[0]
        return k, "FREE", v.get("evidence", "")
    paid = [(k, v) for k, v in table.items()
            if requirement in (v.get("satisfies") or []) and v.get("cost") == "PAID"]
    if paid:
        k, v = paid[0]
        return k, "PAID", v.get("evidence", "")
    return None, None, f"no renderer in the bible claims to satisfy {requirement}"


def shot_visual_change(shot):
    """What this beat must visibly change. Absent means nobody declared it."""
    return shot.get("visual_change")


def estimate_episode(eid):
    """PURE-ish. What this plan will cost BEFORE anything is generated.

    GPT's rule, and it is the right one: we should never again discover unit economics
    after rendering. A plan whose numbers do not make sense gets redesigned while a
    redesign is still free.

    Costs are computed from the REAL policy compiler, not from a shot count — a frame that
    inherits predecessor pixels is free, and an episode that pretends otherwise
    overestimates itself into not being made.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    ep = load_ep(eid)
    done = frozen_prefix(eid, shots)
    lines, frames_paid, video_secs = [], 0, 0.0
    for i, s in enumerate(shots):
        if i < done:
            lines.append((s["id"], "ACCEPTED", 0.0, "already inventory"))
            continue
        pol = reference_policy(shots[i - 1] if i else None, s, BIBLE)[0]
        if pol == "PREDECESSOR_PIXELS":
            fcost, fwhy = 0.0, "inherits predecessor pixels"
        else:
            fcost, fwhy = C.INR_PER_IMAGE, f"first frame ({pol})"
            frames_paid += 1
        # WHY a paid clip exists, or whether it needs to. A Rs 32 call with no semantic
        # change that requires generated pixels is the single easiest rupee to not spend.
        need = shot_visual_change(s)
        renderer, cost_class, _why = renderer_for(need) if need else (None, None, "")
        if need and cost_class == "FREE":
            lines.append((s["id"], "FREE", fcost,
                          f"{fwhy} + {renderer} ({need} needs no generated pixels)"))
            continue
        vcost = C.INR_PER_VID_SEC * C.VIDEO_SECONDS
        video_secs += C.VIDEO_SECONDS
        reason = (f"{need}" if need else "visual_change NOT DECLARED")
        lines.append((s["id"], "TO BUY", fcost + vcost,
                      f"{fwhy} + {C.VIDEO_SECONDS}s clip — {reason}"))
    frames_inr = frames_paid * C.INR_PER_IMAGE
    video_inr = video_secs * C.INR_PER_VID_SEC
    total = frames_inr + video_inr
    worst = total * getattr(C, "SAFETY_MARGIN", 1.0)
    L = ledger()
    return {"episode": eid, "mode": ep["mode"], "shots": len(shots),
            "already_accepted": done, "paid_frames": frames_paid,
            "video_seconds": video_secs, "frames_inr": frames_inr,
            "video_inr": video_inr, "estimate_inr": round(total, 2),
            "reserved_worst_case_inr": round(worst, 2),
            "spent_inr": L["spent_inr"], "cap_inr": C.BUDGET_INR,
            "headroom_inr": round(C.BUDGET_INR - L["spent_inr"], 2),
            "fits": worst <= C.BUDGET_INR - L["spent_inr"],
            "runtime_seconds": round(video_secs + (
                C.ENDING_HOLD_SECONDS if provable_ending(eid) else 0), 2),
            "per_line": lines}


def stage_estimate(eid):
    """Print the production estimate. Rs 0, and it must be run before generation."""
    e = estimate_episode(eid)
    print(f"  {e['episode']} ({e['mode']}): {e['shots']} shots, "
          f"{e['already_accepted']} already accepted")
    for sid, state, inr, why in e["per_line"]:
        print(f"    {sid:5s} {state:9s} Rs {inr:7.2f}   {why}")
    print(f"  frames  {e['paid_frames']} x Rs {C.INR_PER_IMAGE} = Rs {e['frames_inr']:.2f}")
    print(f"  video   {e['video_seconds']}s x Rs {C.INR_PER_VID_SEC}/s = "
          f"Rs {e['video_inr']:.2f}")
    print(f"  ESTIMATE Rs {e['estimate_inr']:.2f}   reserved worst case "
          f"Rs {e['reserved_worst_case_inr']:.2f}")
    print(f"  headroom Rs {e['headroom_inr']:.2f} of the Rs {e['cap_inr']} cap")
    if e["video_seconds"]:
        print(f"  unit economics: Rs "
              f"{(e['estimate_inr'] / e['video_seconds']) * 60:.0f} per published minute "
              f"at this design")
    print("  FITS" if e["fits"] else "  DOES NOT FIT — redesign the episode, not the cap")
    return e


# ─────────────────────────────── ending ──────────────────────────────
def video_geometry(path):
    """Width, height and frame rate of a clip, so a derived shot MATCHES it.

    Read from the footage rather than assumed from config: the episode we are appending to
    is the authority on its own geometry, and a hardcoded 1280x720 is a defect waiting for
    the first episode shot at another size.
    """
    out = os.popen(f'ffprobe -v error -select_streams v:0 -show_entries '
                   f'stream=width,height,r_frame_rate -of csv=p=0 "{path}"').read().strip()
    try:
        w, h, rate = out.split(",")
        num, _, den = rate.partition("/")
        return int(w), int(h), round(int(num) / int(den or 1), 3)
    except ValueError:
        sys.exit(f"  could not read geometry from {path}")


BEAT_RENDERER_VERSION = "1"


def beat_identity(source_sha, seconds, move, w, h, fps, fade_out):
    """Identity of a deterministically rendered beat. ALLOW-LIST of causal inputs."""
    return input_hash(source_frame_sha=source_sha, seconds=round(float(seconds), 3),
                      move=move, w=w, h=h, fps=fps, fade_out=round(float(fade_out), 3),
                      renderer=BEAT_RENDERER_VERSION)


def render_beat(still, dest, seconds, move="HOLD", w=None, h=None, fps=24,
                fade_out=0.0):
    """Render a beat from ONE still, offline. Rs 0, and the room provably cannot move.

    This is the whole point of the hybrid grammar: a beat whose only visual change is the
    camera — or nothing at all — has no business being generated. Nothing is regenerating
    the room here, so the instability we measured in E01/s01 and s04 cannot occur. It is
    not a cheaper way to make the same thing; for these beats it is a BETTER way.

    HOLD is not a degenerate case of a move. It is the correct rendering of a beat where
    nothing changes, and it is the one thing a generative model cannot be asked for — a
    request to hold still is a request that has failed on this provider every time.
    """
    spec = (BIBLE.get("camera_moves") or {}).get(move)
    if spec is None:
        sys.exit(f"  '{move}' is not a camera move in the bible")
    from PIL import Image
    src_w, src_h = Image.open(still).size
    w, h = w or src_w, h or src_h
    seconds = round(float(seconds), 3)
    frames = max(2, int(round(seconds * fps)))
    kind, amount = spec.get("kind", "NONE"), float(spec.get("amount", 0.0))

    if kind == "ZOOM" and amount:
        # a pull-back starts wide and ends tight-free: begin zoomed IN and ease out, so the
        # frame never has to invent pixels outside the still
        start = 1.0 + max(0.0, -amount) / 100.0
        end = 1.0 + max(0.0, amount) / 100.0
        z = f"{start}+({end}-{start})*on/{frames - 1}"
        vf = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"d={frames}:s={w}x{h}:fps={fps}")
    elif kind in ("PAN_X", "PAN_Y") and amount:
        # a pan needs somewhere to pan TO, so hold a small zoom throughout and move the
        # window inside it. Panning a 1:1 image would slide black in from the edge.
        pad = 1.0 + abs(amount) / 100.0 + 0.02
        travel = amount / 100.0
        if kind == "PAN_X":
            x = f"(iw/zoom-iw/zoom/{pad})/2+({travel})*iw/zoom*on/{frames - 1}"
            y = "ih/2-(ih/zoom/2)"
        else:
            x = "iw/2-(iw/zoom/2)"
            y = f"(ih/zoom-ih/zoom/{pad})/2+({travel})*ih/zoom*on/{frames - 1}"
        vf = (f"zoompan=z='{pad}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}")
    else:
        vf = f"scale={w}:{h},loop=loop={frames}:size=1:start=0,fps={fps}"

    if fade_out and fade_out > 0:
        vf += f",fade=t=out:st={max(0.0, seconds - fade_out)}:d={fade_out}"
    rc = os.system(f'ffmpeg -nostdin -y -loop 1 -i "{still}" -vf "{vf}" -t {seconds} '
                   f'-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -an '
                   f'-r {fps} "{dest}" 2>/dev/null')
    return rc == 0 and Path(dest).exists()


def ending_identity(source_sha, w, h, fps):
    """Identity of the closing hold as a DERIVED artifact. Allow-list, as always."""
    return input_hash(source_frame_sha=source_sha, seconds=C.ENDING_HOLD_SECONDS,
                      push=C.ENDING_PUSH_PERCENT, fade=C.ENDING_FADE_SECONDS,
                      w=w, h=h, fps=fps, builder=ENDING_BUILDER_VERSION)


ENDING_BUILDER_VERSION = "1"


def stage_ending(eid):
    """A closing hold built from pixels the audience has already accepted. Rs 0.

    An episode that stops dead on its last generated frame ends; it does not CLOSE. The
    cheapest honest ending is the last accepted image held, pushed into very slowly, and
    faded to black while the bed resolves underneath.

    This is not a substitute for a designed closing shot. It is what a designed closing
    shot must beat before it is worth Rs 37, and it costs nothing to find out.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    accepted = [s["id"] for s in shots if clip_verdict(d, s["id"]) == "ACCEPTED"]
    if not accepted:
        sys.exit(f"  {eid}: nothing accepted to close on")
    last = accepted[-1]
    tail = d / "transitions" / f"{last}_LAST.png"
    src_clip = d / "clips" / f"{last}.mp4"
    ok, why = usable(tail, d / "transitions" / f"{last}_LAST.provenance.json",
                     input_hash(source_clip_sha=sha_file(src_clip) if src_clip.exists()
                                else None, extractor="ffmpeg-sseof-0.1-v1"))
    if not ok:
        sys.exit(f"  {eid}: the last accepted frame of {last} is not provably current "
                 f"({why}). A closing image must come from footage, not from a stray PNG.")

    w, h, fps = video_geometry(src_clip)
    secs = float(C.ENDING_HOLD_SECONDS)
    frames = max(2, int(round(secs * fps)))
    ident = ending_identity(sha_file(tail), w, h, fps)
    dest = d / "ending" / "hold.mp4"
    prov = d / "ending" / "hold.provenance.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    good, _why = usable(dest, prov, ident)
    if good:
        print(f"  {eid}: closing hold already current ({secs}s from {last})")
        return
    z = f"1+({C.ENDING_PUSH_PERCENT}/100)*on/{frames - 1}"
    vf = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
          f"d={frames}:s={w}x{h}:fps={fps},"
          f"fade=t=out:st={max(0.0, secs - C.ENDING_FADE_SECONDS)}:"
          f"d={C.ENDING_FADE_SECONDS}")
    rc = os.system(f'ffmpeg -nostdin -y -loop 1 -i "{tail}" -vf "{vf}" -t {secs} '
                   f'-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -an '
                   f'-r {fps} "{dest}" 2>/dev/null')
    if rc != 0 or not dest.exists():
        sys.exit("  ffmpeg could not build the closing hold")
    prov.write_text(json.dumps(
        {"status": "COMPLETE", "kind": "EPISODE_ENDING_HOLD", "episode": eid,
         "source_shot": last, "source_frame_sha": sha_file(tail),
         "origin": "DERIVED_FROM_ACCEPTED_FRAME", "seconds": secs,
         "push_percent": C.ENDING_PUSH_PERCENT, "fade_seconds": C.ENDING_FADE_SECONDS,
         "geometry": {"w": w, "h": h, "fps": fps},
         "input_hash": ident, "sha": sha_file(dest), "cost_inr": 0,
         "builder": ENDING_BUILDER_VERSION, "revision": build_revision()}, indent=2))
    print(f"  {eid}: {secs}s closing hold from {last}'s accepted last frame, "
          f"pushing in {C.ENDING_PUSH_PERCENT}% and fading to black")
    print(f"    -> {dest}")


def provable_ending(eid):
    """The closing hold, only if it is provably built from the CURRENT last accepted
    frame. A stale hold showing a shot that has since been superseded must not be silently
    concatenated onto the episode."""
    d = ep_dir(eid)
    dest, prov = d / "ending" / "hold.mp4", d / "ending" / "hold.provenance.json"
    if not (dest.exists() and prov.exists()):
        return None
    try:
        pv = json.loads(prov.read_text())
    except Exception:
        return None
    src_clip = d / "clips" / f"{pv.get('source_shot')}.mp4"
    tail = d / "transitions" / f"{pv.get('source_shot')}_LAST.png"
    if not (src_clip.exists() and tail.exists()):
        return None
    if clip_verdict(d, pv.get("source_shot")) != "ACCEPTED":
        return None
    g = pv.get("geometry") or {}
    ok, _why = usable(dest, prov, ending_identity(sha_file(tail), g.get("w"), g.get("h"),
                                                  g.get("fps")))
    return dest if ok else None


# ──────────────────────────────── audio ──────────────────────────────
def media_duration(path):
    """PURE-ish. Seconds of the longest stream, or None. Reads, never writes."""
    out = os.popen(f'ffprobe -v error -show_entries format=duration -of '
                   f'csv=p=0 "{path}" 2>/dev/null').read().strip()
    try:
        return round(float(out), 3)
    except ValueError:
        return None


def stream_duration(path, kind):
    """Seconds of the first stream of `kind` ('a' or 'v'), or None if there is none."""
    out = os.popen(f'ffprobe -v error -select_streams {kind}:0 -show_entries '
                   f'stream=duration -of csv=p=0 "{path}" 2>/dev/null').read().strip()
    try:
        return round(float(out.split(",")[0]), 3)
    except (ValueError, IndexError):
        return None


def measure_loudness(path):
    """Integrated loudness in LUFS, measured by ffmpeg's EBU R128 meter, or None.

    Measurement, not opinion: the same number a broadcaster or YouTube would compute.
    """
    if not Path(path).exists():
        return None
    out = os.popen(f'ffmpeg -nostdin -i "{path}" -af ebur128=framelog=quiet -f null - '
                   f'2>&1 | grep -A1 "Integrated loudness"').read()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            try:
                return round(float(line.split()[1]), 1)
            except (ValueError, IndexError):
                return None
    return None


NOTE_SEMITONES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
                  "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def note_hz(note):
    """PURE. 'A4' -> 440.0. One definition; the bible writes notes, never frequencies."""
    name, octave = note[:-1].upper(), note[-1]
    if name not in NOTE_SEMITONES or not octave.isdigit():
        sys.exit(f"  '{note}' is not a note name like C3 or F#4")
    midi = NOTE_SEMITONES[name] + (int(octave) + 1) * 12
    return round(440.0 * (2 ** ((midi - 69) / 12)), 4)


def synth_bed(mode, seconds, dest):
    """Compose the episode's bed OFFLINE from the mode's chord. Free. Original.

    Deliberately ours rather than licensed: a channel whose entire defence is that it is
    original work should not stake its monetisation on someone else's track, and the free
    music libraries are exactly where a copyright claim comes from six months later.

    It is a held chord with one very slow swell, plus a faint breath of air so the bed is
    not a dead sine tone. Not a score — a bed. Narration and picture carry the episode.
    """
    spec = (BIBLE.get("audio_bed") or {}).get(mode)
    if not spec:
        sys.exit(f"  mode {mode} has no audio_bed in the bible")
    seconds = round(float(seconds), 3)
    swell = float(spec.get("swell_seconds", 8))
    tone = float(spec.get("tone_gain", 0.12)) / max(1, len(spec["chord"]))
    voices, mixes = [], []
    for i, note in enumerate(spec["chord"]):
        hz = note_hz(note)
        # each voice breathes on its own slightly detuned cycle, so the chord shimmers
        # instead of beating in lockstep
        period = swell + i * 1.7
        voices.append(f'sine=frequency={hz}:duration={seconds}:sample_rate=48000')
        mixes.append(f'[{i}:a]volume={tone},'
                     f'volume=\'0.55+0.45*sin(2*PI*t/{period:.3f})\':eval=frame[v{i}]')
    air = float(spec.get("air_gain", 0.01))
    voices.append(f'anoisesrc=d={seconds}:c=pink:r=48000:a={air}')
    n = len(spec["chord"])
    mixes.append(f'[{n}:a]lowpass=f=900[air]')
    names = "".join(f"[v{i}]" for i in range(n)) + "[air]"
    chain = (";".join(mixes) + f';{names}amix=inputs={n + 1}:normalize=0,'
             f'lowpass=f=2600,aformat=sample_fmts=s16:sample_rates=48000:'
             f'channel_layouts=stereo[out]')
    inputs = " ".join(f'-f lavfi -i "{v}"' for v in voices)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rc = os.system(f'ffmpeg -nostdin -y {inputs} -filter_complex "{chain}" '
                   f'-map "[out]" "{dest}" 2>/dev/null')
    if rc != 0 or not dest.exists():
        sys.exit("  ffmpeg could not compose the bed")
    return spec


def stage_bed(eid):
    """Compose this episode's bed to fit its assembled picture exactly. Rs 0."""
    d = ep_dir(eid)
    final = d / "episode.mp4"
    if not final.exists():
        sys.exit(f"  no assembled picture at {final} — assemble first, then compose to it")
    mode = load_ep(eid)["mode"]
    seconds = stream_duration(final, "v") or media_duration(final)
    dest = episode_audio_dir(eid) / "bed.wav"
    spec = synth_bed(mode, seconds, dest)
    (episode_audio_dir(eid) / "bed.provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "kind": "EPISODE_AUDIO_BED", "episode": eid, "mode": mode,
         "seconds": seconds, "spec": spec, "origin": "COMPOSED_OFFLINE",
         "licence": "ORIGINAL — composed by this pipeline, no third-party rights",
         "sha": sha_file(dest), "cost_inr": 0,
         "compiler": BED_COMPILER_VERSION, "revision": build_revision()}, indent=2))
    print(f"  {eid}: composed a {seconds}s {mode} bed  ({spec['character']})")
    print(f"    -> {dest}")
    print(f"    now: python3 make.py assemble {eid} && python3 make.py audio {eid}")


STAR_OVERLAY_VERSION = "1"


def draw_counted_stars(src, dest, count, box, seed_positions=None, size=None):
    """Draw EXACTLY `count` stars into a declared box. Free, exact, repeatable.

    A counting song lives or dies on the count being right, and asking a generator for
    exactly five of something is the one instruction this project has never even tried —
    though Pavan's other repo already carries a FINAL COUNT AUDIT clause begging a model to
    render three ducks and never four, which tells you how that goes.

    So the count is not requested. It is DRAWN. The generated still supplies a night sky;
    arithmetic supplies the five stars, then four, then three. The child can count them
    because they are countable, and the same five sit in the same places every time.
    """
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGBA")
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    size = size or max(5, int(min(w, h) * 0.055))
    # fixed, hand-placed positions inside the box, as fractions. Stars disappear from the
    # END of the list, so the ones that remain never move — a star that jumps when its
    # neighbour vanishes is a star the child cannot keep counting.
    # placed inside the PANES, never on the glazing bars. A star sitting on the wooden
    # cross reads as a decoration stuck to the window rather than a star in the sky, and
    # the child is being asked to count the sky.
    spots = seed_positions or [(0.26, 0.26), (0.71, 0.24), (0.25, 0.69),
                               (0.72, 0.70), (0.40, 0.13)]
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    import math
    for fx, fy in spots[:max(0, int(count))]:
        cx, cy = x0 + fx * w, y0 + fy * h
        r, rin = size, size * 0.40
        # glow FIRST, star on top of it. The other way round buries the shape under its
        # own halo, which is how the first attempt produced five soft discs and no stars.
        for k, a in ((2.2, 26), (1.4, 46)):
            d.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k],
                      fill=(255, 246, 200, a))
        pts = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else rin
            pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
        d.polygon(pts, fill=(255, 252, 232, 255))
    out = Image.alpha_composite(im, layer).convert("RGB")
    out.save(dest)
    return dest


MOTION_RENDERER_VERSION = "1"


def render_motion_beat(still, dest, seconds, move="HOLD", fps=24, w=None, h=None,
                       stars=None, star_box=None, twinkle=True, light=True,
                       fade_out=0.0, phase=0.0):
    """A beat that MOVES, without a generator and without a slideshow. Rs 0.

    A held photograph with a slow zoom on it is a slideshow wearing a camera-effect
    costume, and Pavan is right to reject it. What makes a night scene read as FILM rather
    than a picture is that things inside the frame are alive: the stars breathe, the lamp
    light shifts, and the camera moves through the room rather than across a flat plane.

    All three are arithmetic:
      - every star twinkles on its own phase, so the sky is never still and never uniform
      - the lamp light rises and falls a few percent, the way a real warm bulb does
      - the camera zoom and pan are computed PER FRAME, so they compose with the above
        rather than being an ffmpeg filter bolted on afterwards

    None of it can drift, deform the room, invent a lantern, or push in without being asked,
    because nothing is regenerating anything. It is the same picture, alive.
    """
    from PIL import Image, ImageDraw, ImageEnhance
    import math, tempfile, shutil as _sh
    spec = (BIBLE.get("camera_moves") or {}).get(move) or {"kind": "NONE", "amount": 0.0}
    kind, amount = spec.get("kind", "NONE"), float(spec.get("amount", 0.0))
    base = Image.open(still).convert("RGB")
    W, H = base.size
    w, h = w or W, h or H
    n = max(2, int(round(seconds * fps)))
    tmp = Path(tempfile.mkdtemp())
    spots = [(0.26, 0.26), (0.71, 0.24), (0.25, 0.69), (0.72, 0.70), (0.40, 0.13)]
    try:
        for i in range(n):
            u = i / (n - 1)
            frame = base.copy()
            if stars and star_box:
                x0, y0, x1, y1 = star_box
                bw, bh = x1 - x0, y1 - y0
                size = max(5, int(min(bw, bh) * 0.055))
                layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                d = ImageDraw.Draw(layer)
                for si, (fx, fy) in enumerate(spots[:int(stars)]):
                    # each star on its own period and phase: a sky where everything
                    # twinkles together is a strobe, not a night
                    tw = (0.78 + 0.22 * math.sin(2 * math.pi *
                          (u * seconds / (2.6 + si * 0.7) + phase + si * 0.37))
                          if twinkle else 1.0)
                    cx, cy = x0 + fx * bw, y0 + fy * bh
                    r = size * tw
                    for k, a in ((2.4, int(22 * tw)), (1.5, int(44 * tw))):
                        d.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k],
                                  fill=(255, 246, 200, max(0, a)))
                    pts = []
                    for j in range(10):
                        ang = math.pi / 2 + j * math.pi / 5
                        rad = r if j % 2 == 0 else r * 0.40
                        pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
                    d.polygon(pts, fill=(255, 252, 232, 255))
                frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
            if light:
                # a warm bulb is never perfectly steady. Three percent, slowly.
                lp = 1.0 + 0.03 * math.sin(2 * math.pi * (u * seconds / 7.0 + phase))
                frame = ImageEnhance.Brightness(frame).enhance(lp)
            # camera, computed per frame so it composes with everything above
            if kind == "ZOOM" and amount:
                z0 = 1.0 + max(0.0, -amount) / 100.0
                z1 = 1.0 + max(0.0, amount) / 100.0
                z = z0 + (z1 - z0) * u
                cxf, cyf = 0.5, 0.5
            elif kind in ("PAN_X", "PAN_Y") and amount:
                z = 1.0 + abs(amount) / 100.0 + 0.02
                travel = (amount / 100.0) * (u - 0.5)
                cxf = 0.5 + (travel if kind == "PAN_X" else 0.0)
                cyf = 0.5 + (travel if kind == "PAN_Y" else 0.0)
            else:
                z, cxf, cyf = 1.0, 0.5, 0.5
            cw, ch = W / z, H / z
            cx = min(max(cxf * W, cw / 2), W - cw / 2)
            cy = min(max(cyf * H, ch / 2), H - ch / 2)
            frame = frame.crop((int(cx - cw / 2), int(cy - ch / 2),
                                int(cx + cw / 2), int(cy + ch / 2))).resize((w, h),
                                                                           Image.LANCZOS)
            frame.save(tmp / f"{i:05d}.png")
        vf = (f"fade=t=out:st={max(0.0, seconds - fade_out)}:d={fade_out}"
              if fade_out and fade_out > 0 else "null")
        rc = os.system(f'ffmpeg -nostdin -y -framerate {fps} -i "{tmp}/%05d.png" '
                       f'-vf "{vf}" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p '
                       f'-an "{dest}" 2>/dev/null')
        return rc == 0 and Path(dest).exists()
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


ANIMATIC_VERSION = "1"


def load_beats(eid):
    """The episode's beat map: which visual authority covers which phrases, and how."""
    p = ep_dir(eid) / "beats.json"
    if not p.exists():
        sys.exit(f"  no beat map at {p} — write one against phrases.json first")
    return json.loads(p.read_text())


def beat_segments(eid):
    """PURE-ish. Turn the beat map + phrase timings into concrete (start, end, spec) cuts.

    The song decides where cuts fall. A beat names the PHRASE it starts on; its length is
    whatever the music gives it, never a number somebody typed.
    """
    d = ep_dir(eid)
    pm = json.loads((d / "phrases.json").read_text())
    runtime = pm["trimmed"]["runtime_seconds"]
    at = {i: p["at"] for i, p in enumerate(pm["phrases"])}
    beats = load_beats(eid)["beats"]
    segs = []
    for i, b in enumerate(beats):
        b.setdefault("source", {"kind": "STILL", "id": i})
        # a beat lands on a PHRASE, or — when the picture must count along with the voice —
        # on a WORD. "Four little stars, then three, then two" is one phrase and three
        # numbers, and a star vanishing 0.7s after the last one is not a cut, it is the
        # room agreeing with the song.
        def _time_of(beat):
            return beat["at"] if "at" in beat else at.get(beat.get("from_phrase"))
        start = _time_of(b)
        if start is None:
            sys.exit(f"  beat {i} names phrase {b.get('from_phrase')}, which does not exist")
        if i == 0:
            # picture must cover the instrumental pickup too. The first beat starts when
            # the TRACK starts, not when the first word does, or the episode opens on
            # black for two and a half seconds.
            start = 0.0
        end = _time_of(beats[i + 1]) if i + 1 < len(beats) else runtime
        if end is None:
            sys.exit(f"  beat {i + 1} has no phrase or time")
        segs.append({**b, "start": round(start, 2), "end": round(end, 2),
                     "seconds": round(end - start, 2)})
    return segs, runtime


def stage_beats(eid):
    """Print the beat map against the song, so a human can see the pacing before buying."""
    segs, runtime = beat_segments(eid)
    pm = json.loads((ep_dir(eid) / "phrases.json").read_text())["phrases"]
    print(f"  {eid}: {len(segs)} visual authorities across {runtime}s")
    paid = 0
    for s in segs:
        renderer, cost, _why = renderer_for(s["visual_change"])
        if s["source"]["kind"] == "GENERATIVE":
            renderer, cost = "GENERATIVE_VIDEO", "PAID"
        if cost == "PAID":
            paid += 1
        tag = {"STILL": f"still {s['source'].get('id')}", "GENERATIVE": "GENERATED",
               "TAIL_OF": f"tail of beat {s['source'].get('beat')}"}[s["source"]["kind"]]
        print(f"    {s['start']:6.2f}-{s['end']:6.2f} ({s['seconds']:5.2f}s) "
              f"{s['move']:11s} {tag:16s} {s['state'][:34]}")
        for p in pm[s.get("from_phrase", len(pm)):]:
            if p["at"] >= s["end"]:
                break
            if not p["text"].startswith("["):
                print(f"                    | {p['at']:6.2f}  {p['text'][:56]}")
    stills = {b["source"]["id"] for b in segs if b["source"]["kind"] == "STILL"}
    gens = [b for b in segs if b["source"]["kind"] == "GENERATIVE"]
    over = [b for b in gens if b["seconds"] > C.VIDEO_SECONDS + 0.05]
    cost = len(stills) * C.INR_PER_IMAGE + len(gens) * (C.INR_PER_IMAGE +
                                                        C.VIDEO_SECONDS * C.INR_PER_VID_SEC)
    print(f"  {len(stills)} paid stills + {len(gens)} generated beat(s) = "
          f"Rs {cost:.2f}, worst case Rs {cost * getattr(C, 'SAFETY_MARGIN', 1.0):.2f}")
    for b in over:
        print(f"  x a generated beat covers {b['seconds']}s but a clip lasts "
              f"{C.VIDEO_SECONDS}s. Cover the rest with TAIL_OF, or the picture freezes "
              f"on a paid frame nobody chose.")


def stage_animatic(eid):
    """Watch the whole episode BEFORE buying a single picture. Rs 0.

    GPT's gate, and it is the best idea either of us has had today: build the real
    structure — real song, real cut points, real holds and moves — with placeholder
    pictures. If it is boring with placeholders, Rs 5 images will not fix the pacing; if it
    already feels musical, the structure has earned the money.
    """
    d = ep_dir(eid)
    segs, runtime = beat_segments(eid)
    bed = episode_audio_dir(eid) / "bed.wav"
    if not bed.exists():
        sys.exit(f"  no trimmed track at {bed} — run `track` first")
    stand_in = d / "animatic" / "stills"
    stand_in.mkdir(parents=True, exist_ok=True)
    pool = sorted((OUT / "E01" / "frames").glob("*.png")) + \
           sorted((OUT / "E01" / "transitions").glob("*_LAST.png"))
    if not pool:
        sys.exit("  no placeholder stills available")
    parts = []
    for i, s in enumerate(segs):
        src = pool[i % len(pool)]
        seg = d / "animatic" / f"{i:02d}.mp4"
        ok = render_beat(src, seg, s["seconds"], s.get("move", "HOLD"), 1280, 720, 24,
                         fade_out=(C.ENDING_FADE_SECONDS if i == len(segs) - 1 else 0.0))
        if not ok:
            sys.exit(f"  could not render animatic segment {i}")
        parts.append(seg)
    lst = d / "animatic" / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    silent = d / "animatic" / "picture.mp4"
    os.system(f'ffmpeg -nostdin -y -f concat -safe 0 -i "{lst}" -c copy "{silent}" '
              f'2>/dev/null')
    final = d / "animatic" / "animatic.mp4"
    os.system(f'ffmpeg -nostdin -y -i "{silent}" -i "{bed}" -map 0:v -map 1:a '
              f'-c:v copy -c:a aac -b:a 192k -shortest "{final}" 2>/dev/null')
    print(f"  {eid}: animatic built from PLACEHOLDER pictures and the real song")
    print(f"    {len(segs)} beats, {media_duration(final)}s, Rs 0")
    print(f"    -> {final}")
    print("  Watch the whole thing. If the pacing is boring here, paid stills will not "
          "fix it.")


TRACK_TRIM_VERSION = "1"


def read_lrc(path):
    """PURE. LRC -> [(seconds, text)] for LINES, dropping the per-word stamps.

    Suno stamps every word. Cuts belong on PHRASES, not words: a cut mid-phrase reads as a
    mistake even when it lands exactly on a beat.
    """
    import re
    out, current, start = [], [], None
    for raw in Path(path).read_text().splitlines():
        m = re.match(r"\[(\d+):([\d.]+)\]\s*(.*)", raw)
        if not m:
            if raw.strip() == "" and current:
                out.append((start, " ".join(current).strip())); current, start = [], None
            elif raw.strip():
                current.append(raw.strip())
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        text = m.group(3).strip()
        if text.startswith("["):          # a section label, its own boundary
            if current:
                out.append((start, " ".join(current).strip())); current = []
            out.append((t, text))
            # the first sung word of the next line sits UNSTAMPED under the label. Dropping
            # it loses the word the phrase begins with — "Five" from "Five little stars" —
            # and puts every opening cut half a second late.
            start = t
            continue
        if start is None:
            start = t
        current.append(text)
    if current:
        out.append((start, " ".join(current).strip()))
    return [(round(t, 2), x) for t, x in out if t is not None and x]


def trailing_silence(path, floor_db=-45, min_seconds=0.4):
    """Where the music actually stops. MEASURED, not guessed at with a round number."""
    out = os.popen(f'ffmpeg -nostdin -i "{path}" -af '
                   f'silencedetect=noise={floor_db}dB:d={min_seconds} -f null - 2>&1 '
                   f'| grep silence_start').read().strip().splitlines()
    if not out:
        return None
    try:
        return round(float(out[-1].split("silence_start:")[1].strip()), 3)
    except (IndexError, ValueError):
        return None


def stage_track(eid, clip_id=None, lead_in=2.5):
    """Choose the take, trim the dead air deterministically, make it the audio spine. Rs 0.

    Both takes opened with a fourteen-second instrumental intro while "long intro" sat in
    the exclude list that was sent. That is the seventh prose instruction a generator has
    ignored on this project, and the answer is the same as it was for the unrequested camera
    push-in: do not ask again, measure it and remove it.

    Head is cut to `lead_in` seconds before the first sung word — enough to establish the
    room before anyone sings, not enough for a preschooler to leave. Tail is cut where the
    music MEASURABLY stops rather than at a round number.
    """
    d = ep_dir(eid)
    suno = d / "suno"
    lrcs = sorted(suno.glob("*.lrc"))
    if not lrcs:
        sys.exit(f"  no timings in {suno} — pull them with the Suno CLI first")
    if clip_id:
        lrcs = [p for p in lrcs if p.stem.startswith(clip_id)]
        if not lrcs:
            sys.exit(f"  no timings for clip {clip_id}")
    lrc = lrcs[0]
    cid = lrc.stem
    audio = next((p for p in sorted((suno / "audio").glob("*.mp3"))
                  if cid[:8] in p.name), None)
    if not audio:
        sys.exit(f"  no audio file for clip {cid}")

    lines = read_lrc(lrc)
    sung = [(t, x) for t, x in lines if not x.startswith("[")]
    if not sung:
        sys.exit("  the timings contain no sung lines")
    first, last = sung[0][0], sung[-1][0]
    total = media_duration(audio)
    stop = trailing_silence(audio) or total
    head = max(0.0, round(first - lead_in, 3))
    tail = round(min(stop + 0.4, total), 3)
    dur = round(tail - head, 3)

    dest = episode_audio_dir(eid) / "bed.wav"
    fade = min(C.AUDIO_FADE_SECONDS, dur / 6)
    rc = os.system(f'ffmpeg -nostdin -y -ss {head} -to {tail} -i "{audio}" '
                   f'-af "afade=t=out:st={round(dur - fade, 3)}:d={fade}" '
                   f'-ar 48000 -ac 2 "{dest}" 2>/dev/null')
    if rc != 0 or not dest.exists():
        sys.exit("  ffmpeg could not trim the track")
    phrases = [{"at": round(t - head, 2), "text": x} for t, x in lines
               if t >= head and t <= tail]
    (d / "phrases.json").write_text(json.dumps(
        {"kind": "SONG_PHRASE_MAP", "episode": eid, "clip_id": cid,
         "source_audio": audio.name, "source_seconds": total,
         "trimmed": {"head_seconds": head, "tail_seconds": round(total - tail, 3),
                     "runtime_seconds": dur, "lead_in": lead_in,
                     "first_word_at": round(first - head, 2),
                     "music_stops_at": stop},
         "phrases": phrases, "trimmer": TRACK_TRIM_VERSION,
         "revision": build_revision()}, indent=2))
    (episode_audio_dir(eid) / "bed.provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "kind": "EPISODE_AUDIO_BED", "episode": eid,
         "origin": "SUNO_TRACK_TRIMMED", "clip_id": cid, "source_audio": audio.name,
         "head_seconds": head, "runtime_seconds": dur,
         "licence": "Suno Pro Plan — commercial_rights present on the account at generation",
         "sha": sha_file(dest), "cost_inr": 0, "trimmer": TRACK_TRIM_VERSION,
         "revision": build_revision()}, indent=2))
    print(f"  {eid}: take {cid[:8]} — {total}s in, {dur}s out")
    print(f"    cut {head}s of intro (first word now at {round(first - head, 2)}s) "
          f"and {round(total - tail, 2)}s of tail")
    print(f"    {len([p for p in phrases if not p['text'].startswith('[')])} sung phrases, "
          f"{len([p for p in phrases if p['text'].startswith('[')])} section marks")
    print(f"    -> {dest}")
    print(f"    -> {d / 'phrases.json'}")


SONG_REQUEST_VERSION = "1"


def stage_song(eid):
    """Prepare a Suno request for this episode. FREE — it writes, it does not generate.

    Deliberately the same split as everywhere else in this pipeline: preparation is free and
    reviewable, spending is a separate, explicit act. The request and the lyrics land on disk
    where a human can read them before a single credit moves.

    Generation is NOT run from here, and that is not an oversight. It spends Pavan's Suno
    credits under a licence whose terms depend on his subscription tier, and free-tier output
    is not licensed for commercial use. A pipeline that generates a track for a monetised
    channel without knowing the tier would be making a worse mistake than any pixel we have
    argued about.
    """
    ep = load_ep(eid)
    song = ep.get("song") or {}
    if not song.get("lyrics"):
        sys.exit(f"  {eid} has no song.lyrics — this stage prepares a SONG episode")
    lyrics = song["lyrics"].strip()
    if not lyrics.lstrip().startswith("["):
        sys.exit("  lyrics must use explicit section labels such as [Verse 1] and [Chorus]")
    bpm = int(song.get("bpm", 72))
    d = ep_dir(eid) / "suno"
    d.mkdir(parents=True, exist_ok=True)

    # Tag vocabulary follows the implementation already proven in Pavan's enterprise-ai-yt
    # repo rather than being reinvented here. Two copies of a house voice drift apart.
    tags = ", ".join(filter(None, [
        f"original preschool song at {bpm} BPM in a bright major key",
        "warm natural adult female lead vocal",
        "clear English diction, stable pitch, minimal vibrato",
        "friendly moderate phrase speed, easy for ages two to six to imitate",
        (song.get("direction") or "").strip().replace("\n", " "),
    ]))[:1000]
    request = {
        "provider": "paperfoot/suno-cli", "model": "v5.5",
        "title": ep["title"][:100], "vocal": "female",
        "tags": tags,
        "exclude": ", ".join(["spoken narration", "child choir", "wide vibrato", "belting",
                              "shouting", "spooky", "eerie", "robotic", "strained",
                              "distorted vocals", "rap", "heavy drums", "long intro",
                              "long outro"]),
        "weirdness": 20, "styleInfluence": 80, "captcha": "disabled",
        "compiler": SONG_REQUEST_VERSION,
    }
    (d / "lyrics.txt").write_text(lyrics + "\n")
    (d / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    (d / "GATE.md").write_text(
        f"# {eid} — before a single Suno credit moves\n\n"
        "1. CONFIRM THE SUBSCRIPTION TIER. Free-tier Suno output is not licensed for\n"
        "   commercial use. This episode is intended for a monetised channel. If the tier\n"
        "   is not one that grants commercial rights, STOP — nothing else here matters.\n"
        "2. Read lyrics.txt as a parent, not as an engineer. It is original work and it is\n"
        "   the first thing anyone will hear from this channel.\n"
        "3. Generate with the CLI from the enterprise-ai-yt implementation, CAPTCHA\n"
        "   automation disabled, and pull the word timings — the timings are the point.\n"
        "   The picture is cut to the song, not the other way around.\n"
        "4. Bring the track back and run `make.py beatmap " + eid + "`.\n\n"
        "No Gemini image or video call is authorised before the timings exist. Beats are\n"
        "chosen by where the phrases fall, and buying pictures first would mean buying\n"
        "pictures for cuts nobody has heard yet.\n")
    print(f"  {eid}: prepared a Suno request. NOTHING generated, no credits spent.")
    print(f"    lyrics   {d / 'lyrics.txt'}")
    print(f"    request  {d / 'request.json'}")
    print(f"    gate     {d / 'GATE.md'}   <- the licence question is in here")


BED_COMPILER_VERSION = "1"


def episode_audio_dir(eid):
    d = ep_dir(eid) / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_spine_sources(eid):
    """The episode's AUTHORED audio, in mix order. Absent files are simply absent.

    bed  a single continuous track spanning the whole programme — music or room tone
    vo   narration, laid over the bed

    Deliberately files on disk rather than a generated stage: the bed may be composed,
    licensed, or synthesised, and the mixer should not care which. What it must never be
    is per-clip provider output, which is the defect this whole path exists to remove.
    """
    a = episode_audio_dir(eid)
    return {k: p for k, p in (("bed", a / "bed.wav"), ("vo", a / "vo.wav"))
            if p.exists()}


def mix_audio_spine(eid, picture, dest):
    """Lay the authored spine under FINISHED PICTURE. Free, deterministic, no provider.

    One bed across the whole programme cannot have a seam at a cut, because it does not
    know a cut happened. That is the entire argument for authoring audio at episode level
    instead of accepting whatever each 4-second generation invented for itself.

    Returns (ok, why). A missing bed is not an error — it is an episode that has picture
    and no soundtrack yet, and it must still assemble and be watchable.
    """
    src = audio_spine_sources(eid)
    if "bed" not in src:
        return False, "no audio/bed.wav — picture assembled without a spine"
    picture_secs = media_duration(picture)
    if not picture_secs:
        return False, "could not measure the assembled picture"
    fade = min(C.AUDIO_FADE_SECONDS, picture_secs / 4)
    bed_chain = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{picture_secs},"
                 f"afade=t=in:st=0:d={fade},"
                 f"afade=t=out:st={max(0.0, picture_secs - fade)}:d={fade}[bed]")
    if "vo" in src:
        chain = (f"{bed_chain};[2:a]atrim=0:{picture_secs}[vo];"
                 f"[bed][vo]amix=inputs=2:duration=first:dropout_transition=0,"
                 f"loudnorm=I={C.PROGRAMME_LUFS}:TP={C.PROGRAMME_TRUE_PEAK}[a]")
        inputs = f'-i "{picture}" -i "{src["bed"]}" -i "{src["vo"]}"'
    else:
        chain = f'{bed_chain};[bed]loudnorm=I={C.PROGRAMME_LUFS}:TP={C.PROGRAMME_TRUE_PEAK}[a]'
        inputs = f'-i "{picture}" -i "{src["bed"]}"'
    tmp = Path(str(dest) + ".mixing.mp4")
    rc = os.system(f'ffmpeg -nostdin -y {inputs} -filter_complex "{chain}" '
                   f'-map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest '
                   f'"{tmp}" 2>/dev/null')
    if rc != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False, "ffmpeg could not lay the audio spine"
    tmp.replace(dest)

    # loudnorm in one pass lands close, not exact. Measure what we actually produced and
    # apply a single corrective gain — deterministic, bounded to one correction, and it
    # makes the delivered number match the target instead of merely approaching it.
    got = measure_loudness(dest)
    if got is not None:
        delta = round(C.PROGRAMME_LUFS - got, 2)
        if abs(delta) > 0.3:
            fix = Path(str(dest) + ".gain.mp4")
            rc = os.system(f'ffmpeg -nostdin -y -i "{dest}" -af "volume={delta}dB" '
                           f'-c:v copy -c:a aac -b:a 192k "{fix}" 2>/dev/null')
            if rc == 0 and fix.exists():
                fix.replace(dest)
                got = measure_loudness(dest)
            else:
                fix.unlink(missing_ok=True)
    return True, (f"bed{' + vo' if 'vo' in src else ''} laid across {picture_secs}s "
                  f"at {got} LUFS")


def stage_audio(eid):
    """Judge what the audience will HEAR. Free — measurement, not generation.

    Splits two questions that were never asked at all before E01 was called
    publish-quality: what the DELIVERED programme sounds like, which blocks, and what the
    PROVIDER invented per clip, which is an observation about a generator and blocks
    nothing because we throw it away.
    """
    d = ep_dir(eid)
    final = d / "episode.mp4"
    if not final.exists():
        sys.exit(f"  no assembled episode at {final} — run assemble first")
    shots = json.loads((d / "shots.json").read_text())
    native = {}
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        if c.exists() and clip_verdict(d, s["id"]) == "ACCEPTED":
            native[s["id"]] = measure_loudness(c)
    observation = qc.native_loudness_spread(native)

    picture = stream_duration(final, "v") or media_duration(final)
    audio_secs = stream_duration(final, "a")
    delivered = measure_loudness(final) if audio_secs else None
    has_spine = bool(audio_spine_sources(eid))

    probes, detail = {}, {}
    probes["PROGRAMME_LOUDNESS"], detail["PROGRAMME_LOUDNESS"] = qc.programme_loudness(
        delivered, C.PROGRAMME_LUFS, C.PROGRAMME_LUFS_TOLERANCE)
    probes["AUDIO_SPANS_PICTURE"], detail["AUDIO_SPANS_PICTURE"] = qc.audio_spans_picture(
        audio_secs, picture)
    # provider audio is stripped at assemble; if a track survived without an authored
    # spine, the strip did not happen and the audience is hearing the generator
    if audio_secs and not has_spine:
        probes["NO_PROVIDER_AUDIO"] = "FAIL"
        detail["NO_PROVIDER_AUDIO"] = ("the delivered episode carries audio that no "
                                       "authored spine can account for")
    else:
        probes["NO_PROVIDER_AUDIO"] = "PASS"
        detail["NO_PROVIDER_AUDIO"] = ("provider audio stripped at assemble"
                                       if C.STRIP_PROVIDER_AUDIO else "not stripped")
    probes["UNREQUESTED_SPEECH"] = "NOT_TESTED"
    detail["UNREQUESTED_SPEECH"] = "a human must listen; no automated judgement exists"

    rep = {"kind": "EPISODE_AUDIO", "episode": eid,
           "picture_seconds": picture, "audio_seconds": audio_secs,
           "delivered_lufs": delivered, "target_lufs": C.PROGRAMME_LUFS,
           "spine": sorted(audio_spine_sources(eid)),
           "probes": probes, "detail": detail,
           "provider_observation": observation,
           "revision": build_revision()}
    (d / "audio.json").write_text(json.dumps(rep, indent=2))

    print(f"  picture {picture}s   audio {audio_secs}s   delivered {delivered} LUFS "
          f"(target {C.PROGRAMME_LUFS})")
    for p in qc.AUDIO_PROBES:
        print(f"    {probes[p]:10s} {p:22s} {detail[p]}")
    if observation.get("observation") == "OBSERVED":
        print(f"  provider native audio, per clip: {observation['per_clip']}")
        print(f"    spread {observation['spread_lu']} LU — {observation['means']}")
    print(f"  -> {d / 'audio.json'}")


# ────────────────────────────── assemble ─────────────────────────────
def stage_assemble(eid):
    """Assemble the accepted PREFIX — everything approved so far, in order.

    Assembling a prefix rather than demanding a finished episode is what makes an episode
    watchable while it is still being built. It stops at the first shot that is not
    accepted and says so, so a partial cut is never mistaken for a finished one.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    clips, stopped = [], None
    for s in shots:
        c = d / "clips" / f"{s['id']}.mp4"
        # Call the REAL identity function. This duplicated the formula and would have
        # silently refused to assemble the moment the clip contract changed — the same
        # drift that has now bitten preflight, the frame path and two test fixtures.
        ok, why = usable(c, d / "clips" / f"{s['id']}.provenance.json",
                         clip_identity(s, d / "frames" / f"{s['id']}.png",
                                       load_ep(eid)["mode"])) if c.exists() else (False, "missing")
        if not ok:
            stopped = f"{s['id']} clip is not provably current ({why})"; break
        verdict = clip_verdict(d, s["id"])
        if verdict == "ACCEPTED":
            # a stabilised copy, when one provably came from this exact paid clip. The
            # paid file is untouched; only the file the master is cut from changes.
            fixed = provable_stabilized(eid, s["id"])
            if fixed:
                c = fixed
        if verdict != "ACCEPTED":
            stopped = (f"{s['id']} is {verdict}. QC failure is terminal — it never "
                       f"triggers regeneration.")
            break
        clips.append(c)
    # a closing hold, if one has been built and still belongs to the current last
    # accepted shot. Free, derived, and never a substitute for a shot that was paid for
    hold = provable_ending(eid) if clips else None
    if hold:
        clips.append(hold)
    if not clips:
        sys.exit(f"  nothing accepted to assemble in {d/'clips'}" +
                 (f"\n  first blocker: {stopped}" if stopped else ""))
    if stopped:
        print(f"  PARTIAL: assembling {len(clips)} of {len(shots)} shots")
        print(f"  stopped at {stopped}")
    final = d / "episode.mp4"
    x = C.CROSSFADE_SECONDS
    if len(clips) == 1 or x <= 0:
        lst = d / "concat.txt"
        lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
        # -an: the provider's per-clip audio is a generation by-product, never programme
        # audio. Three independently invented room tones measured 13.4 LU apart on this
        # very episode; a seam at every cut is not a soundtrack.
        strip = "-an" if C.STRIP_PROVIDER_AUDIO else ""
        rc = os.system(f'ffmpeg -y -f concat -safe 0 -i "{lst}" -c copy {strip} '
                       f'"{final}" 2>/dev/null')
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
    print(f"  -> {final}  ({len(clips)} segments"
          + (", including the free closing hold" if hold else "")
          + f", crossfade {x}s)")
    ok, why = mix_audio_spine(eid, final, final)
    print(f"  audio: {why}")
    if not ok:
        print("  the episode has PICTURE ONLY. Author out/%s/audio/bed.wav, then "
              "assemble again." % eid)


def stage_episode(eid, upto=None):
    """Interleaved shot-by-shot run over whatever is NOT already accepted.

    Predecessor-pixel inheritance only works if clip N exists before frame N+1 is
    resolved, so frames and clips must alternate rather than run as separate passes.
    Each shot: resolve its first frame (inherit free, or generate), then render it.

    Shots that are already ACCEPTED are skipped, not re-rendered. That is what makes
    extending an episode cost only the seconds that do not exist yet.

    `upto` caps how many NEW shots one run may generate. Spending is easier to authorise
    in bounded slices than as an open-ended "render the episode", and a run that stops
    early leaves a resumable episode rather than a half-charged mess.
    """
    d = ep_dir(eid)
    shots = json.loads((d / "shots.json").read_text())
    if report(validate(shots, load_ep(eid), BIBLE,
                       frozen=frozen_prefix(eid, shots))):
        sys.exit("  plan has continuity errors")

    done = frozen_prefix(eid, shots)
    if done:
        print(f"  {done} shot(s) already accepted — skipping, not re-rendering")
    todo = shots[done:]
    if upto is not None:
        if upto < 1:
            sys.exit("  --upto must be at least 1")
        if len(todo) > upto:
            print(f"  --upto {upto}: generating {upto} of {len(todo)} remaining shot(s)")
            todo = todo[:upto]
    if not todo:
        print("  nothing to generate")
    for i, s in enumerate(todo):
        print(f"\n── {s['id']} ({done + i + 1}/{len(shots)}) ──")
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
          "video": stage_video, "assemble": stage_assemble, "episode": stage_episode,
          "costs": stage_costs, "audio": stage_audio, "bed": stage_bed, "song": stage_song, "track": stage_track, "beats": stage_beats, "animatic": stage_animatic,
          "ending": stage_ending, "estimate": stage_estimate, "release": stage_release, "contact": stage_contact, "lock": stage_lock, "stabilize": stage_stabilize,
          # dispatched explicitly below: these take a LOCATION id, not an episode id
          "plate-candidate": None, "plate-approve": None}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("episode", nargs="?", help="episode id, e.g. E01 (not needed for portraits)")
    ap.add_argument("--upto", type=int, default=None,
                    help="episode stage: generate at most N new shots this run, so spend "
                         "can be authorised in bounded slices")
    ap.add_argument("--attempt", type=int, default=None,
                    help="plate-approve: which candidate attempt becomes canonical")
    ap.add_argument("--clip", dest="clip", default=None,
                    help="track: which Suno take to use, by clip id prefix")
    ap.add_argument("--from", dest="source", default=None,
                    help="plate-candidate: derive from ACCEPTED footage, e.g. E01/s01")
    ap.add_argument("--override", default=None,
                    help="plate-candidate: reason for buying another attempt after a "
                         "previous one was judged; recorded in provenance")
    a = ap.parse_args()
    plate_stage = a.stage.startswith("plate-")
    if a.stage not in ("portraits", "verify", "costs") and not a.episode:
        need = ("a location id, e.g. make.py plate-candidate cottage_night" if plate_stage
                else f"an episode id, e.g. make.py {a.stage} E01")
        sys.exit(f"`{a.stage}` needs {need}")
    if a.upto is not None and a.stage != "episode":
        sys.exit("--upto only applies to the `episode` stage")
    if a.attempt is not None and a.stage != "plate-approve":
        sys.exit("--attempt only applies to `plate-approve`")
    print(f"stage: {a.stage} {a.episode or ''}   spent: Rs {ledger()['spent_inr']:.2f}"
          f"/{C.BUDGET_INR}\n")
    if a.stage == "episode":
        stage_episode(a.episode, upto=a.upto)
    elif a.stage == "track":
        stage_track(a.episode, clip_id=a.clip)
    elif a.stage == "plate-candidate":
        stage_plate_candidate(a.episode, source=a.source, override=a.override)
    elif a.stage == "plate-approve":
        if a.attempt is None:
            sys.exit("  plate-approve needs --attempt N")
        approve_plate_attempt(a.episode, a.attempt)
    else:
        STAGES[a.stage](a.episode)
