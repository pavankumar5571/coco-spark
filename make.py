#!/usr/bin/env python3
"""Minimal 3-shot episode. Four stages, each stopping for human review.

    python make.py portraits   canonical identity anchors      ~2 images
    python make.py frames      first frames, refs = portraits  ~3 images
    python make.py video       clips from APPROVED frames only ~3 x 4s
    python make.py assemble    ffmpeg concat

Nothing past `frames` runs until you approve. Spend is tracked against BUDGET_INR and
the script refuses to exceed it.

Design rules carried over from the frozen contract:
  - every provider parameter explicit, no adapter defaults
  - identity anchors first, temporal reference after them
  - the previous accepted frame tells the model what CHANGED;
    canonical portraits tell it what must NOT change
  - no audio direction in the video prompt (audio is a separate spine)
"""
import io, json, os, sys, time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

import config as C
from cast import CAST, GEOGRAPHY, LOCATION, SHOTS, STYLE_LOCK

ROOT = Path(__file__).parent
OUT = ROOT / "out"
LEDGER = OUT / "ledger.json"
for d in ("portraits", "frames", "approved", "clips"):
    (OUT / d).mkdir(parents=True, exist_ok=True)


def client():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not set")
    return genai.Client(api_key=key)


def ledger():
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {"spent_inr": 0.0, "ops": []}


def charge(kind, detail, inr):
    L = ledger()
    if L["spent_inr"] + inr > C.BUDGET_INR:
        sys.exit(f"BUDGET STOP: {L['spent_inr']:.2f} + {inr:.2f} exceeds {C.BUDGET_INR}")
    L["spent_inr"] += inr
    L["ops"].append({"kind": kind, "detail": detail, "inr": inr, "at": time.strftime("%F %T")})
    LEDGER.write_text(json.dumps(L, indent=2))
    print(f"    spent {inr:.2f}  running total {L['spent_inr']:.2f} / {C.BUDGET_INR}")


def gen_image(cl, prompt, refs, dest: Path):
    parts = [Image.open(p) for p in refs] + [prompt]
    resp = cl.models.generate_content(
        model=C.IMAGE_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=C.IMAGE_ASPECT),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None):
            dest.write_bytes(part.inline_data.data)
            im = Image.open(dest)
            print(f"    -> {dest.name}  {im.size[0]}x{im.size[1]}")
            return dest
    raise RuntimeError(f"no image returned for {dest.name}")


def stage_portraits():
    cl = client()
    for name, desc in CAST.items():
        dest = OUT / "portraits" / f"{name}.png"
        if dest.exists():
            print(f"  {name}: exists, skipping"); continue
        print(f"  {name}: generating canonical portrait")
        prompt = (f"{STYLE_LOCK}\n\nFull-body character reference sheet on a plain white "
                  f"background. Front view, neutral standing pose, neutral expression, even "
                  f"lighting, no shadows, no props, no scenery.\n\nCHARACTER: {desc}")
        gen_image(cl, prompt, [], dest)
        charge("image", f"portrait:{name}", C.INR_PER_IMAGE)
    print("\nREVIEW out/portraits/ — these are the identity anchors for everything after.")


def stage_frames():
    cl = client()
    prev = None
    for shot in SHOTS:
        dest = OUT / "frames" / f"{shot['id']}.png"
        if dest.exists():
            print(f"  {shot['id']}: exists, skipping"); prev = dest; continue

        refs, legend = [], []
        for i, who in enumerate(shot["cast"]):                    # identity anchors FIRST
            p = OUT / "portraits" / f"{who}.png"
            if not p.exists():
                sys.exit(f"missing portrait {p} — run `make.py portraits` first")
            refs.append(p); legend.append(f"Image {len(refs)-1}: canonical reference for {who}")
        if prev:                                                   # temporal reference AFTER
            refs.append(prev)
            legend.append(f"Image {len(refs)-1}: the previous accepted shot, for continuity "
                          f"of set dressing, lighting and layout")

        prompt = (
            "\n".join(legend) + "\n\n"
            + f"{STYLE_LOCK}\n\n"
            + f"LOCATION (must be the identical room in every shot): {LOCATION}\n\n"
            + f"{GEOGRAPHY}\n\n"
            + f"SHOT: {shot['frame']}\n\n"
            + "The characters must match their canonical reference images exactly: same fur "
              "and feather colour, same clothing, same proportions, same face. "
            + ("Keep the room, furniture layout and lighting identical to the previous shot; "
               "only the framing and character positions change." if prev else "")
            + "\nOnly the characters named above are present. No text or lettering."
        )
        print(f"  {shot['id']}: generating first frame ({len(refs)} refs)")
        gen_image(cl, prompt, refs, dest)
        charge("image", f"frame:{shot['id']}", C.INR_PER_IMAGE)
        prev = dest

    print("\nREVIEW out/frames/. Copy the GOOD ones into out/approved/ (same filename).")
    print("Only approved frames are sent to video. Nothing else spends money.")


def stage_video():
    cl = client()
    approved = sorted((OUT / "approved").glob("*.png"))
    if not approved:
        sys.exit("out/approved/ is empty — copy the frames you accept into it first")
    print(f"  {len(approved)} approved frame(s); {C.VIDEO_MODEL} "
          f"{C.VIDEO_RES} {C.VIDEO_SECONDS}s")

    for frame in approved:
        shot = next((s for s in SHOTS if s["id"] == frame.stem), None)
        if not shot:
            print(f"  {frame.stem}: no shot definition, skipping"); continue
        dest = OUT / "clips" / f"{frame.stem}.mp4"
        if dest.exists():
            print(f"  {frame.stem}: clip exists, skipping"); continue

        # NO audio direction here — audio is a separate spine.
        prompt = f"ACTION: {shot['motion']}\nCAMERA: {shot['camera']}\nSTYLE: {STYLE_LOCK}"
        print(f"  {frame.stem}: generating clip")
        op = cl.models.generate_videos(
            model=C.VIDEO_MODEL,
            prompt=prompt,
            image=types.Image.from_file(location=str(frame)),
            config=types.GenerateVideosConfig(
                resolution=C.VIDEO_RES,
                aspect_ratio=C.VIDEO_ASPECT,
                duration_seconds=C.VIDEO_SECONDS,
            ),
        )
        while not op.done:
            time.sleep(5); op = cl.operations.get(op)
        if op.error:
            print(f"    FAILED: {op.error}"); continue
        vid = op.response.generated_videos[0]
        cl.files.download(file=vid.video)
        dest.write_bytes(vid.video.video_bytes)
        print(f"    -> {dest.name}")
        charge("video", f"clip:{frame.stem}", C.INR_PER_VID_SEC * C.VIDEO_SECONDS)

    print("\nREVIEW out/clips/. Then: python make.py assemble")


def stage_assemble():
    clips = sorted((OUT / "clips").glob("*.mp4"))
    if not clips:
        sys.exit("no clips in out/clips/")
    lst = OUT / "concat.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = OUT / "episode.mp4"
    rc = os.system(f'ffmpeg -y -f concat -safe 0 -i "{lst}" -c copy "{final}" 2>/dev/null')
    if rc != 0:
        sys.exit("ffmpeg failed or is not installed (brew install ffmpeg)")
    print(f"  -> {final}")


if __name__ == "__main__":
    stages = {"portraits": stage_portraits, "frames": stage_frames,
              "video": stage_video, "assemble": stage_assemble}
    if len(sys.argv) < 2 or sys.argv[1] not in stages:
        sys.exit(f"usage: make.py [{'|'.join(stages)}]")
    L = ledger()
    print(f"stage: {sys.argv[1]}   spent so far: Rs {L['spent_inr']:.2f} / {C.BUDGET_INR}\n")
    stages[sys.argv[1]]()
