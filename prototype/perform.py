"""v2: the characters carry the shot, with no camera to rescue them. Rs 0.

GPT's verdict on v1 was precise: consistency PASS, world PASS, multi-character PASS,
"proper animation" NOT YET — the camera and the stars were doing the moving while three
rigid assets stood in a room. So this version:

  * holds the camera COMPLETELY STILL for the first five seconds. If the frame feels alive
    it is because the characters made it so.
  * gives each character a head that turns, tilts and lags a quarter-cycle behind its own
    breathing, which is the difference between a nodding object and a creature.
  * gives them separate reasons to move at separate moments — Pip looks up at the window on
    "stars", Nana turns toward Coco after it, Coco settles.
  * fixes the staging GPT flagged: Coco was half-swallowed by the bed, Nana dominated it,
    Pip was marooned bottom-left.

NO BLINK. I built two — a painted lid and a fur-pull — and both read as damage rather than
as an eye closing. A convincing blink needs an eyelid POSE, which we do not own and which
would cost Rs 5 to buy. Two failures is enough; chasing a third is exactly the instinct we
agreed to distrust.
"""
import math, subprocess, sys, tempfile, shutil
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layers import (PLATE, TRACK, foreground, grade, keyed, scaled, shadow_for,
                    stars_layer, ROOT)
from rig import RIGS, articulate

WINDOW = (32.0, 40.0)
STAR_EVENTS = [(0.0, 5), (36.01, 4), (37.19, 3), (37.90, 2)]

# staging, rewritten. Coco sits up in bed with his whole torso clear of the rail; Nana
# stands beside the bed rather than in it; Pip is close enough to be part of the group.
CAST = {
    "pip":  {"asset": "pip_view0", "h": 196, "cx": 520, "feet": 742, "period": 2.9,
             "look_at": [(33.4, -6.0), (36.2, 0.0)]},
    "nana": {"asset": "nana", "h": 268, "cx": 812, "feet": 706, "period": 4.3,
             "look_at": [(34.6, 5.0), (37.2, -3.0)]},
    "coco": {"asset": "coco", "h": 206, "cx": 1108, "feet": 590, "period": 3.4,
             "look_at": [(35.0, -4.0), (38.2, 2.0)]},
}
BEHIND = ("nana", "coco")


def stars_at(t):
    n = 5
    for at, c in STAR_EVENTS:
        if t >= at:
            n = c
    return n


def look_angle(spec, t):
    """A head that turns to look at something, and eases rather than snaps."""
    ang = 0.0
    for at, target in spec:
        if t >= at:
            k = min(1.0, (t - at) / 0.55)
            e = k * k * (3 - 2 * k)          # smoothstep: no snap, no float
            ang = ang + (target - ang) * e
    return ang


def frame_at(plate, fg, t):
    scene = plate.convert("RGBA")
    for name in ("pip", "nana", "coco"):
        c = CAST[name]
        layer = grade(scaled(keyed(c["asset"]), c["h"]))
        layer = articulate(layer, RIGS[c["asset"]], t, c["period"],
                           head_amp=2.4, bob_px=2.2,
                           look=look_angle(c["look_at"], t))
        x = int(c["cx"] - layer.width / 2)
        y = int(c["feet"] - layer.height)
        scene = Image.alpha_composite(
            scene, shadow_for(c["cx"], c["feet"], layer.width, scene.size))
        tmp = Image.new("RGBA", scene.size, (0, 0, 0, 0))
        tmp.paste(layer, (x, y), layer)
        scene = Image.alpha_composite(scene, tmp)
        if name in BEHIND:
            scene = Image.alpha_composite(scene, fg)
    u = (t - WINDOW[0]) / (WINDOW[1] - WINDOW[0])
    scene = Image.alpha_composite(scene, stars_layer(scene.size, stars_at(t), u,
                                                     WINDOW[1] - WINDOW[0]))
    return scene.convert("RGB")


def render(out_path, fps=24, w=1280, h=720):
    plate = Image.open(PLATE).convert("RGB")
    fg = foreground(plate)
    t0, t1 = WINDOW
    n = int(round((t1 - t0) * fps))
    tmp = Path(tempfile.mkdtemp())
    W, H = plate.size
    try:
        for i in range(n):
            t = t0 + i / fps
            f = frame_at(plate, fg, t)
            # camera: LOCKED for five seconds, then the smallest drift in, so the last
            # three seconds do not feel like a freeze
            held = 5.0
            k = 0.0 if (t - t0) < held else ((t - t0) - held) / max(0.001, (t1 - t0) - held)
            z = 1.16 + 0.02 * (k * k * (3 - 2 * k))
            cw, ch = W / z, H / z
            cx = min(max(0.47 * W, cw / 2), W - cw / 2)
            cy = min(max(0.55 * H, ch / 2), H - ch / 2)
            f = f.crop((int(cx - cw / 2), int(cy - ch / 2),
                        int(cx + cw / 2), int(cy + ch / 2))).resize((w, h), Image.LANCZOS)
            f.save(tmp / f"{i:05d}.png")
        silent = tmp / "p.mp4"
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
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cut/perform.mp4")
    render(out)
    print("done", out)
