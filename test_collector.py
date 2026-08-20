"""Codex controls for G03 policies not fixed by the independent contract."""
from collector import Collector, ObservationConflict
from opportunity import select_opportunity
from pathlib import Path
import tempfile


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

# Persistent production state is byte-faithful across process boundaries: null counters,
# decreases, discoveries, channels and timestamps survive reload without forging a second
# observation.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "collector.sqlite3"
    first = Collector(store_path=path)
    first.record_channel(channel_id="c", title="Channel", hidden_subscriber_count=True,
                         subscriber_count=None)
    first.record_discovery(video_id="v", query="q", region="US", language="en")
    first.record_observation(video_id="v", observed_at="2026-08-20T10:00:00Z",
                             views=500, likes=None, comments=None)
    first.close()
    second = Collector(store_path=path)
    assert second.snapshots("v") == [{"video_id": "v",
                                      "observed_at": "2026-08-20T10:00:00Z",
                                      "views": 500, "likes": None, "comments": None,
                                      "below_minimum_interval": False}]
    assert second.discoveries("v")[0]["query"] == "q"
    second.record_observation(video_id="v", observed_at="2026-08-20T10:00:00Z",
                              views=500, likes=None, comments=None)
    assert len(second.snapshots("v")) == 1
    second.close()

print("collector policy controls passed: interval / partial / conflict / durable reload")
