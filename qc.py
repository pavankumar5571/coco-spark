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
    "UNREQUESTED_VISUAL_ADDITION",   # observed: P01 floating particles, 2026-08-19
)

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
)

UNTESTED_PREVENTION = {
    "UNREQUESTED_VISUAL_ADDITION":
        "compile_prompt.veo_constraint_clause emits a no-particles constraint. "
        "IMPLEMENTED 2026-08-19, NEVER VALIDATED AGAINST THE PROVIDER — we deliberately "
        "did not spend to test it. Do not assume it works.",
}


@dataclass
class QCFinding:
    category: str
    evidence: str            # what was seen, and where
    specified: str           # what the ShotSpec actually called for


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


def decide(shot_id, findings, revision=None, capability=None, judged_by="HUMAN"):
    """No score, no threshold. Either the output matches the spec or it does not.

    `capability` records what the clip proved about the PROVIDER, independently of whether
    the clip itself is publishable.
    """
    bad = [f for f in findings if f.category in CATEGORIES]
    return QCVerdict(shot_id, "REJECTED_QC" if bad else "ACCEPTED", bad, revision or {},
                     capability or {}, judged_by)
