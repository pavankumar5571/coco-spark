"""Codex controls for G03 policies not fixed by the independent contract."""
from collector import Collector, ObservationConflict
from opportunity import select_opportunity


# A sub-interval reading is preserved exactly for audit, but excluded from the observation
# series handed to G02.
c = Collector(minimum_interval_seconds=3600)
c.record_observation(video_id="v", observed_at="2026-08-20T10:00:00Z", views=100)
short = c.record_observation(video_id="v", observed_at="2026-08-20T10:03:00Z", views=104)
assert short["below_minimum_interval"] is True
assert len(c.raw_snapshots("v")) == 2 and len(c.snapshots("v")) == 1

# Partial batches remain inspectable, but are explicitly prohibited as opportunity input.
batch = c.ingest_search_pages(query="q", region="ca", language="EN",
                              pages=[[{"video_id": "a"}], None, [{"video_id": "b"}]])
assert batch["video_ids"] == [] and batch["retry_video_ids"] == ["a", "b"]
assert batch["failed_pages"] == [1]
assert batch["complete"] is False and batch["usable_for_opportunity"] is False

# Cross-module regression: the production-shaped handoff from an incomplete batch contains
# no videos, so G02 cannot prove an opportunity even if a caller ignores the boolean flag.
result = select_opportunity({
    "candidate": {"candidate_id": "partial", "match_any_phrases": ["x"]},
    "videos": [{"video_id": video_id} for video_id in batch["video_ids"]],
})
assert result["status"] == "OPPORTUNITY_UNPROVEN" and result["metrics"]["matched_videos"] == 0

# Same-instant retry is idempotent only when it says the same thing; conflicting public
# counters are surfaced rather than silently choosing one.
c = Collector()
c.record_observation(video_id="v", observed_at="2026-08-20T10:00:00Z", views=100)
try:
    c.record_observation(video_id="v", observed_at="2026-08-20T10:00:00Z", views=101)
except ObservationConflict:
    pass
else:
    raise AssertionError("same-instant conflicting counters were silently accepted")

print("collector policy controls passed: interval audit / partial handoff refusal / conflict")
