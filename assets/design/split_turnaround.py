"""Split an approved turnaround sheet into the four reference views the modeller reads.

    python assets/design/split_turnaround.py assets/design/coco/coco-bandana-turnaround-v2.png coco

ONE SCALE FACTOR, NOT FOUR. The previous manifest normalised every view to the same
content height — 901px on a 1024 canvas. That is wrong the moment a view's silhouette is
legitimately taller than another's: in Coco's profile the ear stands proud of the crown,
so his content is 636px against the front's 628. Normalising each view to a common content
height would have quietly shrunk the profile's BODY by 1.3% to make its EAR agree with the
front's, and a modeller building to those planes would have produced a bear whose depth is
smaller than his width by a percent nobody could see and nobody could explain.

So every view is scaled by the SAME factor, derived from the front, and the profile is
allowed to be taller. Relative proportion survives; only absolute size is normalised.

Feet are aligned on one baseline rather than centred, because the ground is the thing all
four views actually share.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

CANVAS = 1024
TARGET_H = 901          # the front view's content height, in canvas pixels
VIEWS = ["front", "three_quarter", "side", "back"]


def panels(im):
    """Split on fully transparent columns. The sheet must carry real alpha."""
    a = im.split()[-1]
    px = a.load()
    w, h = im.size
    cols = [any(px[x, y] > 12 for y in range(0, h, 2)) for x in range(w)]
    runs, start = [], None
    for x, filled in enumerate(cols):
        if filled and start is None:
            start = x
        elif not filled and start is not None:
            if x - start > 40:
                runs.append((start, x - 1))
            start = None
    if start is not None and w - start > 40:
        runs.append((start, w - 1))
    return runs


def content_box(im, x0, x1):
    a = im.split()[-1]
    px = a.load()
    h = im.size[1]
    ys = [y for y in range(h) if any(px[x, y] > 12 for x in range(x0, x1 + 1, 2))]
    return x0, ys[0], x1, ys[-1]


def main():
    if len(sys.argv) < 3:
        sys.exit("  usage: split_turnaround.py <sheet.png> <character>")
    sheet, character = Path(sys.argv[1]), sys.argv[2]
    im = Image.open(sheet).convert("RGBA")
    if im.split()[-1].getextrema()[0] != 0:
        sys.exit("  sheet has no transparent pixels — the background is painted in, not keyed")

    runs = panels(im)
    if len(runs) != len(VIEWS):
        sys.exit(f"  found {len(runs)} panels, expected {len(VIEWS)}")

    boxes = [content_box(im, x0, x1) for x0, x1 in runs]
    ref_h = boxes[0][3] - boxes[0][1] + 1               # the FRONT view sets the scale
    scale = TARGET_H / ref_h
    baseline = max(b[3] for b in boxes)                 # deepest feet across the sheet

    out_dir = Path("assets") / "design" / character
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"character": character, "canvas": CANVAS, "background": "transparent",
                "source_sheet": str(sheet).replace("\\", "/"),
                "source_sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
                "scale_normalised_on": "ONE factor from the front view; views keep their "
                                       "true relative heights",
                "views": {}}

    for name, (x0, y0, x1, y1) in zip(VIEWS, boxes):
        crop = im.crop((x0, y0, x1 + 1, y1 + 1))
        w = max(1, int(round(crop.width * scale)))
        h = max(1, int(round(crop.height * scale)))
        crop = crop.resize((w, h), Image.LANCZOS)

        canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        # feet land on a common line so the four planes share a ground in Blender
        foot_y = int(round((baseline - y0) * scale))
        top = CANVAS - 60 - foot_y
        canvas.paste(crop, ((CANVAS - w) // 2, top), crop)

        path = out_dir / f"{character}_{name}.png"
        canvas.save(path)
        manifest["views"][name] = {
            "path": str(path).replace("\\", "/"),
            "source_content_h": y1 - y0 + 1,
            "scaled_content_h": h,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
        }
        print(f"  {name:14s} {y1-y0+1:4d}px -> {h:4d}px   {path}")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  scale factor {scale:.5f} from the front view; profile keeps its taller ear")
    print(f"  -> {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
