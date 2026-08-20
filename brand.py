"""Channel brand assets, drawn DETERMINISTICALLY.

A logo is the one thing in this pipeline that must be pixel-identical in every episode,
forever. Generating it would mean asking a stochastic model to reproduce a mark exactly —
the same request that produced a russet bear when we asked for a honey one. So the mark is
COMPUTED: same inputs, same bytes, every time, verifiable by hash.

That is our own rule applied where it fits best: generation where variation is desirable,
references where identity must persist, deterministic computation where correctness must
be guaranteed. A brand mark is the third case.

Nothing here costs money and nothing here can drift.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_VERSION = "1"
NAME = "COCO SPARK"
SUB = "TV"

# Coco's own palette, so the mark belongs to the character rather than sitting beside him.
STAR = (255, 199, 44)          # the yellow star on his shirt
SHIRT = (214, 51, 45)          # his red
CREAM = (255, 246, 227)
NIGHT = (26, 35, 66)

ROUNDED = "/System/Library/Fonts/SFNSRounded.ttf"
FALLBACK = "/System/Library/Fonts/Supplemental/Avenir Next.ttc"


def _font(size, bold=True):
    for p in (ROUNDED, FALLBACK):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def star_points(cx, cy, r_out, r_in, points=5, rot=-math.pi / 2):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / points
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_star(d, cx, cy, r, fill=STAR, outline=None, width=0):
    d.polygon(star_points(cx, cy, r, r * 0.46), fill=fill,
              outline=outline, width=width)


def wordmark(height=200, on_dark=True):
    """The name lockup. TV sits on its own baseline beside SPARK, not under COCO.

    v1 put TV under the C of COCO and it read as a collision rather than a lockup, and a
    translucent halo behind the star rendered as a flat grey disc on a dark field. Both
    are gone: the star carries its own soft outline instead of a backing plate.
    """
    H = height
    pad = int(H * 0.10)
    f_name = _font(int(H * 0.52))
    f_sub = _font(int(H * 0.22))
    tmp = Image.new("RGBA", (10, 10)); td = ImageDraw.Draw(tmp)
    nb = td.textbbox((0, 0), NAME, font=f_name)
    sb = td.textbbox((0, 0), SUB, font=f_sub)
    star_r = H * 0.26
    gap = int(H * 0.09)
    W = int(pad + star_r * 2 + gap + (nb[2] - nb[0]) + gap * 0.5 + (sb[2] - sb[0]) + pad)

    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = pad + star_r, H / 2

    # the star reads on any background because it carries its own dark rim, not a plate
    draw_star(d, cx, cy, star_r * 1.10, fill=(0, 0, 0, 90))
    draw_star(d, cx, cy, star_r)

    text_col = CREAM if on_dark else NIGHT
    x = cx + star_r + gap
    ty = cy - (nb[3] - nb[1]) / 2 - nb[1]
    d.text((x, ty), NAME, font=f_name, fill=(*text_col, 255))
    # TV sits on the SAME baseline, to the right, so it completes the name
    x2 = x + (nb[2] - nb[0]) + gap * 0.5
    base = ty + (nb[3] - nb[1]) - (sb[3] - sb[1])
    d.text((x2, base), SUB, font=f_sub, fill=(*STAR, 255))
    return im


def _coco_bust(px=420):
    """Coco's head and shoulders, cut from the CANONICAL portrait. Not generated.

    Cut by ALPHA, not by a guessed rectangle. v1 sliced a fixed box out of the portrait
    and clipped the tops of his ears flat, which read as homemade the moment it was seen
    at real size. Remove the white field from the whole figure first, find where the
    figure actually is, then take the top of THAT.
    """
    src = Path("out/portraits/coco.png")
    if not src.exists():
        return None
    im = Image.open(src).convert("RGBA")
    # White field -> transparent with a SOFT ramp. A binary threshold leaves the
    # anti-aliased rim of the figure at full opacity while it is still mostly white, which
    # paints a pale halo around him on any dark background — visible immediately at real
    # size. Ramp the alpha across the transition instead, then pull the edge in slightly
    # so no white pixels survive at the boundary.
    from PIL import ImageFilter
    g = im.convert("L")
    lo, hi = 226, 248
    a = g.point(lambda v: 255 if v <= lo else (0 if v >= hi else int(255 * (hi - v) / (hi - lo))))
    a = a.filter(ImageFilter.MinFilter(3))          # erode 1px: kill the residual rim
    im.putalpha(a)
    bb = im.split()[3].getbbox()
    if not bb:
        return None
    fig = im.crop(bb)                       # the whole bear, tightly
    # head and shoulders is the upper 46% of the figure; nothing is clipped because the
    # box is derived from where he IS rather than from where we assumed he was
    bust = fig.crop((0, 0, fig.width, int(fig.height * 0.46)))
    bb2 = bust.split()[3].getbbox()
    if bb2:
        bust = bust.crop(bb2)
    k = px / bust.height
    return bust.resize((max(1, int(bust.width * k)), px), Image.LANCZOS)


def primary_logo(height=520, on_dark=True):
    """Channel artwork, opening signature, end card, thumbnail badge.

    Coco supplies personality; deterministic construction supplies identity. The character
    is canonical pixels and everything around him is computed, so the whole mark still
    hashes stably.
    """
    bust = _coco_bust(int(height * 0.62))
    mark = wordmark(height=int(height * 0.30), on_dark=on_dark)
    W = max(mark.width, (bust.width if bust else 0) + 40) + 60
    im = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    if bust:
        im.alpha_composite(bust, ((W - bust.width) // 2, 0))
    im.alpha_composite(mark, ((W - mark.width) // 2, height - mark.height - 8))
    return im


def micro_mark(height=64):
    """The PERSISTENT watermark. A different job from the primary logo, so a different asset.

    Deliberately not the wordmark shrunk down: large persistent text over every frame of a
    preschool programme competes with the picture, and a bright star parked on the image
    can become part of the scene in a small child's perception. Star plus CS, restrained.
    """
    H = height
    f = _font(int(H * 0.52))
    tmp = Image.new("RGBA", (10, 10)); td = ImageDraw.Draw(tmp)
    tb = td.textbbox((0, 0), "CS", font=f)
    r = H * 0.30
    W = int(r * 2 + H * 0.16 + (tb[2] - tb[0]) + H * 0.12)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = r + 2, H / 2
    draw_star(d, cx, cy, r * 1.12, fill=(0, 0, 0, 110))
    draw_star(d, cx, cy, r)
    d.text((cx + r + H * 0.14, cy - (tb[3] - tb[1]) / 2 - tb[1]), "CS", font=f,
           fill=(255, 255, 255, 235))
    return im


def watermark(video_w, video_h, opacity=0.42, scale=0.055, margin=0.028, corner="br"):
    """A corner mark for every frame of every episode.

    It makes a re-upload identifiable and traceable. It does NOT prevent copying, and
    implying otherwise would be selling a guarantee no overlay can give. Content ID is
    what actually enforces.
    """
    h = max(20, int(video_h * scale))
    m = micro_mark(height=h)
    m.putalpha(m.split()[3].point(lambda v: int(v * opacity)))
    mx, my = int(video_w * margin), int(video_h * margin)
    x = mx if corner in ("tl", "bl") else video_w - m.width - mx
    y = my if corner in ("tl", "tr") else video_h - m.height - my
    return m, x, y
