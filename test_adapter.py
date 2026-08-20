"""Codex policy and cross-boundary controls for G04."""
import adapter
from collector import Collector


# A token loop is incomplete and the production-shaped field fails closed, while partial
# work remains available exclusively for retry.
t = adapter.FakeTransport(pages={None: (["v1"], "a"), "a": (["v2"], "a")})
batch = adapter.search(query="q", region="us", language="EN", transport=t)
assert batch["complete"] is False and batch["video_ids"] == []
assert batch["retry_video_ids"] == ["v1", "v2"]
assert batch["termination_reason"] == "pagination_token_loop"

# Default policy is three total attempts. Exhaustion is explicit and cannot hand partial
# population into the collector's production field.
t = adapter.FakeTransport(pages={None: [RuntimeError("x"), RuntimeError("x"),
                                        RuntimeError("x")]})
batch = adapter.search(query="q", region="US", language="en", transport=t)
assert batch["attempts"] == 3 and batch["failed_pages"] == [0]
assert batch["video_ids"] == []

# Successful retry remains usable, but its history is retained.
t = adapter.FakeTransport(pages={None: [RuntimeError("x"), (["v1"], None)]})
batch = adapter.search(query="q", region="US", language="en", transport=t)
assert batch["complete"] is True and batch["video_ids"] == ["v1"]
assert batch["attempts"] == 2 and batch["retried_pages"] == [0]

# The accepted collector can ingest the adapter's request provenance without using server
# echoes or manufacturing an owner relationship.
c = Collector()
for video_id in batch["video_ids"]:
    c.record_discovery(video_id=video_id, query=batch["query"],
                       region=batch["region"], language=batch["language"])
assert c.discoveries("v1") == [{"video_id": "v1", "query": "q",
                                "region": "US", "language": "en"}]

# One malformed/negative counter makes only that measurement unknown. Raw provider values
# survive, valid neighbours continue, and no fabricated zero enters G03.
t = adapter.FakeTransport(stats={
    "bad": {"viewCount": "abc", "likeCount": "-5", "commentCount": "1.2e3"},
    "good": {"viewCount": "1200", "likeCount": "12", "commentCount": "3"},
})
rows = adapter.fetch_statistics(["bad", "good"], transport=t)
assert (rows["bad"]["views"], rows["bad"]["likes"], rows["bad"]["comments"]) == (None, None, None)
assert rows["bad"]["raw_statistics"] == {
    "viewCount": "abc", "likeCount": "-5", "commentCount": "1.2e3"}
assert (rows["good"]["views"], rows["good"]["likes"], rows["good"]["comments"]) == (1200, 12, 3)

print("adapter policy controls passed: loop / retries / provenance / malformed counters")
