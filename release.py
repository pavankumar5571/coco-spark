"""The boundary between preparing a release and performing one.

videos.insert is the FIRST external mutation this pipeline has ever made. Everything else
it does is local, reversible and free; this reaches out and changes the world. So the
mutation gets its own command, its own name and its own arguments — never a flag on a
generic one, and never a privacy setting that arrives from a default.

    release.py prepare        [EPISODE]   validates everything, touches no network
    release.py upload-private [EPISODE]   performs the mutation, explicitly, in its name
    release.py verify         [EPISODE]   reads back what the platform says is true

A public launch will be a THIRD command against an already-uploaded id. The path used for
today's technical test must never be one omitted argument away from launching the channel.

THE EPISODE IS AN ARGUMENT, NOT A CONSTANT. It was a constant while E01 was the only
artifact, and that is business identity welded into reusable release code: E02 could not
have used this path without editing Python. Provider-shaped code — the ISO 8601 parser,
the scope map — is a different thing and stays; it belongs to the YouTube boundary.
"""
from __future__ import annotations

import hashlib, json, subprocess, sys, time
from pathlib import Path

PURPOSE = "PRIVATE_PUBLISH_PATH_TEST"
DEFAULT_EPISODE = "E01"


def paths(episode=DEFAULT_EPISODE):
    """Where an episode's release lives. One place, so the three commands cannot disagree."""
    d = Path("out") / episode / "release"
    return {"dir": d, "master": d / f"{episode}_master.mp4",
            "metadata": d / "metadata.json", "manifest": d / "upload_manifest.json"}


def _read_manifest(p):
    """A manifest that does not exist yet is an empty record, not an error."""
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _iso8601_s(d):
    """PT1H2M3S -> seconds. YouTube states duration in ISO 8601, whole seconds only."""
    import re
    if not d:
        return 0.0
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0.0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return float(dd * 86400 + h * 3600 + mi * 60 + s)


def _probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,channels,sample_rate:format=duration",
        "-of", "json", str(p)], capture_output=True, text=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    return {"duration": round(float(j["format"]["duration"]), 3),
            "video": {k: v.get(k) for k in ("codec_name", "width", "height")},
            "audio": {k: a.get(k) for k in ("codec_name", "channels", "sample_rate")}}


def prepare(episode=DEFAULT_EPISODE, master=None, metadata_path=None, manifest=None):
    """Everything checkable without touching the network. No mutation, no session created.

    AND NO DESTRUCTION EITHER, which it did not honour until now. This function wrote a
    freshly-built record straight over the manifest, so running the command documented as
    "touches no network" erased youtube_video_id, observed, human_inspection and the frozen
    state — the entire record of what the platform had actually done. upload_private then
    read that erased file looking for the video id it had just destroyed, which is why the
    duplicate guard below never once fired.

    A preparation record is now MERGED over the prior one, and preservation is the default:
    unknown keys survive because a future field must not need this function to be edited.
    Mutation history is only dropped when the bytes are different, and then it is recorded
    as superseded rather than silently discarded.
    """
    import youtube_upload as yt
    p = paths(episode)
    master = Path(master or p["master"])
    meta_p = Path(metadata_path or p["metadata"])
    manifest = Path(manifest or p["manifest"])
    fails = []
    if not master.exists():
        fails.append(f"master missing: {master}")
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    if not meta.get("title"):
        fails.append("metadata has no title")

    # credentials PRESENT, never their values — this function must be safe to run anywhere
    for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not yt._env(k, required=False):
            fails.append(f"{k} not available")

    audit_p = master.parent / "private_test_audit.json"
    if audit_p.exists():
        if not json.loads(audit_p.read_text(encoding="utf-8")).get("all_pass"):
            fails.append("private_test_audit did not pass")
    else:
        fails.append("no private_test_audit.json")

    tech = _probe(master) if master.exists() else {}
    prepared = {
        "kind": "UPLOAD_MANIFEST", "purpose": PURPOSE, "episode": episode,
        "prepared_at": time.strftime("%F %T"),
        "master": str(master), "master_sha256": _sha256(master) if master.exists() else None,
        "master_bytes": master.stat().st_size if master.exists() else None,
        "technical": tech,
        "intended": {"title": meta.get("title"), "privacy": "private",
                     "made_for_kids": bool(meta.get("made_for_kids", True)),
                     "tags": meta.get("tags", [])},
        "contains_no_secrets": True,
        "ready": not fails, "blockers": fails,
    }
    prior = _read_manifest(manifest)
    if prior and prior.get("master_sha256") == prepared["master_sha256"]:
        # SAME BYTES. Everything the platform told us about them is still true, including
        # fields no version of this function has heard of. Preserve by default.
        m = {**prior, **prepared}
    else:
        m = dict(prepared)
        if prior.get("youtube_video_id"):
            # DIFFERENT BYTES. The old observations describe a different artifact and must
            # not be inherited — but they are still what happened, so they are recorded as
            # superseded rather than deleted.
            m["supersedes"] = {k: prior.get(k) for k in
                               ("master_sha256", "youtube_video_id", "uploaded_at")}

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def upload_private(episode=DEFAULT_EPISODE, master=None, metadata_path=None, manifest=None):
    """Perform the mutation. Refuses unless prepare() says ready, and refuses to repeat.

    IDEMPOTENCE MATTERS MORE HERE THAN ANYWHERE ELSE IN THE PIPELINE. Once YouTube has
    accepted bytes, a blind retry can create a SECOND video. So a manifest that already
    carries a video id for these exact bytes is a completed upload, not a reason to try
    again — the same reasoning as reserve-before-invoke, applied to an external mutation
    instead of to money.

    THE PRIOR STATE IS READ BEFORE ANYTHING CAN WRITE IT. It was not: prepare() ran first
    and overwrote the manifest, so this function then searched the file it had just erased
    for the video id that proved the upload had happened. The guard was present, commented,
    and dead from the day it was written. Idempotence state that is read after a writer has
    run is not idempotence state.
    """
    import youtube_upload as yt
    p = paths(episode)
    manifest = Path(manifest or p["manifest"])
    master = Path(master or p["master"])
    metadata_path = Path(metadata_path or p["metadata"])

    prior = _read_manifest(manifest)                       # BEFORE prepare(), always

    m = prepare(episode, master, metadata_path, manifest)
    if not m["ready"]:
        sys.exit("  NOT READY:\n    " + "\n    ".join(m["blockers"]))

    if prior.get("youtube_video_id") and prior.get("master_sha256") == m["master_sha256"]:
        sys.exit(f"  ALREADY UPLOADED: {prior['youtube_video_id']} for these exact bytes. "
                 f"Refusing to create a duplicate.")

    # Acquisition-time validation is necessary and NOT sufficient. A credential can be
    # revoked, a scope policy can change, an account can lose the channel, between the
    # consent that minted the token and the moment it is used. So the mutation checks the
    # authority it is about to exercise, immediately before exercising it — one free token
    # refresh standing in front of an irreversible external write. It fails CLOSED: if the
    # refresh raises because the token was revoked, no upload is attempted.
    if yt.scope_preflight(yt.granted_scopes(), ["upload"]):
        sys.exit("  cannot upload with this credential — re-run consent.")

    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"  uploading {m['master_bytes']/1e6:.1f} MB as PRIVATE …")
    vid = yt.upload(master, meta, privacy="private")

    m["youtube_video_id"] = vid
    m["uploaded_at"] = time.strftime("%F %T")
    manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
    print(f"  video id {vid}")
    return vid


def verify(episode=DEFAULT_EPISODE, video_id=None, manifest=None):
    """Record what YouTube ACTUALLY did, read back from the API.

    Not what we asked for — what it says is true afterwards. Every other stage of this
    project has been caught out by trusting a request instead of reading the result.
    """
    import youtube_upload as yt
    import urllib.request, urllib.parse
    # Say WHY before failing. The first run of this returned a bare 403 because the
    # credential carried youtube.upload only — a fact knowable for free, before any
    # request, from the token itself. Asking first turns an opaque HTTP error into the
    # actual diagnosis: this token cannot observe, so it cannot verify.
    manifest = Path(manifest or paths(episode)["manifest"])
    m = _read_manifest(manifest)
    vid = video_id or m.get("youtube_video_id")
    # NO ID IS A LOCAL FACT. Asking the network about `id=None` is the same defect as
    # every other one in this file: an invalid deterministic state reaching a provider.
    # It is knowable here, for free, before any credential is touched.
    if not vid:
        sys.exit(f"  no video id recorded for {episode} — nothing to verify.")
    if yt.scope_preflight(yt.granted_scopes(), ["verify"]):
        sys.exit("  cannot verify with this credential — re-run consent.")
    q = urllib.parse.urlencode({"part": "status,contentDetails,snippet,processingDetails",
                                "id": vid})
    req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/videos?{q}",
        headers={"Authorization": f"Bearer {yt.access_token()}"})
    with urllib.request.urlopen(req) as r:
        items = json.loads(r.read()).get("items", [])
    if not items:
        sys.exit(f"  {vid} not visible via the API yet")
    it = items[0]
    observed = {
        "privacy": it["status"].get("privacyStatus"),
        "made_for_kids": it["status"].get("madeForKids"),
        "self_declared_made_for_kids": it["status"].get("selfDeclaredMadeForKids"),
        "upload_status": it["status"].get("uploadStatus"),
        "processing": it.get("processingDetails", {}).get("processingStatus"),
        "duration": it.get("contentDetails", {}).get("duration"),
        "title": it["snippet"].get("title"),
    }
    m["observed"] = observed
    m["verified_at"] = time.strftime("%F %T")
    # YouTube reports its OWN duration, and it is not ours: a 12.000s master comes back
    # as PT13S. Recording the delta rather than assuming agreement — the whole point of
    # reading the result is that it may differ from what we sent, in ways nobody predicted.
    m["duration_delta_s"] = _iso8601_s(observed["duration"]) - m.get("technical", {}).get("duration", 0)
    m["matches_intent"] = (observed["privacy"] == "private"
                           and observed["self_declared_made_for_kids"] is True)
    manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    episode = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EPISODE
    if cmd == "prepare":
        r = prepare(episode)
        print(json.dumps({k: r[k] for k in ("episode", "master_sha256", "master_bytes",
                                            "technical", "intended", "ready", "blockers")},
                         indent=2))
    elif cmd == "upload-private":
        upload_private(episode)
    elif cmd == "verify":
        print(json.dumps(verify(episode).get("observed"), indent=2))
    else:
        print(__doc__)
