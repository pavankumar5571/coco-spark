"""The song is the clock. Everything visual is compiled against it.

Wave 2, Claude's column: audio/timing -> production brief. It takes a phrase map with
real word timings and a beat map that names phrases, and emits ONE brief that every
later stage reads instead of re-deriving durations from an animatic, a spreadsheet or
somebody's memory of how long the intro was.

THREE COORDINATE SYSTEMS, AND THEY MUST NOT BE CONFUSED.

    source_t    seconds into the file Suno returned, including 11.38s of intro
    song_t      seconds into the TRIMMED programme; the first sung word is at 2.5
    master_t    seconds into the delivered episode = signature_seconds + song_t

Word timings live in song_t and NEVER move. Branding is added by shifting the origin,
not by editing the map: an opening signature that grows by 200ms must not silently
retime sixteen visual cuts against a lyric. That is the whole reason this file exists.

It computes; it does not decide. Which song, which topic, which pictures are bought —
none of that is here. The compiler compiles whatever song wins.
"""
from __future__ import annotations

import json, sys
from pathlib import Path

import yaml

import config as C


def load_bible(root=Path(".")):
    """The show's own policy file. Modes, and what each mode is delivered at, live here."""
    return yaml.safe_load((Path(root) / "bible.yaml").read_text(encoding="utf-8"))

# BRANDING TIMING CONTRACT. Durations only — the rendered assets are a different module's
# problem, and deliberately so: their timing changes the beat map's offset, so it has to be
# frozen before pictures are bought, while the artwork can be made afterwards.
SIGNATURE_SECONDS = 1.2          # opening channel signature, 1.0-1.5 agreed
OUTRO_SECONDS     = 4.0          # closing card over the episode's own final image, 3-5

# PER-MODE PROGRAMME LOUDNESS LIVES IN THE BIBLE, NOT HERE. config.PROGRAMME_LUFS is a
# single global, which contradicts the agreed policy that a bedtime programme and a song
# are not delivered at the same level: a lullaby mastered to a song's target stops being a
# lullaby.
#
# This table used to be a dict in this file naming three modes. That made adding a fourth
# mode a code change, and it put a delivery decision somewhere a person editing the show's
# policy would never look. Modes are already defined in bible.yaml with their coverage,
# pacing and camera rules; the loudness they are delivered at belongs beside those.
#
# A mode whose programme_lufs is absent or null is UNSET on purpose. A listening test sets
# it, not a default, and asking for an unset mode is an error rather than a silent
# fallback to whatever happened to be in config.


# THE CIRCLE, AND HOW IT IS BROKEN WITHOUT LYING.
#
# A SONG target must come from listening to a real mastered mix. No such mix exists until
# the episode is assembled, which needs the pictures, which needs the target. Waiting would
# let an unmade recording block the recording that would make it.
#
# So a PRIVATE test master may be cut at a deliberately conservative level. That is not
# inheriting the bedtime policy and it is not a decision about SONG — it is choosing a
# level safe enough to produce the evidence the policy needs. SONG stays UNSET, and public
# release is refused until somebody has listened to that private artifact and set the real
# number from it.
PROVISIONAL_PRIVATE_LUFS = -20.0


def programme_lufs(mode, bible, private_test=False):
    """The delivered loudness target, or a refusal that names exactly what is missing."""
    modes = (bible or {}).get("modes") or {}
    if mode not in modes:
        raise KeyError(f"mode '{mode}' is not defined in bible.yaml; the modes there are "
                       f"{sorted(modes) or 'none'}")
    target = (modes[mode] or {}).get("programme_lufs")
    if target is not None:
        return float(target), "POLICY"
    if private_test:
        return PROVISIONAL_PRIVATE_LUFS, "PROVISIONAL_FOR_PRIVATE_TEST"
    raise ValueError(
        f"programme loudness for {mode} is UNSET. It must come from a listening test on a "
        f"real mastered mix, not from config.PROGRAMME_LUFS ({C.PROGRAMME_LUFS}), which is "
        f"a single global and cannot be right for every mode at once, and not from another "
        f"mode's number in bible.yaml. A PRIVATE test master may use the provisional level; "
        f"a public release may not.")


def words_from_lrc(path, head_trim):
    """Word-level timings, rebased into song_t by the same head trim as the phrase map.

    A phrase map is line granularity, and that is enough until a lyric COUNTS. "Four
    little stars, then three, then two" changes the number three times inside one line,
    so a cut anchored to the line lands on the first number and holds through the rest.
    The word timings were always in the .lrc; nothing had ever read them.
    """
    import re
    words, pending = [], None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", raw)
        if m:
            t = int(m.group(1)) * 60 + float(m.group(2)) - head_trim
            text = m.group(3).strip()
            # A timestamp carries the word that FOLLOWS it on the next line in this
            # format, except for a section label, which carries its own line.
            if pending is not None:
                words.append({"at": round(pending[0], 3), "text": pending[1]})
            pending = (t, text) if text else (t, "")
        elif raw.strip() and pending is not None:
            pending = (pending[0], raw.strip())
    if pending is not None and pending[1]:
        words.append({"at": round(pending[0], 3), "text": pending[1]})
    return [w for w in words if w["text"] and not w["text"].startswith("[")]


def find_word(words, text, nth=1):
    """The nth occurrence of a word, matched on its bare form. Returns song_t or None."""
    want = text.strip().lower().strip(".,!?")
    seen = 0
    for w in words:
        if w["text"].strip().lower().strip(".,!?") == want:
            seen += 1
            if seen == nth:
                return w["at"]
    return None


def compile_brief(episode, mode, signature=SIGNATURE_SECONDS, outro=OUTRO_SECONDS,
                  root=Path("."), private_test=False, bible=None):
    """phrase map + beat map -> one production brief, in all three coordinate systems."""
    bible = load_bible(root) if bible is None else bible
    d = Path(root) / "out" / episode
    phrases = json.loads((d / "phrases.json").read_text(encoding="utf-8"))
    beatmap = json.loads((d / "beats.json").read_text(encoding="utf-8"))

    ph = phrases["phrases"]
    trim = phrases["trimmed"]
    runtime = float(trim["runtime_seconds"])
    beats_in = beatmap["beats"]
    lrc = d / "suno" / f"{phrases['clip_id']}.lrc"
    words = words_from_lrc(lrc, float(trim["head_seconds"])) if lrc.exists() else []

    # A beat starts on the phrase it names and ends when the NEXT beat starts. The last
    # one runs to the end of the programme. Lengths are therefore never authored — they
    # are consequences of the song, which is the only way a cut can land on a word.
    def _start_of(b, i):
        """A beat says WHEN either by naming a phrase or by stating a time.

        The map uses both: fourteen beats carry from_phrase and two carry a bare `at`.
        Both are resolved rather than one being coerced into the other, because a beat
        pinned to a phrase MOVES if the song is retrimmed and a beat pinned to a number
        does NOT. Silently treating them alike would make a retrim look successful and
        put two cuts in the wrong place.
        """
        if "from_word" in b:
            w = b["from_word"]
            t = find_word(words, w["text"], w.get("nth", 1))
            if t is None:
                return None, (f"beat {i} anchors to word "
                              f"'{w['text']}' #{w.get('nth', 1)}, which is not sung")
            return t, None
        if "from_phrase" in b:
            idx = b["from_phrase"]
            if not 0 <= idx < len(ph):
                return None, f"beat {i} names phrase {idx}, which does not exist"
            return float(ph[idx]["at"]), None
        if "at" in b:
            return float(b["at"]), None
        return None, f"beat {i} says neither from_word, from_phrase nor at"

    beats, problems = [], []
    # A beat is ANCHORED if it moves when the song is re-cut: to a word, to a phrase, or
    # to the programme origin, which is 0.0 by definition and not a guess. Anything else
    # is a hand-typed timestamp that will be left behind by the next retrim while every
    # anchored beat around it moves — and the result looks fine right up until it doesn't.
    def _anchored(b):
        return ("from_word" in b or "from_phrase" in b
                or (b.get("at") == 0.0 and "why_at" in b))

    loose = [i for i, b in enumerate(beats_in) if not _anchored(b)]
    if loose:
        problems.append(
            f"beats {loose} are pinned to hand-typed times. A retrim moves every "
            f"anchored beat and leaves these behind. Anchor to the word or phrase they "
            f"belong to; only the programme origin may be a literal, and it must say why.")

    for i, b in enumerate(beats_in):
        start, why = _start_of(b, i)
        if why:
            problems.append(why)
            continue
        if i + 1 < len(beats_in):
            end, _ = _start_of(beats_in[i + 1], i + 1)
            end = runtime if end is None else end
        else:
            end = runtime
        idx = b.get("from_phrase")
        dur = round(end - start, 3)
        if dur <= 0:
            # A section label shares its timestamp with the line beneath it. Cutting on
            # both produces a zero-length beat, which is a cut nobody can see and a
            # division by zero waiting downstream.
            problems.append(f"beat {i} has non-positive duration {dur}s "
                            f"(phrase {idx})")
        beats.append({
            "index": i,
            "from_phrase": idx,
            "lyric": (ph[idx]["text"] if idx is not None
                      else (f"word: {b['from_word']['text']}" if "from_word" in b
                            else "(programme origin)")),
            "song_t": round(start, 3),
            "master_t": round(start + signature, 3),
            "duration_s": dur,
            "source": b.get("source"),
            "move": b.get("move"),
            "visual_change": b.get("visual_change"),
            "state": b.get("state"),
            "stars": b.get("stars"),
        })

    # THE PROVIDER'S CLIP LENGTH IS NOT NEGOTIABLE. A generated beat longer than one clip
    # is not a long beat, it is a beat nobody costed. Caught here, before a picture is
    # bought, rather than during assembly.
    for b in beats:
        if b["visual_change"] not in (None, "NONE", "CAMERA_ONLY") \
                and b["duration_s"] > C.VIDEO_SECONDS:
            problems.append(f"beat {b['index']} is generative and {b['duration_s']}s, "
                            f"longer than one {C.VIDEO_SECONDS}s clip")

    covered = round(sum(b["duration_s"] for b in beats), 3)
    if abs(covered - runtime) > 0.05:
        problems.append(f"beats cover {covered}s of a {runtime}s programme - "
                        f"{round(runtime - covered, 3)}s is unaccounted for")

    # WHAT IT COSTS, FROM THE BEATS. The existing estimator reads shots.json — three
    # all-generative shots, Rs 111, worst case Rs 166.50, DOES NOT FIT. That is the OLD
    # design. beats.json is the hybrid redesign that was supposed to fix exactly that, and
    # nobody had ever costed it, so the episode has been sitting behind a number that
    # belongs to a plan we already replaced.
    stills = sorted({b["source"]["id"] for b in beats
                     if (b["source"] or {}).get("kind") == "STILL"})
    gen = [b for b in beats if (b["source"] or {}).get("kind") == "GENERATIVE"]
    # A generated beat is billed per second of CLIP, and a clip is a whole VIDEO_SECONDS
    # unit whatever fraction of it the beat uses. Rounding down would under-reserve.
    gen_seconds = sum(C.VIDEO_SECONDS for _ in gen)
    frames_inr = len(stills) * C.INR_PER_IMAGE
    video_inr = gen_seconds * C.INR_PER_VID_SEC
    estimate = round(frames_inr + video_inr, 2)
    reserved = round(estimate * C.SAFETY_MARGIN, 2)

    try:
        lufs, lufs_basis = programme_lufs(mode, bible, private_test)
        lufs_note = None
    except (KeyError, ValueError) as e:
        lufs, lufs_basis, lufs_note = None, "UNSET", str(e)
        problems.append(str(e))

    return {
        "kind": "PRODUCTION_BRIEF",
        "episode": episode,
        "mode": mode,
        "song": {
            "clip_id": phrases.get("clip_id"),
            "source_audio": phrases.get("source_audio"),
            "head_trim_s": trim.get("head_seconds"),
            "first_word_song_t": trim.get("first_word_at"),
            "runtime_s": runtime,
        },
        "timeline": {
            # master_t = signature + song_t. Stated as data so no stage re-derives it.
            "signature_s": signature,
            "programme_s": runtime,
            "outro_s": outro,
            "master_total_s": round(signature + runtime + outro, 3),
            "song_origin_in_master_s": signature,
        },
        "audio": {
            "programme_lufs": lufs,
            "programme_lufs_basis": lufs_basis,
            "programme_lufs_unset_reason": lufs_note,
            "public_release_allowed": lufs_basis == "POLICY",
            "true_peak_db": C.PROGRAMME_TRUE_PEAK,
            "fade_s": C.AUDIO_FADE_SECONDS,
        },
        "beats": beats,
        # WHAT WILL ACTUALLY BE BOUGHT, counted from the data rather than from the map's
        # prose. The note on this beat map says "fifteen cuts over seven paid pictures";
        # the beats say sixteen cuts over four distinct stills plus one generated clip.
        # Prose is a claim, the data is the fact, and only one of them can be costed.
        "paid": {
            "still_ids": sorted({b["source"]["id"] for b in beats
                                 if (b["source"] or {}).get("kind") == "STILL"}),
            "generative_beats": [b["index"] for b in beats
                                 if (b["source"] or {}).get("kind") == "GENERATIVE"],
            "free_reused_tails": [b["index"] for b in beats
                                  if (b["source"] or {}).get("kind") == "TAIL_OF"],
            "beat_count": len(beats),
            "estimate_inr": estimate,
            "reserved_worst_case_inr": reserved,
            "breakdown": {
                "stills": f"{len(stills)} x Rs {C.INR_PER_IMAGE} = Rs {frames_inr}",
                "video": f"{gen_seconds}s x Rs {C.INR_PER_VID_SEC}/s = Rs {video_inr}",
            },
        },
        "ready": not problems,
        "problems": problems,
    }


def main(argv):
    episode = argv[1] if len(argv) > 1 else "E02"
    mode = argv[2] if len(argv) > 2 else "SONG"
    private = "--private-test" in argv
    brief = compile_brief(episode, mode, private_test=private)
    out = Path("out") / episode / "brief.json"
    out.write_text(json.dumps(brief, indent=2), encoding="utf-8")

    t = brief["timeline"]
    print(f"  {episode} / {mode}")
    print(f"    song      {brief['song']['clip_id']}  first word at "
          f"song_t {brief['song']['first_word_song_t']}s")
    print(f"    master    {t['signature_s']}s signature + {t['programme_s']}s programme "
          f"+ {t['outro_s']}s outro = {t['master_total_s']}s")
    print(f"    beats     {len(brief['beats'])}, "
          f"{len(brief['paid']['still_ids'])} paid stills, "
          f"{len(brief['paid']['generative_beats'])} generative")
    print(f"    loudness  {brief['audio']['programme_lufs']} "
          f"({brief['audio']['programme_lufs_basis']})"
          f"{'' if brief['audio']['public_release_allowed'] else '  PRIVATE ONLY'}")
    print(f"  -> {out}")
    if brief["problems"]:
        print("  PROBLEMS")
        for p in brief["problems"]:
            print(f"    {p}")
    return 0 if brief["ready"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
