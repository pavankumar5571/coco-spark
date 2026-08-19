"""Performance, not just presence. Rs 0.

GPT's verdict on v1: consistency PASS, multi-character PASS, world stability PASS,
"proper animation" NOT YET — the camera and the stars were doing the work while the
characters sat there. So this version takes the camera away for most of the shot and makes
the characters carry it.

Not a skeleton, not IK, not segmentation. Three hand-defined regions per character — head,
eyes, and where the neck bends — which is the least rigging that can produce a performance
and the most we should build before Pavan has judged whether it is worth anything.
"""
import math
from PIL import Image, ImageDraw, ImageFilter

# per character: where the head ends, the pivot it turns about, and the eyes to close.
# Measured off the keyed portraits by eye, once. Fractions of the asset, so they survive
# any scale we place the character at.
RIGS = {
    "coco": {
        "head_split": 0.40,          # everything above this is head
        "pivot": (0.50, 0.42),       # the neck
        "eyes": [(0.37, 0.22), (0.61, 0.22)],
        "eye_r": (0.052, 0.038),
        "lid_from": (0.50, 0.14),    # sample fur colour here to paint the lid
    },
    "pip_view0": {
        "head_split": 0.52,
        "pivot": (0.50, 0.50),
        "eyes": [(0.385, 0.212), (0.615, 0.212)],
        "eye_r": (0.050, 0.036),
        "lid_from": (0.50, 0.13),
    },
    "pip_view1": {
        "head_split": 0.52, "pivot": (0.50, 0.50),
        "eyes": [(0.40, 0.215), (0.63, 0.215)],
        "eye_r": (0.048, 0.035), "lid_from": (0.50, 0.13),
    },
    "nana": {
        "head_split": 0.46,
        "pivot": (0.50, 0.48),
        "eyes": [],                  # behind glasses; a painted lid would read as damage
        "eye_r": (0.0, 0.0),
        "lid_from": (0.50, 0.10),
    },
}


def blink_curve(t, period, dur=0.13, offset=0.0):
    """0 = open, 1 = shut. Blinks are FAST and irregular; a metronome blink is a doll."""
    ph = (t + offset) % period
    if ph > dur:
        return 0.0
    x = ph / dur
    return math.sin(math.pi * x) ** 0.6


def apply_blink(layer, rig, amount, full_size=None):
    """Blink by pulling the fur DOWN over the eye, not by painting a lid on it.

    A flat colour sampled from the forehead reads as damage — I tried it, and the bear
    looked like someone had put two orange stickers on his face. Real eyelids are the same
    skin as the brow, with the same shading, so the honest version takes the strip of fur
    directly above the eye and stretches it down across the socket.
    """
    if amount <= 0.02 or not rig["eyes"]:
        return layer
    W, H = full_size or layer.size
    src = layer.convert("RGBA")
    out = src.copy()
    rx, ry = rig["eye_r"][0] * W, rig["eye_r"][1] * H
    for ex, ey in rig["eyes"]:
        cx, cy = ex * W, ey * H
        top = cy - ry * 1.25
        lid_h = max(1, int(2 * ry * 1.25 * amount))
        brow = src.crop((int(cx - rx * 1.25), int(max(0, top - ry * 1.6)),
                         int(cx + rx * 1.25), int(top)))
        if brow.width < 2 or brow.height < 2:
            continue
        lid = brow.resize((brow.width, lid_h), Image.LANCZOS)
        # feather the bottom edge so the lid does not end in a hard line
        mask = Image.new("L", lid.size, 255)
        md = ImageDraw.Draw(mask)
        for i in range(max(1, lid_h // 5)):
            md.line([(0, lid_h - 1 - i), (lid.width, lid_h - 1 - i)],
                    fill=int(255 * (i / max(1, lid_h // 5))))
        lid.putalpha(Image.composite(lid.split()[3], Image.new("L", lid.size, 0), mask)
                     if lid.mode == "RGBA" else mask)
        out.paste(lid, (int(cx - rx * 1.25), int(top)), lid)
    return out


def articulate(layer, rig, t, period, head_amp=2.2, bob_px=2.0, blink_period=None,
               blink_offset=0.0, look=0.0):
    """Body breathes; head turns, tilts and lags behind it; eyes blink.

    The lag is the part that matters. A head that moves in lockstep with the chest is one
    rigid object nodding. A head a quarter-cycle behind its own body is a creature.
    """
    w, h = layer.size
    split = int(h * rig["head_split"])
    body = layer.crop((0, split, w, h))
    head = layer.crop((0, 0, w, min(h, split + int(h * 0.06))))   # overlap hides the seam

    ph = 2 * math.pi * t / period
    sy = 1.0 + 0.016 * math.sin(ph)
    body = body.resize((w, max(1, int(body.height * sy))), Image.LANCZOS)

    lag = ph - math.pi / 2
    ang = head_amp * math.sin(lag * 0.55) + look
    dx = bob_px * math.sin(lag * 0.5)
    dy = bob_px * 0.6 * math.sin(lag)

    if blink_period:
        head = apply_blink(head, rig, blink_curve(t, blink_period, offset=blink_offset),
                           full_size=(w, h))

    pad = int(max(head.width, head.height) * 0.35)
    big = Image.new("RGBA", (head.width + pad * 2, head.height + pad * 2), (0, 0, 0, 0))
    big.paste(head, (pad, pad))
    px, py = rig["pivot"]
    big = big.rotate(ang, resample=Image.BICUBIC,
                     center=(pad + px * w, pad + py * h))

    out_h = split + body.height
    out = Image.new("RGBA", (w, out_h + pad), (0, 0, 0, 0))
    out.paste(body, (0, split), body)
    tmp = Image.new("RGBA", out.size, (0, 0, 0, 0))
    tmp.paste(big, (int(-pad + dx), int(-pad + dy)), big)
    out = Image.alpha_composite(out, tmp)
    return out.crop((0, 0, w, out_h))
