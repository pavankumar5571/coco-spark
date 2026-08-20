"""Offline policy controls for the live canary's temporal handoff."""
from youtube_canary import evidence_snapshots


rows = evidence_snapshots([
    {"observed_at": "2026-08-20T10:00:00Z", "views": 100},
    {"observed_at": "2026-08-20T13:30:00Z", "views": 170},
])
assert rows == [
    {"observed_hour": 0.0, "views": 100},
    {"observed_hour": 3.5, "views": 170},
]

print("youtube canary policy controls passed: real elapsed hours preserved")
