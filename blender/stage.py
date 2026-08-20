"""Build E02's deterministic 3D bedtime stage.

Run headless:

    blender -b -P blender/stage.py -- --out out/E02/stage

The .blend is an output. Geometry, names, anchors, deformation controls, lighting and
camera are authored here so the stage can be rebuilt and checked without clicking.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path.cwd()
FPS = 24


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    value = argv[argv.index("--out") + 1] if "--out" in argv else "out/E02/stage"
    return Path(value).resolve() if os.path.isabs(value) else (ROOT / value).resolve()


def material(name, color, metallic=0.0, roughness=0.55, emission=None):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1.0)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 3.0
    return m


def finish(obj, name, mat, bevel=0.08):
    obj.name = name
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("soft_edges", "BEVEL")
        mod.width, mod.segments = bevel, 4
    return obj


def cube(name, loc, scale, mat, bevel=0.08):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(o, name, mat, bevel)


def empty(name, loc):
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = "SPHERE"
    o.empty_display_size = 0.08
    o.location = loc
    bpy.context.collection.objects.link(o)
    return o


def star_mesh(name, loc, radius, depth, mat):
    verts = []
    for z in (-depth / 2, depth / 2):
        for i in range(10):
            a = math.radians(90 + i * 36)
            r = radius if i % 2 == 0 else radius * 0.43
            verts.append((r * math.cos(a), 0.0, r * math.sin(a) + z * 0.0))
    # Give the star real depth along Y, the window's viewing axis.
    verts = [(x, -depth / 2 if i < 10 else depth / 2, z) for i, (x, _, z) in enumerate(verts)]
    faces = [tuple(range(9, -1, -1)), tuple(range(10, 20))]
    for i in range(10):
        j = (i + 1) % 10
        faces.append((i, j, 10 + j, 10 + i))
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    o.location = loc
    mesh.materials.append(mat)
    bpy.context.collection.objects.link(o)
    return o


def blanket(mat):
    cols, rows = 16, 18
    width, length = 2.65, 2.85
    verts, faces = [], []
    for y in range(rows):
        for x in range(cols):
            px = -width / 2 + width * x / (cols - 1)
            py = -0.65 + length * y / (rows - 1)
            verts.append((px, py, 1.02))
    for y in range(rows - 1):
        for x in range(cols - 1):
            a = y * cols + x
            faces.append((a, a + 1, a + 1 + cols, a + cols))
    mesh = bpy.data.meshes.new("blanket_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new("blanket", mesh)
    bpy.context.collection.objects.link(o)
    mesh.materials.append(mat)
    solid = o.modifiers.new("blanket_thickness", "SOLIDIFY")
    solid.thickness = 0.035
    sub = o.modifiers.new("blanket_smooth", "SUBSURF")
    sub.levels = sub.render_levels = 2
    o.shape_key_add(name="Basis")
    key = o.shape_key_add(name="SLEEP_DRAPE")
    for i, point in enumerate(key.data):
        x, y, _ = verts[i]
        body = math.exp(-((x / 0.58) ** 2 + ((y - 0.42) / 0.92) ** 2))
        point.co.z += 0.38 * body
    key.value = 1.0
    return o


def pillow(mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=(0, 1.12, 1.12))
    o = bpy.context.object
    o.scale = (0.78, 0.43, 0.18)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    finish(o, "pillow", mat, 0)
    o.shape_key_add(name="Basis")
    key = o.shape_key_add(name="HEAD_CONTACT")
    for point in key.data:
        x, y, z = point.co
        influence = math.exp(-((x / 0.42) ** 2 + ((y + 0.02) / 0.27) ** 2))
        point.co.z -= 0.075 * influence
    key.value = 1.0
    return o


def build_stage():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    wood = material("warm_wood", (0.28, 0.105, 0.045), roughness=0.68)
    quilt = material("night_quilt", (0.12, 0.27, 0.52), roughness=0.8)
    linen = material("pillow_linen", (0.88, 0.82, 0.67), roughness=0.9)
    wall = material("honey_wall", (0.42, 0.21, 0.08), roughness=0.9)
    glass = material("night_glass", (0.025, 0.055, 0.13), roughness=0.25)
    gold = material("star_glow", (1.0, 0.65, 0.12), roughness=0.35,
                    emission=(1.0, 0.38, 0.04))

    cube("floor", (0, 0, -0.13), (3.8, 3.3, 0.13), wood, 0.03)
    cube("back_wall", (0, 2.65, 2.25), (3.8, 0.10, 2.38), wall, 0.02)
    cube("bed_frame", (0, 0.42, 0.54), (1.62, 1.85, 0.28), wood, 0.12)
    cube("mattress", (0, 0.35, 0.88), (1.48, 1.70, 0.18), linen, 0.13)
    cube("headboard", (0, 2.05, 1.38), (1.68, 0.14, 0.78), wood, 0.12)
    pillow(linen)
    blanket(quilt)

    # Round window: dark glass disc plus wooden frame, vertical in the back wall.
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.78, depth=0.035,
                                        location=(0, 2.51, 2.72), rotation=(math.pi / 2, 0, 0))
    finish(bpy.context.object, "round_window_glass", glass, 0)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.79, minor_radius=0.075,
                                    major_segments=64, minor_segments=12,
                                    location=(0, 2.46, 2.72), rotation=(math.pi / 2, 0, 0))
    finish(bpy.context.object, "round_window_frame", wood, 0)

    star_positions = [(-0.40, 2.39, 2.98), (-0.18, 2.38, 2.58),
                      (0.04, 2.37, 3.12), (0.27, 2.38, 2.76), (0.43, 2.39, 3.00)]
    stars = [star_mesh(f"star_{i + 1}", pos, 0.12, 0.035, gold)
             for i, pos in enumerate(star_positions)]

    bed_origin = Vector((0.0, 0.18, 1.04))
    anchors = {
        "character_origin": empty("ANCHOR_character_origin", (0, 0.18, 0.0)),
        "bed_surface": empty("ANCHOR_bed_surface", bed_origin),
        "sleep_head": empty("ANCHOR_sleep_head", bed_origin + Vector((0.0, 0.14, 0.12))),
        "sleep_hips": empty("ANCHOR_sleep_hips", bed_origin + Vector((0.0, -0.06, 0.10))),
        "sleep_feet": empty("ANCHOR_sleep_feet", bed_origin + Vector((0.0, -0.20, 0.05))),
        "window_focus": empty("ANCHOR_window_focus", (0, 2.42, 2.72)),
    }

    # Camera rig is a parented system so animation changes the rig, not lens semantics.
    rig = empty("camera_rig", (0, 0.35, 1.35))
    cam_data = bpy.data.cameras.new("camera")
    cam_data.lens = 48
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = (0, -7.4, 2.45)
    cam.rotation_euler = (math.radians(76), 0, 0)
    bpy.context.collection.objects.link(cam)
    cam.parent = rig
    bpy.context.scene.camera = cam

    for name, loc, energy, size, color in [
        ("key_moon", (-2.6, -2.4, 4.8), 850, 4.0, (0.66, 0.78, 1.0)),
        ("fill_warm", (2.7, -1.3, 2.8), 520, 3.5, (1.0, 0.62, 0.32)),
        ("window_rim", (0, 2.1, 3.2), 400, 2.0, (0.52, 0.68, 1.0)),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.shape, data.size, data.color = energy, "DISK", size, color
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        obj.rotation_euler = (math.radians(22 if loc[1] > 0 else 62), 0,
                              math.atan2(loc[1], loc[0]) + math.pi / 2)
        bpy.context.collection.objects.link(obj)

    world = bpy.data.worlds.new("starlight_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.018, 0.025, 0.06, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    bpy.context.scene.world = world
    return stars, anchors


def configure(out):
    s = bpy.context.scene
    s.render.engine = "BLENDER_EEVEE"
    s.render.resolution_x, s.render.resolution_y = 960, 540
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = "PNG"
    s.render.film_transparent = False
    s.render.fps = FPS
    s.frame_start, s.frame_end = 1, 1829
    s.render.filepath = str(out / "stage_preview.png")


def main():
    out = args()
    out.mkdir(parents=True, exist_ok=True)
    stars, anchors = build_stage()
    configure(out)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "starlight_bedroom_stage_v1.blend"))
    bpy.ops.render.render(write_still=True)
    required = ["bed_frame", "pillow", "blanket", "round_window_glass",
                "round_window_frame", "camera_rig", "camera"] + [s.name for s in stars]
    missing = [name for name in required if bpy.data.objects.get(name) is None]
    report = {
        "kind": "BLENDER_STAGE_MANIFEST",
        "location_id": "starlight_bedroom_stage_v1",
        "fps": FPS,
        "blend": "starlight_bedroom_stage_v1.blend",
        "preview": "stage_preview.png",
        "required_objects": required,
        "missing_objects": missing,
        "stars": [{"name": s.name, "independently_addressable": True} for s in stars],
        "deformation_controls": {"pillow": "HEAD_CONTACT", "blanket": "SLEEP_DRAPE"},
        "anchors": {name: [round(v, 4) for v in obj.location] for name, obj in anchors.items()},
        "contract": {
            "one_blender_unit_m": 1.0,
            "ground_z": 0.0,
            "bed_surface_z": 1.04,
            "character_standing_height_m": 0.55,
            "character_origin_local": [0.0, 0.0, 0.0],
            "character_foot_plane_local_z": 0.0,
            "character_facing": "+Y",
            "sleep_pose_side": "right",
            "sleep_pose_local": {
                "head_centre": [0.0, 0.14, 0.12],
                "hips_centre": [0.0, -0.06, 0.10],
                "feet_contact": [0.0, -0.20, 0.05],
            },
        },
    }
    (out / "stage_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if missing:
        raise SystemExit("missing required stage objects: " + ", ".join(missing))
    print("  E02 STAGE PASS")
    print(f"    objects {len(required)}, stars {len(stars)}, anchors {len(anchors)}")
    print("    deformation pillow.HEAD_CONTACT blanket.SLEEP_DRAPE")
    print(f"    -> {out}")


if __name__ == "__main__":
    main()
