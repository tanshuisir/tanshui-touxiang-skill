#!/usr/bin/env python3
"""Decode one technical color master and render one or four local color variants.

The RGB cube colors below encode roles, not deliverable artwork colors. This
module never draws or calls a model: one role map and one black-line alpha map
are reused by every variant. Ambiguous or ordinary colored artwork is rejected.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageDraw
import garment_plan
import semantic_encoding
import object_plan
from style_language import validate_role_map, validate_cheek_edge_specks




ENCODING = {
    'line': '#000000', 'background': '#FFFFFF',
    'skin_base': '#FF0000', 'skin_shadow': '#00FF00',
    'hair': '#FFFF00', 'clothing': '#00FFFF',
    'accent': '#FF00FF', 'detail': '#0000FF',
}
_IDS = {'line': 0, 'background': 7, 'skin_base': 4, 'skin_shadow': 2,
        'hair': 6, 'clothing': 3, 'accent': 5, 'detail': 1,
        'clothing_inner':8,'clothing_shadow':9,'clothing_trim':10,
        'clothing_pattern':11,'accessory':12,'headwear':13}
_IDS.update({role: semantic_encoding.PROP_IDS[role] for role in object_plan.ROLES})
_HEX = re.compile(r'#[0-9A-Fa-f]{6}')


def _rgb(value):
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError('配色必须为 #RRGGBB')
    return tuple(bytes.fromhex(value[1:]))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _count(mask):
    return sum(value * count for value, count in enumerate(mask.histogram())) / 255


def _mask(ids, role):
    return ids.point([255 if value == _IDS[role] else 0 for value in range(256)])


def _validate_frame_corners(ids,line_alpha):
    """Empty top corners; lower corners may contain a connected cropped coat."""
    width,height=ids.size
    corner=max(1,round(min(ids.size)*.01))
    boxes=((0,0,corner,corner),(width-corner,0,width,corner),
           (0,height-corner,corner,height),(width-corner,height-corner,width,height))
    for box in boxes[:2]:
        if ids.crop(box).getextrema()!=(7,7) or line_alpha.crop(box).getextrema()!=(0,0):
            raise ValueError('技术底稿顶部四角检查失败：必须为纯背景，不能残留细节或其他角色')
    clothes={_IDS[r] for r in garment_plan.GARMENT_ROLES}
    body=ids.point([255 if v in clothes else 0 for v in range(256)])
    support=ImageChops.lighter(body,line_alpha.point([255 if v>=64 else 0 for v in range(256)]))
    connected=None
    for box in boxes[2:]:
        labels=ids.crop(box);alpha=line_alpha.crop(box)
        if labels.getextrema()==(7,7) and alpha.getextrema()==(0,0):continue
        if any(v not in clothes|{0,7} for v in labels.tobytes()):
            raise ValueError('技术底稿底角不是背景或连续衣服，四角角色校验失败')
        if connected is None:
            seeds=[x for x,v in enumerate(body.crop((0,height-1,width,height)).tobytes()) if v]
            if not seeds:raise ValueError('技术底稿底角衣服未连续连接到底缘')
            flooded=support.copy()
            ImageDraw.floodfill(flooded,(min(seeds,key=lambda x:abs(x-width/2)),height-1),128)
            connected=flooded.point([255 if v==128 else 0 for v in range(256)])
        fg=ImageChops.lighter(body.crop(box),alpha.point([255 if v>=64 else 0 for v in range(256)]))
        # A cropped coat outline may reach the corner just before its fill.
        # Connection to the bottom garment seed is the evidence; requiring
        # garment fill inside this tiny corner wrongly rejects that outline.
        if ImageChops.subtract(fg,connected.crop(box)).getbbox():
            raise ValueError('技术底稿底角并非连续衣片，不把零散编码当成背景')


def _decode_garments(master_path, *, encoding=semantic_encoding.ENCODING_ID):
    image,ids,alpha,manifest=semantic_encoding.decode(master_path,encoding=encoding)
    pixels=image.width*image.height
    counts=manifest['role_pixel_counts']
    if not .0002<=manifest['line_core_fraction']<=.4:
        raise ValueError('技术底稿没有可靠黑线或暗面过多')
    if any(counts[r]<max(4,pixels*.001) for r in ('background','skin_base')):
        raise ValueError('技术底稿缺少背景或肤面角色')
    _validate_frame_corners(ids,alpha)
    manifest['background_corners_validated']=True
    manifest['corner_validation_policy']='empty-top-connected-garment-bottom-v2'
    visible=alpha.point([255 if v==0 else 0 for v in range(256)])
    visible_counts={role:_count(ImageChops.multiply(_mask(ids,role),visible).filter(ImageFilter.MinFilter(3))) for role in garment_plan.GARMENT_ROLES}
    if visible_counts['clothing']<max(4,pixels*.001):raise ValueError('底稿缺少主衣片，服饰分区不可靠')
    manifest['visible_garment_roles']=visible_counts
    return image,ids,alpha,manifest


def _decode(master_path):
    with Image.open(master_path) as source:
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('技术底稿必须是单帧图片')
        if 'A' in source.getbands() or 'transparency' in source.info:
            if source.convert('RGBA').getchannel('A').getextrema() != (255, 255):
                raise ValueError('技术底稿必须是不透明编码图，不能猜补透明区域')
        image = source.convert('RGB')
    red, green, blue = image.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    gaps = [ImageChops.darker(channel, ImageChops.subtract(maximum, channel))
            for channel in (red, green, blue)]
    gap = ImageChops.lighter(ImageChops.lighter(gaps[0], gaps[1]), gaps[2])
    tolerance = maximum.point([round(value * 0.12 + 4) for value in range(256)])
    invalid = ImageChops.subtract(gap, tolerance).point([0] + [255] * 255)
    pixels = image.width * image.height
    invalid_fraction = _count(invalid) / pixels
    if invalid_fraction > 0.03:
        raise ValueError(f'技术底稿编码不可靠：{invalid_fraction:.1%}像素偏离角色编码；不对普通上色头像猜分区')

    # A black line blended over a cube-corner fill has max(R,G,B)=255*(1-a).
    # Normalize role bits against the local maximum, then retain the same line
    # alpha separately. Tiny deviations from white/full channels are denoised.
    bits = []
    for channel, bit in zip((red, green, blue), (4, 2, 1)):
        positive = ImageChops.subtract(channel, ImageChops.subtract(maximum, channel))
        bits.append(positive.point([0] + [bit] * 255))
    ids = ImageChops.add(ImageChops.add(bits[0], bits[1]), bits[2])
    line_alpha = ImageOps.invert(maximum).point([
        0 if value <= 8 else 255 if value >= 247 else value for value in range(256)])
    # An antialiased red/green fill boundary can look like dark yellow. It is
    # neither hair nor a new black stroke. Only retain line alpha near actual
    # dark ink, and repair transient role labels from nearby stable fill cores.
    actual_ink = maximum.point([255 if value <= 96 else 0 for value in range(256)])
    line_alpha = ImageChops.multiply(line_alpha, actual_ink.filter(ImageFilter.MaxFilter(7)))
    bright = maximum.point([255 if value >= 224 else 0 for value in range(256)])
    small_gap = gap.point([255 if value <= 24 else 0 for value in range(256)])
    fill_core = ImageChops.multiply(bright, small_gap)
    neighbors = {}
    for role, role_id in _IDS.items():
        if role == 'line':
            continue
        core = ImageChops.multiply(_mask(ids, role), fill_core).filter(ImageFilter.MinFilter(3))
        neighbors[role_id] = core.filter(ImageFilter.MaxFilter(7)).tobytes()
    labels = bytearray(ids.tobytes())
    rgb_bytes = image.tobytes()
    corner_colors = {_IDS[role]: _rgb(color) for role, color in ENCODING.items() if role != 'line'}
    for index, role_id in enumerate(labels):
        if role_id == 0 or neighbors[role_id][index]:
            continue
        candidates = [candidate for candidate, nearby in neighbors.items() if nearby[index]]
        if candidates:
            pixel = rgb_bytes[index * 3:index * 3 + 3]
            labels[index] = min(candidates, key=lambda candidate:
                                sum((value - target) ** 2 for value, target in zip(pixel, corner_colors[candidate])))
    ids = Image.frombytes('L', image.size, bytes(labels))
    line_core = line_alpha.point([255 if value >= 160 else 0 for value in range(256)])
    line_fraction = _count(line_core) / pixels
    if not 0.0002 <= line_fraction <= 0.4:
        raise ValueError('技术底稿没有可靠黑色线条，或黑色暗面过多，不能锁定线稿')
    counts = {role: int(_count(_mask(ids, role))) for role in _IDS}
    for role in ('background', 'skin_base'):
        if counts[role] < max(4, pixels * 0.001):
            raise ValueError('技术底稿缺少可识别的' + role + '区域')
    # The retained bust framing leaves all four corners empty. Do not let a
    # valid detail/skin code masquerade as background and survive as white.
    _validate_frame_corners(ids,line_alpha)
    if max(counts['hair'], counts['clothing']) < max(4, pixels * 0.001):
        raise ValueError('技术底稿没有可见头发或衣服区域，无法放置必需的人物局部渐变')
    return image, ids, line_alpha, {
        'schema_version': 1, 'encoding': ENCODING, 'role_ids': _IDS,
        'source_sha256': _sha(master_path.read_bytes()),
        'role_map_sha256': _sha(ids.tobytes()), 'line_alpha_sha256': _sha(line_alpha.tobytes()),
        'role_pixel_counts': counts, 'unknown_fraction': round(invalid_fraction, 6),
        'line_core_fraction': round(line_fraction, 6),
        'background_corners_validated': True,
        'validation_scope': '编码可解码性与共用像素几何；不证明人物相似度或语义画对',
    }


def _align_subject_to_bottom(ids, line_alpha):
    """Translate the shared subject once, preserving its size and every role.

    Only low-opacity trailing AA fringe may leave the canvas. Material must
    reach the bottom over a substantial continuous span; a hair tip, loose
    line, or isolated point cannot masquerade as a torso touching the edge.
    """
    width, height = ids.size
    visible = line_alpha.point([255 if value < 224 else 0 for value in range(256)])
    fill = ids.point([0 if value in (0, _IDS['background']) else 255 for value in range(256)])
    meaningful = ImageChops.lighter(ImageChops.multiply(fill, visible),
                                    line_alpha.point([255 if value >= 64 else 0 for value in range(256)]))
    bbox = meaningful.getbbox()
    if bbox is None:
        raise ValueError('人物贴底失败：没有可靠人物区域')
    shift = height - bbox[3]
    if shift > round(height * 0.12):
        raise ValueError('人物贴底失败：底部空隙超过画高12%，不能过度移动人物或猜补身体')
    torso = ids.point([255 if value in tuple(_IDS[r] for r in garment_plan.GARMENT_ROLES)+(_IDS['skin_base'], _IDS['skin_shadow']) else 0
                       for value in range(256)])
    torso = ImageChops.multiply(torso, visible)
    # A cropped garment may end on its antialiased outline. Accept that edge
    # only when a wide torso span connects to it with no background row in
    # between; an isolated horizontal stroke below a bust is not sufficient.
    support = ImageChops.lighter(torso, line_alpha.point([
        255 if value >= 64 else 0 for value in range(256)]))
    connected = bytearray([255] * width)
    longest = 0
    contact_inset = None
    for inset in range(max(2, round(height * 0.025)) + 1):
        row_y = bbox[3] - 1 - inset
        if row_y < 0:
            break
        support_row = support.crop((0,row_y,width,row_y+1)).tobytes()
        torso_row = torso.crop((0,row_y,width,row_y+1)).tobytes()
        current = candidate = 0
        for index, (edge, material) in enumerate(zip(support_row, torso_row)):
            connected[index] &= edge
            current = current + 1 if connected[index] and material else 0
            candidate = max(candidate, current)
        if candidate >= max(4, round(width * 0.10)):
            longest, contact_inset = candidate, inset
            break
    if contact_inset is None:
        raise ValueError('人物贴底失败：底缘不是连续衣服或身体区域，不能用发梢、线条或零散像素冒充贴底')
    original_ids, original_alpha = ids, line_alpha
    if shift:
        ids = Image.new('L', ids.size, _IDS['background'])
        line_alpha = Image.new('L', line_alpha.size, 0)
        ids.paste(original_ids, (0, shift))
        line_alpha.paste(original_alpha, (0, shift))
    assert ids.crop((0,height-1,width,height)).tobytes() == original_ids.crop((0,bbox[3]-1,width,bbox[3])).tobytes()
    return ids, line_alpha, {
        'policy_id': 'shared-subject-bottom-anchor-v1',
        'offset_xy': [0, shift], 'source_subject_bbox': list(bbox),
        'bottom_gap_pixels': 0, 'bottom_torso_continuous_pixels': longest,
        'connected_bottom_outline_pixels': contact_inset,
        'minimum_torso_continuous_pixels': max(4, round(width * 0.10)),
        'translation_only': True, 'scale': 1, 'substantive_subject_preserved': True,
        'discarded_fringe': 'Only trailing line alpha below 64/255; no meaningful fill or ink cropped',
        'shared_across_variants': True,
    }


def _validate_plans(plans):
    # A source-verified RGB by itself is insufficient: every role must belong
    # to this same reference palette, including ink, cheeks and detail fill.
    from source_colorways import upgrade_gradient_plan
    if not isinstance(plans, list) or len(plans) not in (1, 4):
        raise ValueError('需要恰好一个或四个 variant_plans')
    if any(not isinstance(plan, dict) for plan in plans):
        raise ValueError('每个配色方案必须为对象')
    if any(not plan.get('source_colorway') for plan in plans):
        raise ValueError('必须使用带TS模板来源与哈希的完整配色计划；旧单图混色入口已停用')
    normalized = [upgrade_gradient_plan(plan) for plan in plans]
    if len(normalized) == 4 and len({plan['source_hd_id'] for plan in normalized}) != 4:
        raise ValueError('四配色必须对应四张不同模板，不能重复或拆拼色板')
    return normalized


def _gradient_axis(direction):
    text = str(direction)
    for first, second, vector in [('左上', '右下', (1, 1)), ('右上', '左下', (-1, 1))]:
        if first in text and second in text:
            sign = 1 if text.index(first) < text.index(second) else -1
            return tuple(value * sign for value in vector)
    if '左' in text and '右' in text:
        return (1 if text.index('左') < text.index('右') else -1, 0)
    if '上' in text and '下' in text:
        return (0, 1 if text.index('上') < text.index('下') else -1)
    return (0, 1)


def _gradient_domain(mask, gradient):
    """Anchor both colors inside the visible fill, never under ink/outliers."""
    dx, dy = _gradient_axis(gradient.get('direction', '从上到下'))
    width, height = mask.size
    if dx == 0:
        counts = {position * dy: mask.crop((0, position, width, position + 1)).histogram()[255]
                  for position in range(height)}
    elif dy == 0:
        counts = {position * dx: mask.crop((position, 0, position + 1, height)).histogram()[255]
                  for position in range(width)}
    else:
        counts = Counter((position % width) * dx + (position // width) * dy
                         for position, value in enumerate(mask.tobytes()) if value == 255)
    total = sum(counts.values())
    if total < 4:
        raise ValueError('人物渐变没有足够可见填色面积')
    def quantile(fraction):
        cumulative = 0
        for position, count in sorted(counts.items()):
            cumulative += count
            if cumulative >= total * fraction:
                return position
        return max(counts)
    start, end = quantile(0.05), quantile(0.95)
    if end - start < 7:
        raise ValueError('人物渐变可见主体跨度不足，不能用边缘像素冒充连续渐变')
    domain = {'start': start, 'end': end, 'vector': [dx, dy]}
    return domain, {'method': 'visible-fill-area-quantiles-v1',
                    'projection_vector': [dx, dy], 'area_quantiles': [0.05, 0.95],
                    'start': start, 'end': end, 'visible_fill_pixels': total}


def _gradient_image(size, bounds, gradient):
    width, height = size
    dx, dy = _gradient_axis(gradient.get('direction', '从上到下'))
    if isinstance(bounds, dict):
        start, end = bounds['start'], bounds['end']
    else:
        # Retain the old private helper's rectangle interface for callers;
        # normal rendering always supplies the visible-fill domain above.
        coordinates = [x * dx + y * dy for x in (bounds[0], bounds[2] - 1)
                       for y in (bounds[1], bounds[3] - 1)]
        start, end = min(coordinates), max(coordinates)
    extremes = [x * dx + y * dy for x in (0, width - 1) for y in (0, height - 1)]
    minimum, maximum = min(extremes), max(extremes)
    span = max(1, end - start)
    ramp = Image.new('L', (maximum - minimum + 1, 1))
    ramp.putdata([max(0, min(255, round(255 * (position - start) / span)))
                  for position in range(minimum, maximum + 1)])
    # Map image pixel centers to their exact signed projection coordinate.
    weights = ramp.transform(size, Image.Transform.AFFINE,
                             (dx, dy, -minimum + 0.5 - (dx + dy) * 0.5, 0, 0, 0),
                             resample=Image.Resampling.NEAREST)
    return Image.composite(Image.new('RGB', size, gradient['to']),
                           Image.new('RGB', size, gradient['from']), weights), weights


def _gradient_metrics(rendered, visible_fill, gradient, *, thumbnail=False):
    """Measure delivered RGB, so a varying weight map cannot pass flat paint."""
    sampled = rendered.convert('RGBA')
    sampled.putalpha(visible_fill)
    colors = [(count, color[:3]) for count, color in sampled.getcolors(rendered.width * rendered.height)
              if color[3] == 255]
    area = sum(count for count, _ in colors)
    start, end = _rgb(gradient['from']), _rgb(gradient['to'])
    delta = tuple(b - a for a, b in zip(start, end))
    contrast = math.dist(start, end)
    tolerance = max(4.0, contrast * 0.15) if thumbnail else max(3.0, contrast * 0.10)
    start_colors, end_colors = [], []
    transition_pixels = 0
    for count, color in colors:
        if math.dist(color, start) <= tolerance:
            start_colors.append((count, color))
        if math.dist(color, end) <= tolerance:
            end_colors.append((count, color))
        progress = sum((value - first) * change for value, first, change in zip(color, start, delta)) / max(1, contrast ** 2)
        if 0.15 <= progress <= 0.85:
            transition_pixels += count
    def pixels(items):
        return sum(count for count, _ in items)
    def mean(items):
        count = pixels(items)
        return tuple(sum(number * color[channel] for number, color in items) / count
                     for channel in range(3)) if count else None
    start_pixels, end_pixels = pixels(start_colors), pixels(end_colors)
    mean_start, mean_end = mean(start_colors), mean(end_colors)
    actual_contrast = math.dist(mean_start, mean_end) if mean_start and mean_end else 0.0
    fractions = {'from': start_pixels / max(1, area), 'to': end_pixels / max(1, area),
                 'transition': transition_pixels / max(1, area)}
    # A tiny patch may contain many interpolation levels without remaining
    # visible at avatar size. Reserve at least 1% of the native canvas for the
    # required gradient, and inspect actual downsampled RGB as well.
    required_area = max(12, rendered.width * rendered.height * 0.002) if thumbnail else max(4, rendered.width * rendered.height * 0.01)
    endpoint_fraction, transition_fraction = (0.04, 0.15) if thumbnail else (0.05, 0.20)
    checks = {'minimum_visible_area': area >= required_area,
              'both_source_colors_visible': min(start_pixels, end_pixels) >= (2 if thumbnail else 1) and fractions['from'] >= endpoint_fraction and fractions['to'] >= endpoint_fraction,
              'continuous_transition_area': fractions['transition'] >= transition_fraction and len(colors) >= 8,
              'delivered_color_span': actual_contrast >= contrast * (0.65 if thumbnail else 0.70)}
    thumbnail_metrics = None
    if not thumbnail:
        ratio = min(1.0, 128 / max(rendered.size))
        size = tuple(max(1, round(value * ratio)) for value in rendered.size)
        reduced = rendered.resize(size, Image.Resampling.LANCZOS)
        coverage = visible_fill.resize(size, Image.Resampling.BOX)
        # Only evaluate thumbnail pixels predominantly covered by the original
        # visible role interior; exclude ink/background boundary mixtures.
        reduced_mask = coverage.point([255 if value >= 224 else 0 for value in range(256)])
        thumbnail_metrics = _gradient_metrics(reduced, reduced_mask, gradient, thumbnail=True)
        checks['thumbnail_visibility'] = thumbnail_metrics['visible']
    visible = all(checks.values())
    result = {'policy_id': 'delivered-rgb-gradient-visibility-v1', 'visible_fill_pixels': area,
            'minimum_area_fraction': 0.002 if thumbnail else 0.01, 'evaluation_size': list(rendered.size),
            'source_rgb_distance': round(contrast, 3), 'delivered_rgb_distance': round(actual_contrast, 3),
            'endpoint_rgb_tolerance': round(tolerance, 3),
            'endpoint_pixels': {'from': start_pixels, 'to': end_pixels},
            'visible_area_fractions': {key: round(value, 6) for key, value in fractions.items()},
            'distinct_fill_colors': len(colors), 'checks': checks, 'visible': visible,
            'qualifies_as_required': visible and contrast >= 24,
            'scope': '最终RGB中无主线遮挡的角色内区；不以插值权重数量代替实际渐变'}
    if thumbnail_metrics is not None:
        result['thumbnail'] = thumbnail_metrics
    return result


def _save_png(image, destination):
    with destination.open('xb') as stream:
        image.save(stream, format='PNG')


def render_variants(master_path, plans, output_dir, *, encoding='semantic-cube-v1'):
    """Render one source-locked artwork or four variants and a 2×2 sheet."""
    started = perf_counter()
    master_path, output_dir = Path(master_path).resolve(), Path(output_dir).resolve()
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError('四配色输出目录非空，不能覆盖此前结果')
    plans = _validate_plans(plans)
    if encoding not in ('semantic-cube-v1',semantic_encoding.ENCODING_ID,semantic_encoding.PROP_ENCODING_ID):raise ValueError('未知技术底稿编码')
    extended=encoding in (semantic_encoding.ENCODING_ID,semantic_encoding.PROP_ENCODING_ID)
    prop_encoding=encoding==semantic_encoding.PROP_ENCODING_ID
    if prop_encoding:plans=[object_plan.upgrade(plan) for plan in plans]
    image, ids, line_alpha, manifest = _decode_garments(master_path,encoding=encoding) if extended else _decode(master_path)
    if extended:
        # Single flat garments can use fine structural lines. Requiring a
        # second filled region encouraged the unwanted heavy fold patches.
        from source_colorways import colorway
        require_blush = any(colorway(p['source_hd_id']).get('role_presence', {}).get('cheek', {}).get('present', True) for p in plans if p.get('source_colorway'))
        require_shadow = any(p['roles']['skin_base'] != p['roles']['skin_shadow'] for p in plans)
        manifest['style_language'] = validate_role_map(ids, line_alpha, _IDS,
            require_blush=require_blush, require_skin_shadow=require_shadow)
    manifest['cheek_edge_cleanliness'] = validate_cheek_edge_specks(ids, line_alpha, _IDS)
    if prop_encoding:manifest['object_cleanliness']=object_plan.validate_clean_regions(ids,line_alpha,_IDS)
    ids, line_alpha, bottom_alignment = _align_subject_to_bottom(ids, line_alpha)
    manifest['pre_alignment_role_map_sha256'] = manifest['role_map_sha256']
    manifest['pre_alignment_line_alpha_sha256'] = manifest['line_alpha_sha256']
    manifest['role_map_sha256'] = _sha(ids.tobytes())
    manifest['line_alpha_sha256'] = _sha(line_alpha.tobytes())
    manifest['role_pixel_counts'] = {role: int(_count(_mask(ids, role))) for role in _IDS}
    manifest['bottom_alignment'] = bottom_alignment
    manifest['background_corners_validation_stage'] = 'decoded-source-before-bottom-anchor'
    decoded_at = perf_counter()
    masks = {role: _mask(ids, role) for role in _IDS}
    # Exclude hidden role labels under opaque ink, then erode a pixel so
    # antialias colors cannot substitute for either real gradient endpoint.
    visible = line_alpha.point([255 if value == 0 else 0 for value in range(256)])
    gradient_roles=('hair',)+garment_plan.GARMENT_ROLES
    gradient_masks = {role: ImageChops.multiply(masks[role], visible).filter(ImageFilter.MinFilter(3))
                      for role in gradient_roles}
    min_region = max(4, image.width * image.height * 0.001)
    available = [role for role in gradient_roles
                 if _count(gradient_masks[role]) >= min_region]
    if not available and any(plan.get('gradient') for plan in plans):
        raise ValueError('可见头发或衣服面积不足，不能呈现所选模板渐变')
    output_dir.mkdir(parents=True, exist_ok=True)
    _save_png(ids, output_dir / 'role-ids.png')
    _save_png(line_alpha, output_dir / 'line-alpha.png')
    for role, mask in masks.items():
        _save_png(mask, output_dir / ('mask-' + role + '.png'))
    manifest['master_size'] = list(image.size)
    manifest['role_map_file'] = str(output_dir / 'role-ids.png')
    manifest['line_alpha_file'] = str(output_dir / 'line-alpha.png')
    manifest_path = output_dir / 'mask-manifest.json'
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    variants, details, signatures, pending = [], [], set(), []
    grid = Image.new('RGB', (image.width * 2, image.height * 2)) if len(plans) == 4 else None
    for index, plan in enumerate(plans):
        roles = plan['roles']
        colors = {'line': roles['outline'], 'background': roles['background'],
                  'skin_base': roles['skin_base'], 'skin_shadow': roles['skin_shadow'],
                  'hair': roles['hair'], 'clothing': roles['clothing'],
                  'accent': roles['cheek'], 'detail': roles['detail']}
        if extended:
            gp=plan.get('garment_plan')
            garment_plan.validate(gp,plan['source_hd_id'])
            colors.update(gp['render_roles'])
            if prop_encoding:colors.update(plan['object_plan']['roles'])
            inner_visible=_count(ImageChops.multiply(masks['clothing_inner'],visible))
            if inner_visible>=min_region and colors['clothing']==colors['clothing_inner']:
                raise ValueError('外套和内搭颜色仍相同，不能合并衣层交付')
        palette = [0] * 768
        for role, color in colors.items():
            offset = _IDS[role] * 3
            palette[offset:offset + 3] = _rgb(color)
        indexed = ids.copy().convert('P')
        indexed.putpalette(palette)
        rendered = indexed.convert('RGB')
        requested_gradient = dict(plan['gradient']) if plan.get('gradient') else None
        gradient_options=list(plan.get('gradient_options',[]))
        if extended:
            gradient_options=[g for g in gradient_options if g['region']=='hair']+gp['gradients']
            if requested_gradient and requested_gradient['region']=='clothing':
                requested_gradient={k:v for k,v in gp['gradients'][0].items() if k!='samples'} if gp['gradients'] else None
        requested_region = requested_gradient['region'] if requested_gradient else None
        # Keep all source-defined role gradients, one per visible role. A
        # clothing gradient is not discarded just because hair is visible.
        gradients = []
        for candidate in ([requested_gradient] if requested_gradient else []) + gradient_options:
            if candidate['region'] in available and candidate['region'] not in {item['region'] for item in gradients}:
                gradients.append({key: candidate[key] for key in ('region', 'from', 'to', 'direction')})
        if requested_gradient and not gradients and plan.get('source_colorway'):
            raise ValueError(f"TS-{plan['source_hd_id']:03d}的可见部位没有同角色渐变；不能把头发配色移到衣服，请换完整模板方案")
        applied = []
        for gradient in gradients:
            region = gradient['region']
            bounds, domain = _gradient_domain(gradient_masks[region], gradient)
            gradient_rgb, gradient_weights = _gradient_image(image.size, bounds, gradient)
            rendered = Image.composite(gradient_rgb, rendered, masks[region])
            histogram = gradient_weights.histogram(mask=gradient_masks[region])
            applied.append({'gradient': gradient, 'coordinate_domain': domain,
                            'visible_gradient_steps': sum(bool(count) for count in histogram)})
        rendered = Image.composite(Image.new('RGB', image.size, roles['outline']), rendered, line_alpha)
        for item in applied:
            item['visibility'] = _gradient_metrics(rendered, gradient_masks[item['gradient']['region']], item['gradient'])
        if requested_gradient and not any(item['visibility']['qualifies_as_required'] for item in applied):
            raise ValueError('人物局部渐变未通过最终RGB可见性检查：两端、连续过渡或色差不足，未生成最终拼图')
        primary = next((item for item in applied if item['gradient']['region'] == requested_region), applied[0] if applied else None)
        gradient = primary['gradient'] if primary else None
        signature = _sha(rendered.tobytes())
        if signature in signatures:
            raise ValueError('四版出现完全相同配色，未生成最终拼图')
        signatures.add(signature)
        destination = output_dir / (f'variant-{index + 1:02d}.png' if grid is not None else 'avatar.png')
        pending.append((rendered, destination))
        variants.append(str(destination))
        if grid is not None:
            grid.paste(rendered, ((index % 2) * image.width, (index // 2) * image.height))
        details.append({'index': index + 1, 'delivery': str(destination),
                        'pixel_sha256': signature, 'size': list(image.size),
                        'source_colorway': plan.get('source_colorway'),
                        'source_selection': plan['source_selection'],
                        'garment_plan':gp if extended else None,
                        'garment_encoding':encoding,
                        'object_plan':plan.get('object_plan') if prop_encoding else None,
                        'role_map_sha256': manifest['role_map_sha256'],
                        'line_alpha_sha256': manifest['line_alpha_sha256'],
                        'gradient': gradient, 'gradient_region_changed': bool(gradient and gradient['region'] != requested_region),
                        'visible_gradient_steps': primary['visible_gradient_steps'] if primary else 0,
                        'gradient_visibility': primary['visibility'] if primary else {'required': False, 'reason': 'source_palette_is_flat'}, 'applied_gradients': applied})
    # Publish artwork only once every plan passes the delivered-pixel checks.
    for rendered, destination in pending:
        _save_png(rendered, destination)
    delivery = output_dir / 'avatar-four-colors.png' if grid is not None else Path(variants[0])
    if grid is not None:
        _save_png(grid, delivery)
    return {'status': 'completed', 'delivery': str(delivery), 'delivery_size': list(grid.size if grid is not None else image.size),
            'variants': variants, 'variant_details': details, 'master_size': list(image.size),
            'mask_manifest': str(manifest_path),
            'geometry_lock': {'same_pixel_geometry': True,
                              'bottom_alignment': bottom_alignment,
                              'role_map_sha256': manifest['role_map_sha256'],
                              'line_alpha_sha256': manifest['line_alpha_sha256'],
                              'scope': '共用一次解码的角色图与线条alpha；换色前全体统一贴底平移，四版之间不重新绘制、裁切或移动人物'},
            'timings': {'decode_seconds': round(decoded_at - started, 6),
                        'render_seconds': round(perf_counter() - decoded_at, 6),
                        'total_seconds': round(perf_counter() - started, 6)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--plans', type=Path, help='Independent list of one or four standard color plans')
    source.add_argument('--request', type=Path, help='Request JSON containing variant_plans')
    parser.add_argument('--encoding', choices=('semantic-cube-v1', semantic_encoding.ENCODING_ID, semantic_encoding.PROP_ENCODING_ID),
                        help='底稿编码；默认读取request元数据，独立旧plans使用v1')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads((args.request or args.plans).read_text(encoding='utf-8'))
        plans = payload['variant_plans'] if args.request else payload
        encoding = args.encoding or (payload.get('master_encoding', 'semantic-cube-v1') if args.request else 'semantic-cube-v1')
        result = render_variants(args.master, plans, args.out_dir, encoding=encoding)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, 'Error: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
