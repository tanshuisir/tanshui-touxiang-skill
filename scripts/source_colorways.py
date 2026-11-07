"""Use complete, visually sampled reference palettes without mixing sources."""
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path

from line_plan import plan_lines
from source_colors import (library as role_library, background_brightness,
                           is_allowed_background, MIN_BACKGROUND_BRIGHTNESS,
                           WHITE_BACKGROUND_MIN_BRIGHTNESS,
                           WHITE_BACKGROUND_MAX_CHANNEL_SPREAD)


SKILL = Path(__file__).resolve().parents[1]
POLICY_ID = 'single-source-colorways-v1'
GRADIENT_POLICY_ID = 'visible-source-gradients-v2'
ROLES = ('outline', 'skin_base', 'skin_shadow', 'hair', 'clothing',
         'background', 'cheek', 'detail')


@lru_cache(maxsize=1)
def catalog():
    data = json.loads((SKILL/'references/source-colorways.json').read_text(encoding='utf-8'))
    if data.get('policy_id') != POLICY_ID or not data.get('colorways'):
        raise ValueError('完整原作配色目录缺失；不能回退到跨图混搭')
    return data


@lru_cache(maxsize=1)
def line_library():
    return json.loads((SKILL/'references/line-library.json').read_text(encoding='utf-8'))


def colorway(identifier):
    found = next((item for item in catalog()['colorways']
                  if item['id'] == identifier or item['source_hd_id'] == identifier), None)
    if found is None:
        raise ValueError('该原作尚无已核对的完整配色方案：' + str(identifier))
    return found


def eligible_colorways():
    """Admit entire source palettes; never replace a rejected background."""
    candidates = [item for item in catalog()['colorways']
                  if is_allowed_background(item['roles']['background'])]
    if not candidates:
        raise ValueError('完整原作配色目录没有明亮非白的合规整套；停止，不单换背景或混搭其他原作')
    for item in candidates:
        validate_template(item)
    return candidates


def validate_template(item):
    """Check cached provenance; pixel sampling is verified when authoring."""
    hd, roles = item['source_hd_id'], item['roles']
    sources = role_library()
    skin = next((x for x in sources['skins'] if x['id'] == item['skin_template_id']), None)
    bg = next((x for x in sources['backgrounds'] if x['id'] == item['background_template_id']), None)
    ink = next((x for x in line_library()['portraits'] if x['id'] == hd), None)
    if skin is None or bg is None or ink is None or skin['source_hd_id'] != hd or bg['source_hd_id'] != hd:
        raise ValueError('整套配色的肤色、背景及线色必须来自同一张原作')
    if (roles['skin_base'] != skin['base']['hex'] or
            roles['skin_shadow'] != (skin['shadow'] or skin['base'])['hex'] or
            roles['background'] != bg['hex'] or roles['outline'] != ink['primary_hex']):
        raise ValueError('整套配色必须保持同一原作的真实角色颜色')
    if not is_allowed_background(roles['background']):
        raise ValueError('整套背景严禁白色、近白、灰白、米白或深色；选择另一套明亮非白原作配色，不能单独换背景')
    samples = item['samples']
    for role in ROLES:
        if samples[role]['hex'] != roles[role]:
            raise ValueError('配色角色缺少对应原作取样：' + role)
    gradient = item['gradient']
    if (gradient['region'] not in ('hair', 'clothing') or
            gradient['from'] != samples['gradient_from']['hex'] or
            gradient['to'] != samples['gradient_to']['hex'] or
            math.dist(bytes.fromhex(gradient['from'][1:]), bytes.fromhex(gradient['to'][1:])) < 24):
        raise ValueError('渐变必须使用该原作同一发衣区域的实际端点')
    options = item.get('gradient_options', [])
    if not any(all(option.get(key) == gradient.get(key)
                   for key in ('region', 'from', 'to', 'direction')) for option in options):
        raise ValueError('主渐变必须对应原作已采样的完整渐变方案')
    for option in options:
        if (option.get('region') not in ('hair', 'clothing') or
                option.get('from') != option.get('samples', {}).get('from', {}).get('hex') or
                option.get('to') != option.get('samples', {}).get('to', {}).get('hex') or
                not isinstance(option.get('direction'), str) or not option['direction'].strip()):
            raise ValueError('每处渐变必须保留同一原作同角色的端点和方向')
    return skin, bg


def plan_for(identifier, brief=None):
    """Return a full reference palette, keeping every sampled role together."""
    brief = brief or {}
    item = colorway(identifier)
    skin, bg = validate_template(item)
    roles, gradient = deepcopy(item['roles']), deepcopy(item['gradient'])
    line_brief = {'line_reference_id': item['source_hd_id']}
    if brief.get('line_family'):
        line_brief['line_family'] = brief['line_family']
    lines = plan_lines(line_brief, line_library(), item['source_hd_id'],
                       item['source_hd_id'], brief.get('mode', 'flat'))
    provenance = {
        'policy_id': POLICY_ID, 'template_id': item['id'],
        'source_hd_id': item['source_hd_id'], 'name': item['name'],
        'source_image': item['source_image'], 'source_sha256': item['source_sha256'],
        'samples': deepcopy(item['samples']),
    }
    background = {
        'type': 'solid', 'color': roles['background'], 'original_color': roles['background'],
        'reason': f"整套沿用HD-{item['source_hd_id']:03d}的配色关系，不跨图找替代背景",
        'adjusted': False, 'gradient': deepcopy(gradient), 'evaluated_roles': list(ROLES),
        'unevaluated_roles': [], 'minimum_separation': None, 'meets_plan': True,
        'instructions': f"背景只用原作HD-{item['source_hd_id']:03d}的{roles['background']}，满幅均匀不透明纯色；严禁白色、近白、灰白、米白、渐变、纹理、投影或另换背景。",
        'tone_policy': {'id': 'complete-source-bright-nonwhite-background-v2',
                        'minimum_brightness': MIN_BACKGROUND_BRIGHTNESS,
                        'selected_brightness': round(background_brightness(roles['background']), 3),
                        'white_minimum_brightness': WHITE_BACKGROUND_MIN_BRIGHTNESS,
                        'white_maximum_channel_spread': WHITE_BACKGROUND_MAX_CHANNEL_SPREAD},
        'scope': '完整同源色板与明亮非白背景约束；不是对新图效果的视觉验收',
    }
    gradient_parts = []
    for option in item.get('gradient_options', [gradient]):
        region = {'hair': '头发', 'clothing': '衣服或服饰'}[option['region']]
        gradient_parts.append(f"{region}{option['direction']}由{option['from']}连续过渡至{option['to']}")
    return {
        'id': item['id'], 'source_hd_id': item['source_hd_id'],
        'gradient_policy_id': GRADIENT_POLICY_ID,
        'source_colorway': provenance, 'roles': roles, 'gradient': gradient,
        'gradient_options': deepcopy(item.get('gradient_options', [])),
        'color_text': '；'.join(f'{key}: {value}' for key, value in roles.items()),
        'gradient_instructions': '；'.join(gradient_parts) + '。可见角色保留对应原作渐变；每张预览或高清至少一处在普通头像尺寸下清楚看见两端颜色及中间连续过渡，两端各占可辨认面积。渐变端点优先于该区域基色，不退化成微弱同色变化、细边或硬切两块色；不把发色移到衣服，不用背景渐变代替。',
        'gradient_adjustment': None,
        'source_selection': {
            'policy_id': role_library()['policy_id'],
            'skin': {'template_id': skin['id'], 'source_hd_id': item['source_hd_id'],
                     'base': roles['skin_base'], 'shadow': roles['skin_shadow']},
            'background': {'template_id': bg['id'], 'source_hd_id': item['source_hd_id'],
                           'hex': roles['background']},
        },
        'background_plan': background, 'line_plan': lines,
    }


def _compare_plan(plan, expected):
    lines = plan.get('line_plan', {})
    # Older complete plans may differ only in the background policy metadata.
    # Reconstruct the exact prior shape; never accept arbitrary color edits.
    legacy_background = deepcopy(expected['background_plan'])
    legacy_background['instructions'] = (
        f"背景只用原作HD-{expected['source_hd_id']:03d}的{expected['roles']['background']}，"
        '满幅均匀不透明纯色；禁止渐变、纹理、投影或另换背景。')
    legacy_background['tone_policy'] = {
        'id': 'complete-source-bright-background-v1', 'minimum_brightness': 150,
        'selected_brightness': round(background_brightness(expected['roles']['background']), 3)}
    legacy_background['scope'] = '完整同源色板与明亮背景约束；不是对新图效果的视觉验收'
    for key in ('id', 'source_hd_id', 'roles', 'gradient', 'gradient_options',
                'gradient_policy_id', 'source_colorway', 'source_selection', 'background_plan'):
        if key == 'background_plan' and plan.get(key) == legacy_background:
            continue
        if plan.get(key) != expected.get(key):
            raise ValueError('整套原作配色已被拆换或来源不符：' + key)
    for key in ('source_reference_id', 'primary_hex', 'primary_sample_xy', 'role_colors', 'family_id'):
        if lines.get(key) != expected['line_plan'][key]:
            raise ValueError('线色必须对应本版原作：' + key)


def validate_plan(plan):
    """Reject valid individual swatches borrowed from another portrait."""
    provenance = plan.get('source_colorway', {}) if isinstance(plan, dict) else {}
    if provenance.get('policy_id') != POLICY_ID:
        raise ValueError('头像须绑定完整原作模板；旧混搭方案请迁移后再交付')
    item = colorway(provenance.get('template_id'))
    expected = plan_for(item['id'], {'line_family': plan.get('line_plan', {}).get('family_id')})
    _compare_plan(plan, expected)
    return item


def upgrade_gradient_plan(plan):
    """Refresh only an exact recorded old gradient, preserving its source palette."""
    if not isinstance(plan, dict):
        raise ValueError('配色计划必须为对象')
    if plan.get('gradient_policy_id') == GRADIENT_POLICY_ID:
        validate_plan(plan)
        return deepcopy(plan)
    if plan.get('gradient_policy_id') is not None:
        raise ValueError('未知渐变版本，不能猜测替换已保存的配色')
    provenance = plan.get('source_colorway', {})
    if provenance.get('policy_id') != POLICY_ID:
        raise ValueError('旧渐变迁移仅适用于已核对的完整同源配色')
    item = colorway(provenance.get('template_id'))
    legacy = item.get('legacy_gradient_v1')
    if not legacy:
        raise ValueError('缺少该原作旧渐变的精确记录')
    expected = plan_for(item['id'], {'line_family': plan.get('line_plan', {}).get('family_id')})
    old_expected = deepcopy(expected)
    old_expected.pop('gradient_policy_id')
    old_expected['gradient'] = deepcopy(legacy['gradient'])
    old_expected['gradient_options'] = deepcopy(legacy['gradient_options'])
    old_expected['source_colorway']['samples'].update(deepcopy(legacy['samples']))
    old_expected['background_plan']['gradient'] = deepcopy(legacy['gradient'])
    _compare_plan(plan, old_expected)
    upgraded = deepcopy(plan)
    upgraded.update(expected)
    previous_tone = plan['background_plan']['tone_policy']['id']
    current_tone = expected['background_plan']['tone_policy']['id']
    if previous_tone != current_tone:
        upgraded['background_policy_migration'] = {
            'from': previous_tone, 'to': current_tone,
            'reason': '完整同源角色色均合规，仅刷新非白背景约束元数据；不替换任何角色颜色',
        }
    upgraded['gradient_migration'] = {
        'from': 'recorded-source-gradient-v1', 'to': GRADIENT_POLICY_ID,
        'reason': '补齐同一原作实际渐变端色，并按可见区域检查渐变；人物角色色与来源编号保持不变',
    }
    validate_plan(upgraded)
    return upgraded


def requested_colorway(identifier, reference_id=None):
    """Resolve an explicit selection; unavailable whole palettes never mix/fallback."""
    if identifier in ('auto', 'reference'):
        known = {item['source_hd_id'] for item in catalog()['colorways']}
        return colorway(reference_id if reference_id in known else catalog()['default_reference_ids'][0])
    if isinstance(identifier, str) and identifier.isdigit():
        identifier = int(identifier)
    # Historical named art palettes are selectors only, never partial swatches.
    if isinstance(identifier, str):
        aliases = json.loads((SKILL/'references/artistic-palettes.json').read_text())['palettes']
        alias = next((p for p in aliases if p['id'] == identifier), None)
        if alias:
            identifier = alias['source_hd_id']
    return colorway(identifier)


def single_plan_for(brief, reference_id=None, color_mode='expressive'):
    """Migrate old single briefs to the same immutable palettes used by four tiles."""
    if color_mode != 'expressive':
        raise ValueError('所有头像统一完整同源配色；natural 已停用，不能单独保留照片发色')
    explicit = brief.get('colorway_reference_id', brief.get('source_colorway_id'))
    if explicit is not None:
        selected = requested_colorway(explicit, reference_id)
    elif brief.get('requested_palette') is not None:
        selected = requested_colorway(brief['requested_palette'], reference_id)
    else:
        # Saved art_palette/line selectors are legacy hints. Prefer their
        # complete original when maintained; otherwise use the standard whole set.
        candidates = [brief.get('art_palette'), brief.get('line_reference_id'), reference_id]
        selected = None
        for hint in candidates:
            if hint is None or hint in ('auto', 'reference'):
                continue
            try:
                selected = requested_colorway(hint, reference_id)
                break
            except ValueError:
                continue
        selected = selected or requested_colorway('auto', reference_id)
    plan = plan_for(selected['id'], brief)
    legacy = {key: brief[key] for key in ('color_roles', 'gradient', 'skin_template_id',
              'background_template_id', 'line_reference_id', 'gradient_adjustment') if key in brief}
    expected = {'color_roles': plan['roles'], 'gradient': plan['gradient'],
                'skin_template_id': selected['skin_template_id'],
                'background_template_id': selected['background_template_id'],
                'line_reference_id': selected['source_hd_id'], 'gradient_adjustment': None}
    if any(value != expected[key] for key, value in legacy.items()):
        plan['migration'] = {'from': 'legacy-independent-role-selection', 'to': POLICY_ID,
                             'reason': '单图与四图统一完整同源，替换独立角色色与渐变',
                             'previous': deepcopy(legacy), 'source_hd_id': selected['source_hd_id']}
    elif brief.get('colorway_migration'):
        plan['migration'] = deepcopy(brief['colorway_migration'])
    validate_plan(plan)
    return plan
