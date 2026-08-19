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

    def to_json(self):
        return {"shot_id": self.shot_id, "status": self.status,
                "findings": [f.__dict__ for f in self.findings],
                "revision": self.revision}


def decide(shot_id, findings, revision=None):
    """No score, no threshold. Either the output matches the spec or it does not."""
    bad = [f for f in findings if f.category in CATEGORIES]
    return QCVerdict(shot_id, "REJECTED_QC" if bad else "ACCEPTED", bad, revision or {})
