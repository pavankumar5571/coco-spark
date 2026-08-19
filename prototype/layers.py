"""Deterministic multi-character animation over a fixed world. Rs 0, no generator.

The claim under test, and it is a strong one: if a character is COMPOSITED from the same
accepted pixels every frame, identity drift is not unlikely, it is IMPOSSIBLE. Consistency
becomes a checksum rather than a judgement.

What this prototype must prove, per GPT's brutal list: three canonical characters in one
canonical room, independent micro-motion, a star count that changes exactly on the sung
word, at least one character passing BEHIND furniture, and a real cut — because two
compositions of the same scene is the thing a viewer actually experiences, and careful
staging of a single tableau could hide the sticker problem.
"""
import math, os, subprocess, sys, tempfile, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
CUT = Path("/tmp/cut")
PLATE = ROOT / "out/location_plates/cottage_night/attempts/002/plate.png"
STAR_BOX = (230, 55, 615, 435)
SPOTS = [(0.26, 0.26), (0.71, 0.24), (0.25, 0.69), (0.72, 0.70), (0.40, 0.13)]
# the bed, traced by hand from the plate. One mask, derived once, so a character can pass
# BEHIND it — without an occlusion the demo could be hiding the problem it claims to solve.
# only the bed's FRONT structure — rail, footboard, quilt front — so a character beside
# it is occluded from the knees down rather than swallowed whole. The first version hid
# Nana almost completely, which proves ordering and shows nothing.
BED_POLY = [(838, 545), (1360, 500), (1364, 706), (1120, 720), (840, 664)]


def keyed(name):
    return Image.open(CUT / f"{name}.png").convert("RGBA")


def grade(layer, warm=(1.06, 0.99, 0.86), dim=0.72):
    """Make a character lit on white belong in a warm lamplit room. Arithmetic, not taste."""
    r, g, b, a = layer.split()
    r = r.point(lambda v: min(255, int(v * warm[0] * dim)))
    g = g.point(lambda v: min(255, int(v * warm[1] * dim)))
    b = b.point(lambda v: min(255, int(v * warm[2] * dim)))
    return Image.merge("RGBA", (r, g, b, a))


def scaled(layer, target_h):
    s = target_h / layer.height
    return layer.resize((max(1, int(layer.width * s)), target_h), Image.LANCZOS)


def shadow_for(cx, feet_y, width, size):
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    rx, ry = width * 0.42, width * 0.12
    d.ellipse([cx - rx, feet_y - ry * 0.8, cx + rx, feet_y + ry * 0.8], fill=(18, 8, 0, 120))
    return sh.filter(ImageFilter.GaussianBlur(10))


def stars_layer(size, count, u, seconds):
    x0, y0, x1, y1 = STAR_BOX
    bw, bh = x1 - x0, y1 - y0
    base = max(4, int(min(bw, bh) * 0.040))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, (fx, fy) in enumerate(SPOTS[:count]):
        tw = 0.78 + 0.22 * math.sin(2 * math.pi * (u * seconds / (2.6 + i * 0.7) + i * 0.37))
        cx, cy = x0 + fx * bw, y0 + fy * bh
        r = base * tw
        for k, a in ((2.4, int(22 * tw)), (1.5, int(44 * tw))):
            d.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k],
                      fill=(255, 246, 200, max(0, a)))
        pts = []
        for j in range(10):
            ang = math.pi / 2 + j * math.pi / 5
            rad = r if j % 2 == 0 else r * 0.40
            pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
        d.polygon(pts, fill=(255, 252, 232, 255))
    return layer


def breathe(layer, t, period, depth=0.018, sway_deg=0.7):
    """Breathing is a vertical squash about the FEET, not a scale about the centre — a
    character that grows out of the floor is a balloon, not a bear. The sway is a degree
    either side, which is under conscious notice and over the threshold of feeling alive."""
    ph = 2 * math.pi * t / period
    sy = 1.0 + depth * math.sin(ph)
    sx = 1.0 - depth * 0.35 * math.sin(ph)
    w = max(1, int(layer.width * sx))
    h = max(1, int(layer.height * sy))
    out = layer.resize((w, h), Image.LANCZOS)
    ang = sway_deg * math.sin(ph * 0.5)
    if abs(ang) > 0.01:
        big = Image.new("RGBA", (int(w * 1.35), int(h * 1.35)), (0, 0, 0, 0))
        big.paste(out, ((big.width - w) // 2, big.height - h))
        out = big.rotate(ang, resample=Image.BICUBIC, center=(big.width // 2, big.height))
    return out


def foreground(plate):
    """The bed, cut from the plate as a foreground layer. Derived ONCE, by hand, for this
    experiment — not a scene graph, not a depth system. Enough to prove ordering."""
    mask = Image.new("L", plate.size, 0)
    ImageDraw.Draw(mask).polygon(BED_POLY, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    fg = plate.convert("RGBA")
    fg.putalpha(mask)
    return fg


CAST = {
    # name          height  centre  feet   breath period   depth
    "pip":  {"asset": "pip_view0", "h": 168, "cx": 300,  "feet": 726, "period": 2.9},
    "nana": {"asset": "nana",      "h": 292, "cx": 880,  "feet": 700, "period": 4.1},
    "coco": {"asset": "coco",      "h": 214, "cx": 1120, "feet": 596, "period": 3.4},
}


def compose(plate, fg, t, seconds, u, stars, shot, cast=None):
    scene = plate.convert("RGBA")
    cast = cast or CAST
    behind = [k for k in ("nana", "coco") if k in cast]   # both stand behind the bed front
    infront = [k for k in cast if k not in behind]
    for group, over_fg in ((behind, False), (infront, False)):
        for name in group:
            c = cast[name]
            layer = grade(scaled(keyed(c["asset"]), c["h"]))
            layer = breathe(layer, t, c["period"])
            x = int(c["cx"] - layer.width / 2)
            y = int(c["feet"] - layer.height)
            scene = Image.alpha_composite(
                scene, shadow_for(c["cx"], c["feet"], layer.width, scene.size))
            tmp = Image.new("RGBA", scene.size, (0, 0, 0, 0))
            tmp.paste(layer, (x, y), layer)
            scene = Image.alpha_composite(scene, tmp)
            if name in behind:
                scene = Image.alpha_composite(scene, fg)   # the bed goes back on top
    scene = Image.alpha_composite(scene, stars_layer(scene.size, stars, u, seconds))
    return scene.convert("RGB")


# ── the prototype itself: two shots, one cut, real song, real word timings ──────────────
TRACK = ROOT / "out/E02/audio/bed.wav"
WINDOW = (32.0, 40.0)          # seconds of the trimmed track
CUT_AT = 36.01                 # "Four little stars" — the phrase boundary we cut on
STAR_EVENTS = [(0.0, 5), (36.01, 4), (37.19, 3), (37.90, 2)]   # exact sung word times


def stars_at(t_track):
    n = 5
    for at, c in STAR_EVENTS:
        if t_track >= at:
            n = c
    return n


def shot_crop(shot, u, size):
    """Per-frame camera. Shot A is the room; shot B is tighter on the window and the bed."""
    W, H = size
    if shot == "A":
        z = 1.0 + 0.035 * u                    # slow push in
        cx, cy = 0.52, 0.52
    else:
        z = 1.34 - 0.02 * u                    # tighter, easing back a touch
        cx, cy = 0.42, 0.55
    cw, ch = W / z, H / z
    x = min(max(cx * W, cw / 2), W - cw / 2)
    y = min(max(cy * H, ch / 2), H - ch / 2)
    return (int(x - cw / 2), int(y - ch / 2), int(x + cw / 2), int(y + ch / 2))


def render(out_path, fps=24, w=1280, h=720):
    plate = Image.open(PLATE).convert("RGB")
    fg = foreground(plate)
    t0, t1 = WINDOW
    tmp = Path(tempfile.mkdtemp())
    n = int(round((t1 - t0) * fps))
    try:
        for i in range(n):
            t_track = t0 + i / fps
            shot = "A" if t_track < CUT_AT else "B"
            # each shot has its own clock, so the camera restarts at the cut like a real one
            base = t0 if shot == "A" else CUT_AT
            span = (CUT_AT - t0) if shot == "A" else (t1 - CUT_AT)
            u = (t_track - base) / max(0.001, span)
            cast = dict(CAST)
            if shot == "B":
                cast.pop("coco", None)
                # PIP TURNS on the word "three" — two views from ONE paid generation, which
                # is the articulation-coherence question stated as cheaply as it can be
                cast["pip"] = {**CAST["pip"], "cx": 430, "feet": 726,
                               "asset": "pip_view1" if t_track >= 37.19 else "pip_view0"}
                cast["nana"] = {**CAST["nana"], "cx": 880}
            frame = compose(plate, fg, t_track, span, u, stars_at(t_track), shot, cast)
            frame = frame.crop(shot_crop(shot, u, frame.size)).resize((w, h), Image.LANCZOS)
            frame.save(tmp / f"{i:05d}.png")
        silent = tmp / "picture.mp4"
        subprocess.run(f'ffmpeg -nostdin -y -framerate {fps} -i "{tmp}/%05d.png" '
                       f'-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "{silent}"',
                       shell=True, capture_output=True)
        subprocess.run(f'ffmpeg -nostdin -y -i "{silent}" -ss {t0} -to {t1} -i "{TRACK}" '
                       f'-map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest '
                       f'"{out_path}"', shell=True, capture_output=True)
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cut/prototype.mp4")
    print("rendering", out)
    render(out)
    print("done")
