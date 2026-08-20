"""Three-case battle test for generic YouTube opportunity evidence."""
from opportunity import select_opportunity


def video(number, title, channel, gains, channel_peers=(80, 90, 100, 110),
          cohort_peers=(100, 110, 120, 130), query="broad kids topic"):
    snapshots = [{"observed_hour": i * 4, "views": sum(gains[:i + 1])}
                 for i in range(len(gains))]
    return {"video_id": f"v{number}", "channel_id": channel, "title": title,
            "query": query, "region": "US", "language": "en",
            "channel_owner_hint": f"owner-{channel}",
            "snapshots": snapshots, "channel_peer_velocities": list(channel_peers),
            "cohort_peer_velocities": list(cohort_peers)}


def payload(candidate, videos):
    return {"candidate": {"candidate_id": candidate,
                          "match_any_phrases": [candidate.replace("_", " ")],
                          "match_all_terms": candidate.split("_"),
                          "mode_markers": {"SONG": ["song", "sing", "rhyme", "music"],
                                           "EPISODE": ["story", "episode", "adventure", "learn"]}},
            "videos": videos}


# Battle 1: three independent channels, repeated measurements, peer-relative acceleration,
# and convergent song evidence. Expected: a song opportunity, not merely popular videos.
song = payload("moon_counting", [
    video(1, "Moon Counting Song", "a", [100, 1800, 1900]),
    video(2, "Sing the Moon Counting Rhyme", "b", [80, 1600, 1800],
          query="preschool night counting"),
    video(3, "Moon Counting Music for Kids", "c", [120, 2000, 2200]),
])
r = select_opportunity(song)
assert r["status"] == "OPPORTUNITY_PROVEN" and r["selection"] == "SONG", r

# Battle 2: a huge lifetime count with one snapshot plus two same-channel copies must not
# become evidence. Expected: explicitly unproven.
false_viral = payload("robot_colors", [
    video(4, "Robot Colors Song", "one", [10_000_000]),
    video(5, "Robot Colors Song Remix", "one", [100, 200, 200]),
    video(6, "Robot Colors Music", "one", [100, 220, 220],
          query="preschool robot learning"),
])
r = select_opportunity(false_viral)
assert r["status"] == "OPPORTUNITY_UNPROVEN", r
assert "fewer_than_3_independent_channels" in r["reasons"], r

# Battle 3: a real independent-channel breakout cluster whose titles disagree on format.
# Expected: opportunity proven, production mode still UNPROVEN rather than invented.
ambiguous = payload("garden_shapes", [
    video(7, "Garden Shapes Song", "x", [100, 1700, 1900]),
    video(8, "Garden Shapes Story", "y", [100, 1800, 2000],
          query="preschool outdoor shapes"),
    video(9, "Garden Shapes Adventure", "z", [100, 1900, 2100]),
])
r = select_opportunity(ambiguous)
assert r["status"] == "OPPORTUNITY_PROVEN" and r["selection"] == "UNPROVEN", r
assert "format_evidence_ambiguous" in r["reasons"], r

print("opportunity battle tests passed: SONG / false-viral refusal / ambiguous-format refusal")
