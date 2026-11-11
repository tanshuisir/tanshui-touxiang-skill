"""Choose only role-verified source swatches; no image work on the fast path."""
from functools import lru_cache
import json
from pathlib import Path
import re
import secrets

LIBRARY = Path(__file__).resolve().parents[1]/'references/source-role-colors.json'
MIN_BACKGROUND_BRIGHTNESS = 150
WHITE_BACKGROUND_MIN_BRIGHTNESS = 235
WHITE_BACKGROUND_MAX_CHANNEL_SPREAD = 48


def background_brightness(color):
    """Return the existing sRGB planning brightness, never alter the color."""
    if not isinstance(color, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', color):
        raise ValueError('背景颜色必须为 #RRGGBB')
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    return sum(weight * channel for weight, channel in zip((0.299, 0.587, 0.114), rgb))


def is_white_background(color):
    """Block white and near-white neutrals; this is a new design rule.

    This threshold is not a source-art measurement or a perceptual guarantee.
    Bright chromatic pastel backgrounds remain available.
    """
    brightness = background_brightness(color)
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    return (brightness >= WHITE_BACKGROUND_MIN_BRIGHTNESS
            and max(rgb) - min(rgb) <= WHITE_BACKGROUND_MAX_CHANNEL_SPREAD)


def is_allowed_background(color):
    """Historical independent planner only; complete 70-palette selection ignores tone."""
    return (background_brightness(color) >= MIN_BACKGROUND_BRIGHTNESS
            and not is_white_background(color))


@lru_cache(maxsize=1)
def library():
    data = json.loads(LIBRARY.read_text(encoding='utf-8'))
    if data.get('policy_id') != 'source-role-colors-v1' or not data.get('skins') or not data.get('backgrounds'):
        raise ValueError('肤色/背景来源库缺失或版本不符，停止，不回退到自创颜色')
    return data


def skin_for(brief, roles):
    templates = library()['skins']
    requested = brief.get('skin_template_id')
    if requested is not None:
        selected = next((item for item in templates if item['id'] == requested), None)
        if selected is None:
            raise ValueError('不存在的 skin_template_id: '+str(requested))
    else:
        # Preserve an old valid source color, while migrating any former
        # designed/cross-role skin to a real source template.
        saved_roles = brief.get('color_roles') or {}
        saved = saved_roles.get('skin_base', '').upper()
        shadow = saved_roles.get('skin_shadow', '').upper()
        matches = [item for item in templates if item['base']['hex'] == saved]
        exact = [item for item in matches if (item['shadow'] or item['base'])['hex'] == shadow]
        selected = (exact or matches)[0] if matches else secrets.choice(templates)
    roles['skin_base'] = selected['base']['hex']
    roles['skin_shadow'] = (selected['shadow'] or selected['base'])['hex']
    return {'template_id': selected['id'], 'source_hd_id': selected['source_hd_id'],
            'base': roles['skin_base'], 'shadow': roles['skin_shadow']}


def background_templates():
    return library()['backgrounds']


def eligible_background_templates():
    return [item for item in background_templates() if is_allowed_background(item['hex'])]


def background_request(brief, roles):
    requested = brief.get('background_template_id')
    if requested is None:
        return
    selected = next((item for item in background_templates() if item['id'] == requested), None)
    if selected is None:
        raise ValueError('不存在的 background_template_id: '+str(requested))
    roles['background'] = selected['hex']


def background_source(color, preferred=None):
    matches = [item for item in background_templates() if item['hex'] == color]
    selected = next((item for item in matches if item['id'] == preferred), matches[0] if matches else None)
    if selected is None:
        raise ValueError('背景颜色不在模板背景库，停止，不使用自创回退色')
    return {'template_id': selected['id'], 'source_hd_id': selected['source_hd_id'], 'hex': selected['hex']}
