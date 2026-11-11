#!/usr/bin/env python3
"""Build the 70-template runtime library from approved PNGs and public annotations.

Offline and deterministic. Python 3 and Pillow are required. No generation API,
previous reference library, private mapping, or photo collection is used.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

from PIL import Image

COUNT = 70
ROLES = ("outline", "skin_base", "skin_shadow", "background", "hair", "clothing", "cheek", "detail")
GARMENT_ROLES = ("clothing", "clothing_inner", "clothing_shadow", "clothing_trim", "clothing_pattern", "accessory", "headwear")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgb_hex(rgb):
    return "#" + "".join(f"{v:02X}" for v in rgb[:3])


def source_image(source_dir, i):
    for name in (f"avatar-{i:03d}.png", f"{i:03d}.png"):
        path = source_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"Missing approved PNG {i:03d} in {source_dir}")


def verify_sample(im, sample, context):
    x, y = sample["xy"]
    assert 0 <= x < im.width and 0 <= y < im.height, context
    actual = rgb_hex(im.getpixel((x, y)))
    assert actual == sample["hex"], f"{context}: {actual} != {sample['hex']}"


def color_family(value):
    import colorsys
    r, g, b = bytes.fromhex(value[1:])
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if s < .2 or v < .13:
        return "neutral-ink"
    return ("red-coral", "brown-ochre", "yellow-olive", "green-teal", "blue-cyan", "violet", "magenta-plum")[min(6, int(h * 7))]


def clean_generic(value):
    """Retain current drawing instructions without obsolete catalog identities."""
    if isinstance(value, dict):
        return {k: clean_generic(v) for k, v in value.items() if k not in ("technique_reference_ids", "reference_ids")}
    if isinstance(value, list):
        return [clean_generic(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"HD[- ]?\d{1,3}", "所选模板", value)
        value = value.replace("69张原图", "70张模板").replace("69张", "70张").replace("原作", "模板")
    return value


def migrate_cases(old, manifest):
    cases = []
    by_id = {x["id"]: x for x in manifest["templates"]}
    for case in old.get("cases", []):
        i = int(case["avatar_id"])
        current = by_id[i]
        c = {k: clean_generic(copy.deepcopy(case[k])) for k in ("avatar_id", "title", "status", "evidence", "learning_scope", "not_authoritative_for") if k in case}
        if i == 57:
            c["evidence"] = "用户确认重新设计后要求保存至Figma，沉淀为后续使用的当前头像模板。"
        c.update(template_id=current["label"], image=current["image"], sha256=current["sha256"], reference_size=[1000, 1000])
        cases.append(c)
    for i, title, scope in (
        (3, "照片结构与简化表达", ["人物身份特征与衣物的关键层次服从照片，线条和色面遵守当前通用规范。"]),
        (7, "男性露齿笑的简化嘴型", ["保留照片中露齿笑的关键表情；唇形克制，不把男生画成夸张厚唇，不逐颗描牙。"]),
    ):
        if any(int(x["avatar_id"]) == i for x in cases):
            continue
        t = by_id[i]
        cases.append({"avatar_id": f"{i:03d}", "template_id": t["label"], "title": title, "status": "user_confirmed", "evidence": "用户确认新图并要求替换Figma中的对应成品。", "image": t["image"], "sha256": t["sha256"], "reference_size": [1000, 1000], "learning_scope": scope, "not_authoritative_for": ["不复制人物、衣服或配色到其他照片。"]})
    cases.sort(key=lambda x: int(x["avatar_id"]))
    return {
        "schema_version": 1,
        "policy_id": "confirmed-avatar-corrections-v6",
        "purpose": "当前批准模板中可复核的局部修订经验；learning_scope界定每个案例可迁移的规则。",
        "reference_count": len(cases),
        "numbering": {"avatar_id": "当前批准模板001–070", "template_id": "TS-001–TS-070"},
        "default_attachment": "none; inspect relevant examples only when needed",
        "authority": "learning_scope only; current explicit user requirements and general style rules still apply",
        "source_manifest_sha256": hashlib.sha256((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(),
        "cases": cases,
    }


def build(args):
    root = args.skill_dir.resolve()
    refs = root / "references"
    annotations = read(args.annotations)
    templates = annotations["templates"]
    assert annotations["count"] == COUNT
    assert [x["id"] for x in templates] == list(range(1, COUNT + 1))
    old_line = read(refs / "line-library.json")
    old_cases = read(refs / "confirmed-cases.json")
    # Generic rules and curated learning scopes are owned by the Skill, not by
    # the template source. A rebuild retains them without source-image history.
    line = {
        "schema_version": 1,
        "title": "70套批准头像的线条设计与核心线色库",
        "source_catalog": "references/finished-reference-library.json",
        "count": COUNT,
        "missing_numeric_ids": [],
        "basis": "线色HEX与坐标来自当前1000×1000批准模板；角色和画法分类是本Skill的编辑标注。",
        "measurement_boundary": "采样证明成品栅格中此处存在此RGB，不声称恢复源工程色板、笔刷或独立图层。",
        "generation_policy": "主轮廓、五官、发内结构和衣饰结构统一使用所选模板primary_hex；通用减线规则优先于成品中更密的细节。",
        "role_rules": clean_generic(old_line["role_rules"]),
        "width_policy": clean_generic(old_line["width_policy"]),
        "families": clean_generic(old_line["families"]),
        "portraits": [],
    }
    for family in line["families"]:
        family["reference_ids"] = list(range(1, COUNT + 1)) if family["id"] == "rounded-monoline" else []
        if family["id"] == "offset-accent":
            family["classification_note"] = "可选的通用局部强调技法；当前70套统一使用圆润单线主类，不单独启用辅助线色。"
            family["technique_reference_ids"] = []
    role_library = {
        "schema_version": 1, "policy_id": "source-role-colors-v1", "source_count": COUNT,
        "missing_numeric_ids": [],
        "method": "从每张当前批准1000×1000 PNG读取标注坐标的精确RGB；角色标签为编辑元数据，缺失角色显式披露同模板回退。",
        "background_policy": "单一不透明纯色背景；模板中观测到的背景渐变仅作档案，新图使用已记录的纯色采样。",
        "skin_policy": "肤面与暗面跟随同一当前模板；没有可靠可见暗面时复用肤面基色，不虚构新肤色。",
        "sources": [], "skins": [], "backgrounds": [],
    }
    color_library = {
        "schema_version": 1, "policy_id": "single-source-colorways-v1", "source_library_count": COUNT,
        "scope": "70套当前批准新头像各自构成独立色板；所有可执行HEX、像素坐标与哈希均指向本包对应模板。",
        "example_reference_ids": [3, 4, 9, 25, 52, 57, 70],
        "gradient_policy_id": "visible-source-gradients-v2",
        "archived_colorway_count": COUNT, "eligible_colorway_count": COUNT, "colorways": [],
    }
    garment_library = {
        "policy_id": "source-garment-layers-v1", "source_count": COUNT,
        "coordinate_system": "Current approved 1000×1000 template pixels, top-left origin",
        "scope": "Observed garment colors and explicit same-template role fallbacks; photo controls clothing geometry.",
        "garments": [],
    }
    finished = {
        "schema_version": 1, "source": "approved-tanshui-template-library", "count": COUNT,
        "missing_numeric_ids": [], "default_reference_id": 25,
        "normalization": "Exact approved 1000×1000 RGB PNG files copied without resampling or recoloring.",
        "portraits": [],
    }
    manifest = {
        "schema_version": 1, "count": COUNT, "source": "approved-tanshui-templates",
        "numbering": "Current independent template sequence TS-001 through TS-070",
        "templates": [],
    }
    colorways_dir = refs / "colorways"
    colorways_dir.mkdir(parents=True, exist_ok=True)
    for stale in colorways_dir.glob("*.json"):
        stale.unlink()
    sample_count = gradient_count = 0
    for t in templates:
        i, label = t["id"], t["label"]
        source = source_image(args.source_dir, i)
        assert digest(source) == t["sha256"], f"Template hash mismatch: {label}"
        with Image.open(source) as image:
            assert image.size == (1000, 1000) and image.mode == "RGB", label
            im = image.copy()
        for group in (t["role_samples"], t["garment_samples"]):
            for role, sample in group.items():
                verify_sample(im, sample, f"{label}/{role}")
                sample_count += 1
        for g in t["gradients"]:
            assert g["region"] in ("hair", "clothing")
            assert sum((a-b)**2 for a,b in zip(bytes.fromhex(g["from"][1:]), bytes.fromhex(g["to"][1:]))) >= 24**2
            assert sum(n > 20 for n in g["observed_ramp_bins"]) >= 8
            for end in ("from", "to"):
                verify_sample(im, g["samples"][end], f"{label}/gradient/{end}")
                assert g["samples"][end]["hex"] == g[end]
                sample_count += 1
            gradient_count += 1
        target = root / t["image"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        assert digest(target) == t["sha256"]
        m = {k: copy.deepcopy(t[k]) for k in ("id", "label", "image", "sha256", "size", "name")}
        manifest["templates"].append(m)
        s = t["role_samples"]
        roles = {r: s[r]["hex"] for r in ROLES}
        gopts = [{k: copy.deepcopy(g[k]) for k in ("region", "from", "to", "direction", "samples")} for g in t["gradients"]]
        main_grad = {k: copy.deepcopy(gopts[0][k]) for k in ("region", "from", "to", "direction")} if gopts else None
        samples = copy.deepcopy(s)
        if gopts:
            samples["gradient_from"] = copy.deepcopy(gopts[0]["samples"]["from"])
            samples["gradient_to"] = copy.deepcopy(gopts[0]["samples"]["to"])
        bg = {"id": f"{label}-bg-1", **copy.deepcopy(s["background"]), "usage": "solid_fill"}
        colorway = {
            "id": f"{label}-colorway", "source_hd_id": i, "source_template_id": label,
            "name": t["name"], "source_image": t["image"], "source_sha256": t["sha256"],
            "skin_template_id": f"{label}-skin", "background_template_id": bg["id"],
            "roles": roles, "samples": samples, "gradient": main_grad, "gradient_options": gopts,
            "role_presence": {r: copy.deepcopy(t.get("role_presence", {}).get(r, {"present": True})) for r in ROLES},
            "image_size": [1000, 1000], "coordinate_system": t["coordinate_system"],
            "background_samples": [bg], "additional_skin_samples": [],
            "generation_eligibility": {"eligible": True, "reasons": [], "policy": "all-70-approved-template-palettes-v1", "archive_complete": True},
            "gradient_observation": "Only actually sampled, sufficiently populated continuous hair/clothing ramps are executable. Absence means no observed executable ramp.",
        }
        if "background_observation" in t:
            colorway["background_observation"] = copy.deepcopy(t["background_observation"])
        color_library["colorways"].append(colorway)
        write(colorways_dir / f"{label}-colorway.json", colorway)
        role_library["sources"].append({"source_hd_id": i, "source_template_id": label, "source_image": t["image"], "source_sha256": t["sha256"], "image_size": [1000, 1000]})
        role_library["skins"].append({"id": f"{label}-skin", "source_hd_id": i, "base": copy.deepcopy(s["skin_base"]), "shadow": copy.deepcopy(s["skin_shadow"]), "additional_skin_samples": []})
        role_library["backgrounds"].append({"source_hd_id": i, **bg})
        line["portraits"].append({
            "id": i, "label": label, "primary_hex": roles["outline"], "primary_sample_xy": s["outline"]["xy"],
            "line_family": "rounded-monoline", "reference_image": t["image"], "sha256": t["sha256"],
            "role_notes": {"contour": "连续平顺外轮廓，遮挡边界有序连接。", "face": "眉眼及鼻口用同色清楚符号，表情服从人物照片。", "hair": "完整发型剪影优先；当前减线预算优先于成品内部细节。", "clothing": "领口、衣片、袖口和必要折线用疏线区分，不画大片阴影块。"},
            "technique_notes": "从当前模板提取统一线色；照片决定人物、衣服和动作。", "secondary_colors": [], "confidence": "measured", "color_family": color_family(roles["outline"]),
        })
        gs = {r: {**copy.deepcopy(t["garment_samples"][r]), "semantic_role": r} for r in GARMENT_ROLES}
        garment_library["garments"].append({
            "source_hd_id": i, "source_template_id": label, "source_image": t["image"], "source_sha256": t["sha256"],
            "image_size": [1000, 1000], "structure": t["garment_structure"], "observation": t["name"],
            "samples": gs, "role_mapping": {r: r for r in GARMENT_ROLES}, "render_roles": {r: gs[r]["hex"] for r in GARMENT_ROLES},
            "gradients": [g for g in gopts if g["region"] == "clothing"], "observed_inner": t["observed_inner"], "observed_pattern": t["observed_pattern"], "motifs": t["motifs"],
            "role_presence": copy.deepcopy(t["garment_role_presence"]),
            "fallback_disclosure": t["role_fallback_policy"] + " clothing_shadow is structure ink for thin fold lines only, never a filled cast-shadow patch.",
            "geometry_rule": "Photo controls outfit layers, collar, cuffs, folds, patterns and accessories; do not copy the template costume.",
        })
        frequent = sorted(im.getcolors(im.width * im.height), reverse=True)[:12]
        finished["portraits"].append({
            "id": i, "label": label, "source_filename": f"{i:03d}.png", "source_size": [1000, 1000], "source_sha256": t["sha256"],
            "reference_image": t["image"], "size": [1000, 1000], "sha256": t["sha256"], "technique": "gradient" if gopts else "flat",
            "shape_cues": t["shape_cues"], "layer_cues": t["name"], "most_frequent_colors": [{"hex": rgb_hex(c), "pixels": n} for n, c in frequent], "color_roles": roles,
        })
    role_library.update(
        unique_skin_base_count=len({x["base"]["hex"] for x in role_library["skins"]}),
        unique_skin_color_count=len({x[r]["hex"] for x in role_library["skins"] for r in ("base", "shadow")}),
        unique_background_color_count=len({x["hex"] for x in role_library["backgrounds"]}),
    )
    for name, data in (("template-manifest.json", manifest), ("source-colorways.json", color_library), ("source-role-colors.json", role_library), ("line-library.json", line), ("garment-library.json", garment_library), ("finished-reference-library.json", finished), ("confirmed-cases.json", migrate_cases(old_cases, manifest)), ("template-annotations.json", annotations)):
        write(refs / name, data)
    report = {"templates": COUNT, "pixel_samples_verified": sample_count, "observed_executable_gradients": gradient_count, "hashes_verified": COUNT, "image_size": [1000, 1000], "image_mode": "RGB"}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir", required=True, type=Path)
    p.add_argument("--skill-dir", required=True, type=Path)
    p.add_argument("--annotations", default=Path(__file__).resolve().parents[1] / "references/template-annotations.json", type=Path)
    build(p.parse_args())
