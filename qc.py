"""Minimal semantic QC contract, grown from evidence rather than imagination.

Exactly ONE category earns a place today, because exactly one provider-side failure has
been observed: the P01 probe produced floating luminous particles present in no prompt,
bible entry or location description.

Twenty hypothetical categories would be speculation. Categories are added when a real
generation exhibits them.

QC FAILURE DOES NOT TRIGGER REGENERATION. The terminal state is REJECTED_QC. Automatic
retry on a quality signal is how an unbounded spend loop begins.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES = (
    "UNREQUESTED_VISUAL_ADDITION",   # a thing that is not supposed to be there at all
    "UNREQUESTED_AMBIENT_EFFECT",    # atmosphere the provider adds: motes, haze, glow
)

# SEVERITY, not a binary. "Anything unrequested is a reject" sounds rigorous and is
# actually a way to never publish: one harmless deviation the provider cannot be talked
# out of blocks every episode forever.
BLOCKING = "BLOCKING"        # the clip cannot be published
TOLERATED = "TOLERATED"      # real, recorded, and not worth blocking a launch over

# Tolerance is granted per (category, mode) and NEVER by default. A warm bedtime room can
# carry soft ambient motes; a counting lesson or a science demonstration cannot, because
# there the same specks compete with the thing the child is supposed to be looking at.
# Anything not listed here is BLOCKING.
TOLERATED_DEVIATIONS = {
    ("UNREQUESTED_AMBIENT_EFFECT", "BEDTIME_STORY"): {
        "provider_surface": "GEMINI_DEVELOPER_API",
        "model": "veo-3.1-lite-generate-preview",
        "observed_frequency": "3 of 4 relevant clips (P01, E01/s01, s02, s03; P01B clean)",
        "control_available": False,
        "why_no_control": "seed, negative_prompt and enhance_prompt are ALL rejected by "
                          "this model; prose is the only channel and it failed 3 of 4",
        "rationale": "visually soft, does not alter characters or world topology, does "
                     "not obscure the story, introduces no entity, changes no meaning",
        "publication_blocking": False,
        "escape_hatch": "Vertex surface documents negativePrompt. Revisit if this becomes "
                        "a brand or content problem — NOT before the channel publishes.",
        "recorded": "2026-08-19",
    },
}


def severity(category, mode):
    """Default BLOCKING. Tolerance is an explicit, mode-scoped, recorded decision.

    Deliberately not inherited across modes: tolerating motes in a bedtime story says
    nothing about tolerating them in a classroom scene.
    """
    return TOLERATED if (category, mode) in TOLERATED_DEVIATIONS else BLOCKING

# PROVIDER CAPABILITY and CLIP PUBLISHABILITY are different measurements and must never
# be collapsed. P01 is not a failed motion probe: it is MOTION_PRIMITIVE=PASS and
# CLIP_ACCEPTANCE=REJECTED_QC simultaneously. Merging them would, months from now, make
# Veo look like it has a poor motion success rate when the real defect was generative
# additions.
CAPABILITY_PROBES = (
    "MOTION_PRIMITIVE",       # did the requested transition occur
    "IDENTITY_PRESERVATION",  # did the character survive the motion
    "WORLD_PRESERVATION",     # did set geometry survive the motion
)

# Prevention implemented from a hypothesis is NOT prevention demonstrated. Anything listed
# here is untested against the provider, and must not be treated as solved.
# Evidence strength. n=1 against a STOCHASTIC generator does not validate anything: an
# unconstrained sample might also have produced no particles. Strength is recorded
# explicitly so a single lucky clip never gets promoted to "solved".
TRIAL_STRENGTH = (
    "UNTESTED",
    "POSITIVE_SINGLE_TRIAL",              # helped once; not a prevention rate
    "PREVENTION_FAILED_ON_CONTROLLED_TRIAL",
    "MIXED_SINGLE_TRIAL",                 # treatment traded one defect for another
    # A BUNDLE of parameters changed together can only ever be judged as a bundle. Naming
    # these separately stops a passing result being written up as "we found the cause",
    # which is what a single-variable label would quietly imply.
    "POSITIVE_SINGLE_TRIAL_FOR_GENERATION_CONTRACT",
    "CONTRACT_FAILED_ON_CONTROLLED_TRIAL",
    "TRADE_OFF",
)

# Changing several generation parameters in one paid call buys a production answer, not a
# causal one. Recorded here so a later reader cannot mistake the two.
CONFOUNDED_TREATMENTS = {
    "GENERATION_CONTRACT_V2": {
        "changed_together": ("enhance_prompt=False", "negative_prompt=<compiled>",
                             "seed=<fixed>"),
        "answers": "is the hardened contract production-useful",
        "does_not_answer": "which of the three parameters mattered, or whether Veo on the "
                           "Gemini Developer API honours enhance_prompt=False at all — "
                           "the SDK accepting a field is not the backend obeying it",
    },
}

UNTESTED_PREVENTION = {}

# Preventions that have been put in front of the real provider at least once. The strength
# label is load-bearing: it is what stops a single clean clip becoming "we solved that".
TESTED_PREVENTION = {
    "UNREQUESTED_VISUAL_ADDITION": {
        "mechanism": "compile_prompt.veo_constraint_clause emits a no-particles constraint",
        "trials": [
            ("P01B", "2026-08-19", "CLEAN",  "controlled against P01, byte-identical start frame"),
            ("E01/s01", "2026-08-19", "PARTICLES", "WIDE, clean generated still"),
            ("E01/s02", "2026-08-19", "PARTICLES", "CLOSE, clean generated still"),
            ("E01/s03", "2026-08-19", "PARTICLES", "CLOSE, inherited clean pixels"),
        ],
        "strength": "PREVENTION_FAILED_ON_CONTROLLED_TRIAL",
        "capability_effect": "NO_REGRESSION — motion, identity and world all held in every "
                             "clip. The defect is additive only.",
        "finding": "1 clean of 4 attempts with a byte-identical constraint clause. The "
                   "clause is NOT a reliable control. In every failure the input still was "
                   "verified clean, so the addition is introduced by the VIDEO model, not "
                   "the image model — which is what narrows the next fix to the video "
                   "stage rather than the prompt compiler in general.",
        "do_not": "Do not re-roll clips hoping for a clean sample. At roughly 1-in-4 that "
                  "is a slot machine, and paying per pull is how the previous project "
                  "reached Rs 30,000.",
    },
}


# A location plate is not a clip and must not be judged with clip semantics. It is
# long-lived authority: every future frame in that location inherits object FORM from it,
# so a defect here is not one bad shot, it is a bad world that keeps being right.
PLATE_PROBES = (
    "LOCATION_IDENTITY",     # is this recognisably the place the bible describes
    "WORLD_GEOGRAPHY",       # does the arrangement match the declared FIXED LAYOUT
    "PERSISTENT_OBJECTS",    # is every persistent object FULLY visible and legible as form
    "STYLE_CONFORMANCE",     # does it obey style_lock
    "TEXT_HALLUCINATION",    # any lettering at all is blocking
    "UNREQUESTED_ENTITIES",  # characters or props that are not part of the place
    "TECHNICAL_VALIDITY",    # dimensions, format, not corrupt
    "CANON_AGREEMENT",       # does it agree with footage already ACCEPTED for this place
)


@dataclass
class QCFinding:
    category: str
    evidence: str            # what was seen, and where
    specified: str           # what the ShotSpec actually called for
    severity: str = "BLOCKING"   # set by decide() from the mode-scoped tolerance table


@dataclass
class QCVerdict:
    shot_id: str
    status: str                       # ACCEPTED | REJECTED_QC
    findings: list = field(default_factory=list)
    revision: dict = field(default_factory=dict)
    capability: dict = field(default_factory=dict)   # probe -> PASS | FAIL | NOT_TESTED
    judged_by: str = "HUMAN"          # automated judging needs labelled examples first

    def to_json(self):
        return {"shot_id": self.shot_id, "status": self.status,
                "findings": [f.__dict__ for f in self.findings],
                "capability": self.capability, "judged_by": self.judged_by,
                "revision": self.revision}


def compare_capability(baseline: dict, treatment: dict):
    """A treatment that removes one defect while degrading a proven capability is a
    TRADE-OFF, not a success. Compare the whole vector, never the target defect alone."""
    regressions = [k for k, v in baseline.items()
                   if v == "PASS" and treatment.get(k) not in ("PASS", None)]
    return {"regressions": regressions,
            "verdict": "TRADE_OFF" if regressions else "NO_REGRESSION"}


def decide(shot_id, findings, revision=None, capability=None, judged_by="HUMAN",
           mode=None):
    """No score, no threshold — but severity-aware.

    Every finding is still RECORDED. What changes is whether it blocks publication. A
    TOLERATED deviation stays visible in the verdict forever, so nobody can later claim
    the footage was clean; it simply does not veto the episode.

    `capability` records what the clip proved about the PROVIDER, independently of whether
    the clip itself is publishable.
    """
    known = [f for f in findings if f.category in CATEGORIES]
    for f in known:
        f.severity = severity(f.category, mode)
    blocking = [f for f in known if f.severity == BLOCKING]
    return QCVerdict(shot_id, "REJECTED_QC" if blocking else "ACCEPTED", known,
                     revision or {}, capability or {}, judged_by)


# ---------------------------------------------------------------------------
# CANON_AGREEMENT — does a candidate plate agree with footage already ACCEPTED?
#
# A plate is not judged like a clip. It is long-lived authority: once canonical, every
# future frame inherits object FORM from it, so a plate that disagrees with published
# episodes is WORSE than no plate — the plate wins from that point onward and the
# audience sees the contradiction, not the schema.
#
# Attempt 001 for cottage_night passed geography perfectly and still had to be rejected:
# accepted s01-s03 show a RECTANGULAR FRINGED rug, the candidate invented a ROUND BRAIDED
# one. No probe in the contract asked that question. This is that probe.
#
# Three outcomes per object, and the third is load-bearing:
#   MATCH          the form visible in the source is preserved in the candidate
#   CONTRADICTION  the candidate shows a DIFFERENT form for something already seen
#   NOT_OBSERVABLE the source never showed it (e.g. the completed portion of a shelf
#                  that was cropped), so there is nothing to agree or disagree with
#
# NOT_OBSERVABLE is not a soft pass. It is an honest statement that these pixels are
# NEWLY ESTABLISHED and become canon only through human acceptance — which is legitimate,
# because canon means "the accepted visual specification from here on", not "historically
# observed everywhere". Collapsing it into MATCH would let a plate claim agreement with
# footage that never showed the object.
MATCH = "MATCH"
CONTRADICTION = "CONTRADICTION"
NOT_OBSERVABLE = "NOT_OBSERVABLE"
CANON_JUDGEMENTS = (MATCH, CONTRADICTION, NOT_OBSERVABLE)


def canon_agreement(required_objects, judgements):
    """PURE. Decide the CANON_AGREEMENT probe from a per-object judgement map.

    Returns (status, reasons). Status is PASS only when every required object has been
    judged and none contradicts canon. Incompleteness FAILS: a probe that can be passed
    by not looking at something is worse than no probe, because it retires the concern.
    """
    reasons = []
    judgements = judgements or {}
    missing = [o for o in required_objects if o not in judgements]
    if missing:
        reasons.append("NOT JUDGED: " + ", ".join(sorted(missing)))
    bad = sorted(k for k, v in judgements.items() if v not in CANON_JUDGEMENTS)
    if bad:
        reasons.append("not a CANON_AGREEMENT judgement: " + ", ".join(bad))
    contra = sorted(k for k, v in judgements.items() if v == CONTRADICTION)
    if contra:
        reasons.append("CONTRADICTS accepted footage: " + ", ".join(contra))
    unknown = sorted(k for k in judgements if k not in required_objects)
    if unknown:
        reasons.append("not a declared persistent object: " + ", ".join(unknown))
    return ("FAIL" if reasons else "PASS"), reasons


def plate_probe_completeness(probes):
    """PURE. Every plate probe must be answered, and every answer must be PASS.

    Approval reads a verdict written by a human. Silence is not consent: a verdict that
    simply omits a probe must not be able to authorise canon.
    """
    probes = probes or {}
    missing = [p for p in PLATE_PROBES if p not in probes]
    failed = [p for p, v in probes.items() if p in PLATE_PROBES and v != "PASS"]
    extra = [p for p in probes if p not in PLATE_PROBES]
    reasons = []
    if missing:
        reasons.append("probes not answered: " + ", ".join(missing))
    if failed:
        reasons.append("probes FAILED: " + ", ".join(sorted(failed)))
    if extra:
        reasons.append("unknown probes: " + ", ".join(sorted(extra)))
    return (not reasons), reasons


# ---------------------------------------------------------------------------
# AUDIO. Every probe above this line LOOKS. None of them listens, and E01 was accepted,
# assembled and called publish-quality with a 13.4 LU volume lurch at its first cut that
# nobody had measured. A preschool audience notices bad audio in one second.
#
# Two different questions, deliberately separated:
#
#   the DELIVERED programme   is what the audience hears. These probes BLOCK.
#   the PROVIDER's native audio  is a by-product we discard. Measuring it says something
#                                about the provider, never about the episode, so those
#                                results are OBSERVATIONS and block nothing.
AUDIO_PROBES = (
    "PROGRAMME_LOUDNESS",    # delivered integrated loudness is at our house target
    "AUDIO_SPANS_PICTURE",   # the spine covers the whole episode, with no silent tail
    "NO_PROVIDER_AUDIO",     # nothing of the generator's own soundtrack survived
    "UNREQUESTED_SPEECH",    # any voice, word or gibberish, in a wordless piece
)

PROVIDER_AUDIO_OBSERVATIONS = (
    "NATIVE_LOUDNESS_SPREAD",   # how far apart independently generated clips landed
)


def programme_loudness(measured, target, tolerance):
    """PURE. Is the delivered mix at the house target?

    `measured` is None when there is no audio at all, which is a FAIL rather than a pass:
    an episode that ships silent has not met the target, it has skipped it.
    """
    if measured is None:
        return "FAIL", "no audio stream in the delivered episode"
    off = round(measured - target, 1)
    if abs(off) > tolerance:
        return "FAIL", f"{measured} LUFS is {off:+} LU from the {target} LUFS target"
    return "PASS", f"{measured} LUFS ({off:+} LU)"


def audio_spans_picture(audio_seconds, picture_seconds, tolerance=0.25):
    """PURE. A bed that stops early leaves the episode ending in silence."""
    if audio_seconds is None:
        return "FAIL", "no audio stream"
    gap = round(picture_seconds - audio_seconds, 3)
    if abs(gap) > tolerance:
        return "FAIL", (f"audio {audio_seconds}s vs picture {picture_seconds}s "
                        f"({gap:+}s)")
    return "PASS", f"audio {audio_seconds}s covers picture {picture_seconds}s"


def native_loudness_spread(per_clip):
    """PURE. An OBSERVATION about the provider, not a verdict on the episode.

    Recorded because it is the evidence for discarding provider audio, and because a
    future provider that generates a consistent bed would show up here as a changed
    capability rather than as a hunch.
    """
    vals = [v for v in per_clip.values() if v is not None]
    if len(vals) < 2:
        return {"observation": "NOT_OBSERVABLE", "per_clip": per_clip}
    spread = round(max(vals) - min(vals), 1)
    return {"observation": "OBSERVED", "spread_lu": spread, "per_clip": per_clip,
            "means": ("independently generated per-clip audio is not a continuous bed"
                      if spread > 3.0 else
                      "per-clip audio landed close enough to be worth re-examining")}
