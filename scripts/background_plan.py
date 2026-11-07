"""Plan single-color opaque backgrounds from known subject role colors.

The small RGB/brightness/hue heuristic is a planning aid, not a perceptual or
accessibility certification. It never changes a subject role or subject gradient.
"""
import colorsys
from copy import deepcopy
import math
import re
import secrets
from source_colors import (background_templates, background_brightness,
                           is_allowed_background, is_white_background,
                           MIN_BACKGROUND_BRIGHTNESS,
                           WHITE_BACKGROUND_MIN_BRIGHTNESS,
                           WHITE_BACKGROUND_MAX_CHANNEL_SPREAD)


_ROLE_THRESHOLDS = {'hair': 1.0, 'clothing': 1.0, 'skin_base': 0.65, 'outline': 0.55}
_MIN_BACKGROUND_BRIGHTNESS = MIN_BACKGROUND_BRIGHTNESS


def _hex(value):
    return value.upper() if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) else None


def _rgb(value):
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _brightness(value):
    # Planning preference on an sRGB 0–255 scale, not a visual certification.
    return background_brightness(value)


def _color(values):
    return '#' + ''.join(f'{max(0, min(255, round(value))):02X}' for value in values)


def _mix(first, second, amount):
    return _color(a + (b - a) * amount for a, b in zip(_rgb(first), _rgb(second)))


def _separation(first, second):
    a, b = _rgb(first), _rgb(second)
    distance = math.dist(a, b)
    brightness = abs(sum(weight * (x - y) for weight, x, y in zip((0.299, 0.587, 0.114), a, b)))
    hue_a, saturation_a, _ = colorsys.rgb_to_hsv(*(value / 255 for value in a))
    hue_b, saturation_b, _ = colorsys.rgb_to_hsv(*(value / 255 for value in b))
    hue_difference = min(abs(hue_a - hue_b), 1 - abs(hue_a - hue_b))
    # Hue has little meaning for grey/white/black, so require brightness there.
    hue_score = hue_difference / 0.15 if min(saturation_a, saturation_b) >= 0.2 else 0.0
    return min(distance / 100, max(brightness / 45, hue_score))


def _score(colors, targets):
    return min((_separation(color, foreground) / threshold
                for color in colors for _, foreground, threshold in targets), default=0.0)


def _samples(first, second):
    # Check interior stops as well: two distant endpoints can cross a subject color.
    return [_mix(first, second, index / 8) for index in range(9)]


def plan_background(roles, gradient):
    """Return a traceable opaque background plan without mutating either input.

    Only #RRGGBB role values can be assessed. Unknown natural hair or descriptive
    colors remain unknown; the report names this limitation instead of inventing
    photo observations. ``color`` is the only background color. Subject
    gradients are returned unchanged; background gradients must be migrated
    by the prompt builder before calling this helper.
    """
    if not isinstance(roles, dict):
        raise ValueError('roles 必须为颜色角色对象')
    if gradient is not None and not isinstance(gradient, dict):
        raise ValueError('gradient 必须为对象或 None')
    if gradient and gradient.get('region') == 'background':
        raise ValueError('背景必须为单一纯色；请先将旧背景渐变迁移到人物头发或衣服')
    original = _hex(roles.get('background'))
    targets = [(role, _hex(roles.get(role)), threshold)
               for role, threshold in _ROLE_THRESHOLDS.items() if _hex(roles.get(role))]
    unknown = [role for role in _ROLE_THRESHOLDS
               if not _hex(roles.get(role)) and (role in roles or role in ('hair', 'clothing'))]
    if gradient and gradient.get('region') in ('hair', 'clothing'):
        first, second = _hex(gradient.get('from')), _hex(gradient.get('to'))
        if first and second:
            targets.extend((f"{gradient['region']}_gradient_{index}", color, 1.0)
                           for index, color in enumerate(_samples(first, second)[::4]))
    # Strict allowlist: neither an old brief nor the contrast heuristic may
    # introduce a new background RGB outside the observed source backgrounds.
    source_candidates = list(dict.fromkeys(item['hex'] for item in background_templates()))
    # Brightness is a constraint before contrast ranking. Neither an old dark
    # template nor insufficient separation may restore the dark source pool.
    candidates = [color for color in source_candidates if is_allowed_background(color)]
    if not candidates:
        raise ValueError('原作背景库没有符合明亮偏好且非白的颜色，停止；不回退白色、深色或自创新色')
    allowed_original = original if original in candidates else None
    planned_gradient = deepcopy(gradient)
    if not targets:
        selected = allowed_original or secrets.choice(candidates)
        reason = '没有可计算的前景HEX色，仅从原作明亮非白背景库选纯色；无法判断人物与背景反差'
        score = 0.0
    else:
        if allowed_original and _score([allowed_original], targets) >= 1:
            selected = allowed_original
            reason = '现有背景属于原作明亮非白背景库且与已知人物角色色分离，保留原背景'
        else:
            scores = {color: _score([color], targets) for color in candidates}
            eligible = [color for color in candidates if scores[color] >= 1]
            selected = secrets.choice(eligible) if eligible else max(candidates, key=scores.get)
            reason = ('仅从原作明亮非白背景库中随机选择与人物分离的纯色；人物颜色不变'
                      if eligible else '仅从原作明亮非白背景库中选分离度最高的纯色；不为对比回退白色、深色或新增候选色')
        score = _score([selected], targets)

    adjusted = selected != original or planned_gradient != gradient
    if targets and score < 1:
        reason += '；有限候选仍未满足全部计划规则，实际画面需核对'
    if unknown:
        reason += '；未计算非HEX角色或缺失主色：' + '、'.join(unknown)
    instruction = (f'背景只用{selected}这一种明亮纯色，均匀铺满整个画面至四角和外缘，完全不透明；'
                   '与人物大面积发块和衣服分开，不留透明边或圆形裁切；背景严禁白色、近白、灰白或米白，不用白底替代。'
                   '不要为对比压暗或罩黑，背景禁止渐变、纹理、图案和投影。')
    return {
        'type': 'solid',
        'color': selected, 'original_color': original,
        'reason': reason, 'adjusted': adjusted, 'instructions': instruction,
        'gradient': planned_gradient,
        'evaluated_roles': [role for role, _, _ in targets],
        'unevaluated_roles': unknown,
        'minimum_separation': round(score, 4), 'meets_plan': bool(targets) and score >= 1,
        'tone_policy': {'id': 'source-light-nonwhite-background-v2',
                        'minimum_brightness': _MIN_BACKGROUND_BRIGHTNESS,
                        'selected_brightness': round(_brightness(selected), 3),
                        'candidate_count': len(candidates),
                        'excluded_dark_count': sum(_brightness(color) < _MIN_BACKGROUND_BRIGHTNESS for color in source_candidates),
                        'excluded_white_count': sum(is_white_background(color) for color in source_candidates),
                        'white_minimum_brightness': WHITE_BACKGROUND_MIN_BRIGHTNESS,
                        'white_maximum_channel_spread': WHITE_BACKGROUND_MAX_CHANNEL_SPREAD},
        'scope': '已知角色色的RGB距离、亮度和色相规划；不是视觉验收',
    }
