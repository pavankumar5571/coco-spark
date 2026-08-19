"""Character bible for the 3-shot proof. Identity anchors — concrete, immutable, no mood."""

STYLE_LOCK = ("Bright 3D preschool animation, soft rounded shapes, warm saturated colours, "
              "gentle even lighting, simple friendly character design.")

CAST = {
    "coco": (
        "A small young bear cub with soft warm golden-brown fur, a lighter cream-coloured "
        "muzzle and belly patch, small rounded ears, large friendly dark-brown eyes, a small "
        "black nose, and short rounded limbs. Toddler proportions, large head relative to body. "
        "Wearing a bright red short-sleeved t-shirt with a small yellow star on the chest."
    ),
    "nana": (
        "A gentle elderly owl with soft pale-grey and white feathers, a heart-shaped facial "
        "disc, large calm amber eyes, and small round spectacles resting on her beak. Rounded, "
        "unthreatening silhouette. Wearing a soft lavender knitted shawl."
    ),
}

LOCATION = (
    "A cosy one-room cottage interior at night: honey-coloured wooden walls, a round window "
    "showing a deep blue starry sky, a small bed with a patchwork quilt, a small wooden chair "
    "beside the bed, a woven rug on the floor, a low bookshelf. Warm low lamp light."
)

# Fixed screen geography. Every frame must respect this or the room reads as mirrored.
GEOGRAPHY = (
    "FIXED ROOM LAYOUT, identical in every shot: the round window is on the LEFT wall. "
    "The low bookshelf is on the FAR LEFT. The bed stands against the RIGHT wall with its "
    "headboard toward the BACK-RIGHT corner, so a character lying in it has their head on "
    "the RIGHT and feet toward the LEFT. The wooden chair sits beside the bed on its LEFT "
    "side. The woven rug covers the floor in the centre. Never mirror or flip this layout."
)

# 3 shots. BEDTIME_STORY: static camera, minimal motion, calm.
SHOTS = [
    {
        "id": "s01",
        "cast": ["coco"],
        "frame": ("Wide shot, static camera at eye level. Coco the Bear sits upright in bed under "
                  "the patchwork quilt on the right of frame, looking toward the round window on "
                  "the left. The starry night sky is visible through the window."),
        "motion": "Coco blinks slowly and turns his head to look toward the window.",
        "camera": "Locked static camera. No camera movement.",
    },
    {
        "id": "s02",
        "cast": ["coco", "nana"],
        "frame": ("Medium shot, static camera. Nana Willow perches on the wooden chair beside the "
                  "bed on the left of frame, facing right toward Coco, who sits up in bed on the "
                  "right. Both are calm and settled. The round window glows behind them."),
        "motion": "Nana Willow gently tilts her head toward Coco. Coco looks up at her.",
        "camera": "Locked static camera. No camera movement.",
    },
    {
        "id": "s03",
        "cast": ["coco"],
        "frame": ("Close shot, static camera, same side of the room as the previous shots. Coco "
                  "the Bear lies down with his head on the pillow at the RIGHT end of the bed, "
                  "eyes closed, the patchwork quilt pulled up to his chin. The round window "
                  "remains on the left. Warm lamp light falls softly across his face."),
        "motion": "Coco settles his head into the pillow and breathes slowly, fast asleep.",
        "camera": "Locked static camera. Very slight slow push in.",
    },
]
