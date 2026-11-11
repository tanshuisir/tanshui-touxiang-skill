"""Use complete, visually sampled reference palettes without mixing sources."""
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
from colorway_selection import draw_colorway_ids
import garment_plan

from line_plan import plan_lines
from source_colors import library as role_library, background_brightness


SKILL = Path(__file__).resolve().parents[1]
POLICY_ID = 'single-source-colorways-v1'
GRADIENT_POLICY_ID = 'visible-source-gradients-v2'
ROLES = ('outline', 'skin_base', 'skin_shadow', 'hair', 'clothing',
         'background', 'cheek', 'detail')


@lru_cache(maxsize=1)
def catalog():
    data = json.loads((SKILL/'references/source-colorways.json').read_text(encoding='utf-8'))
    records = data.get('colorways', [])
    if (data.get('policy_id') != POLICY_ID or len(records) != 70 or
            {item.get('source_hd_id') for item in records} != set(range(1, 71)) or
            any(item.get('id') != f"TS-{item['source_hd_id']:03d}-colorway" for item in records)):
        raise ValueError('完整70套模板配色目录缺失；不能回退到旧库或跨图混搭')
    return data


@lru_cache(maxsize=1)
def line_library():
    return json.loads((SKILL/'references/line-library.json').read_text(encoding='utf-8'))


def colorway(identifier):
    if isinstance(identifier, bool):
        raise ValueError('TS模板编号必须为整数1至70或TS标识，不能为布尔值')
    if isinstance(identifier, str) and identifier.startswith('TS-') and len(identifier) == 6:
        identifier += '-colorway'
    found = next((item for item in catalog()['colorways']
                  if item['id'] == identifier or item['source_hd_id'] == identifier), None)
    if found is None:
        raise ValueError('不存在的TS模板配色；旧素材编号不能自动映射，请重新选择TS-001至TS-070：' + str(identifier))
    return found


def eligible_colorways():
    """Every independently verified original participates, including white/flat/dark."""
    candidates = catalog()['colorways']
    if not candidates:
        raise ValueError('完整模板配色目录为空；停止，不跨图混色')
    for item in candidates:
        validate_template(item)
    return candidates


def eligibility_reasons(item):
    """Tone and gradient presence no longer exclude a verified source palette."""
    return []


def validate_template(item, require_eligible=True):
    """Check cached provenance; pixel sampling is verified when authoring."""
    hd, roles = item['source_hd_id'], item['roles']
    sources = role_library()
    skin = next((x for x in sources['skins'] if x['id'] == item['skin_template_id']), None)
    bg = next((x for x in sources['backgrounds'] if x['id'] == item['background_template_id']), None)
    ink = next((x for x in line_library()['portraits'] if x['id'] == hd), None)
    if skin is None or bg is None or ink is None or skin['source_hd_id'] != hd or bg['source_hd_id'] != hd:
        raise ValueError('整套配色的肤色、背景及线色必须来自同一张模板')
    if (roles['skin_base'] != skin['base']['hex'] or
            roles['skin_shadow'] != (skin['shadow'] or skin['base'])['hex'] or
            roles['background'] != bg['hex'] or roles['outline'] != ink['primary_hex']):
        raise ValueError('整套配色必须保持同一模板的真实角色颜色')
    samples = item['samples']
    for role in ROLES:
        if samples[role]['hex'] != roles[role]:
            raise ValueError('配色角色缺少对应模板取样：' + role)
    gradient = item.get('gradient')
    options = item.get('gradient_options', [])
    if not gradient:
        if options:
            raise ValueError('有渐变备选但缺少主渐变，目录不完整')
        return skin, bg
    if (gradient['region'] not in ('hair', 'clothing') or
            gradient['from'] != samples['gradient_from']['hex'] or
            gradient['to'] != samples['gradient_to']['hex'] or
            math.dist(bytes.fromhex(gradient['from'][1:]), bytes.fromhex(gradient['to'][1:])) < 24):
        raise ValueError('渐变必须使用该模板同一发衣区域的实际端点')
    if not any(all(option.get(key) == gradient.get(key)
                   for key in ('region', 'from', 'to', 'direction')) for option in options):
        raise ValueError('主渐变必须对应模板已采样的完整渐变方案')
    for option in options:
        if (option.get('region') not in ('hair', 'clothing') or
                option.get('from') != option.get('samples', {}).get('from', {}).get('hex') or
                option.get('to') != option.get('samples', {}).get('to', {}).get('hex') or
                math.dist(bytes.fromhex(option['from'][1:]), bytes.fromhex(option['to'][1:])) < 24 or
                not isinstance(option.get('direction'), str) or not option['direction'].strip()):
            raise ValueError('每处渐变必须保留同一模板同角色的端点和方向')
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
        'reason': f"整套沿用TS-{item['source_hd_id']:03d}的配色关系，不跨图找替代背景",
        'adjusted': False, 'gradient': deepcopy(gradient), 'evaluated_roles': list(ROLES),
        'unevaluated_roles': [], 'minimum_separation': None, 'meets_plan': True,
        'instructions': f"背景只用模板TS-{item['source_hd_id']:03d}的{roles['background']}，满幅均匀不透明纯色；模板白色、近白或深色也原样保留，禁止渐变、纹理、投影或另换背景。",
        'tone_policy': {'id': 'complete-source-all70-background-v3',
                        'selected_brightness': round(background_brightness(roles['background']), 3),
                        'white_and_dark_source_backgrounds_allowed': True},
        'scope': '完整同源色板，全部70套参与；不是对新图效果的视觉验收',

    }
    gradient_parts = []
    for option in item.get('gradient_options', []):
        region = {'hair': '头发', 'clothing': '衣服或服饰'}[option['region']]
        gradient_parts.append(f"{region}{option['direction']}由{option['from']}连续过渡至{option['to']}")
    return {
        'id': item['id'], 'source_hd_id': item['source_hd_id'],
        'gradient_policy_id': GRADIENT_POLICY_ID,
        'source_colorway': provenance, 'roles': roles, 'gradient': gradient,
        'gradient_options': deepcopy(item.get('gradient_options', [])),
        'color_text': '；'.join(f'{key}: {value}' for key, value in roles.items()),
        'gradient_instructions': ('该模板没有已核对的发衣渐变，严格保留模板平涂，不新增渐变、不跨角色或跨模板借色。' if not gradient else '；'.join(gradient_parts) + '。可见角色保留对应模板渐变；每张预览或高清至少一处在普通头像尺寸下清楚看见两端颜色及中间连续过渡，两端各占可辨认面积。渐变端点优先于该区域基色，不退化成微弱同色变化、细边或硬切两块色；不把发色移到衣服，不用背景渐变代替。'),
        'gradient_adjustment': None,
        'garment_plan': garment_plan.plan_for(item['source_hd_id']),
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
    for key in ('id', 'source_hd_id', 'roles', 'gradient', 'gradient_options',
                'gradient_policy_id', 'source_colorway', 'source_selection', 'background_plan'):
        if plan.get(key) != expected.get(key):
            raise ValueError('整套模板配色已被拆换或来源不符：' + key)
    for key in ('source_reference_id', 'source_image', 'source_sha256', 'primary_hex', 'primary_sample_xy', 'role_colors', 'family_id'):
        if lines.get(key) != expected['line_plan'][key]:
            raise ValueError('线色必须对应本版模板：' + key)


def validate_plan(plan):
    """Reject valid individual swatches borrowed from another portrait."""
    provenance = plan.get('source_colorway', {}) if isinstance(plan, dict) else {}
    if provenance.get('policy_id') != POLICY_ID:
        raise ValueError('头像须绑定完整模板模板；旧混搭方案请迁移后再交付')
    item = colorway(provenance.get('template_id'))
    expected = plan_for(item['id'], {'line_family': plan.get('line_plan', {}).get('family_id')})
    _compare_plan(plan, expected)
    if 'garment_plan' in plan:
        garment_plan.validate(plan['garment_plan'],item['source_hd_id'])
    return item


def upgrade_gradient_plan(plan):
    """Validate a frozen current-library plan without mapping older artwork."""
    if not isinstance(plan, dict):
        raise ValueError('配色计划必须为对象')
    if plan.get('gradient_policy_id') != GRADIENT_POLICY_ID:
        raise ValueError('旧版或未知渐变计划不能映射到新模板；请重新选择TS模板')
    validate_plan(plan)
    return garment_plan.upgrade(plan)


def requested_colorway(identifier, reference_id=None):
    """Resolve an explicit selection; unavailable whole palettes never mix/fallback."""
    if identifier == 'auto':
        selected, selection = draw_colorway_ids([item['source_hd_id'] for item in eligible_colorways()], 1)
        item = deepcopy(colorway(selected[0]))
        item['palette_selection'] = selection
        return item
    if identifier == 'reference':
        return colorway(reference_id)
    if isinstance(identifier, str) and identifier.isdigit():
        identifier = int(identifier)
    return colorway(identifier)


def single_plan_for(brief, reference_id=None, color_mode='expressive'):
    """Migrate old single briefs to the same immutable palettes used by four tiles."""
    if color_mode != 'expressive':
        raise ValueError('所有头像统一完整同源配色；natural 已停用，不能单独保留照片发色')
    explicit = brief.get('colorway_reference_id', brief.get('source_colorway_id'))
    selection = None
    if explicit is not None:
        selected = requested_colorway(explicit, reference_id)
    elif brief.get('requested_palette') is not None:
        selected = requested_colorway(brief['requested_palette'], reference_id)
    else:
        hint = brief.get('art_palette', brief.get('line_reference_id'))
        if hint is not None:
            selected = requested_colorway(hint, reference_id)
        else:
            references, selection = draw_colorway_ids(
                [item['source_hd_id'] for item in eligible_colorways()], 1)
            selected = colorway(references[0])
    plan = plan_for(selected['id'], brief)
    if brief.get('garment_plan') and brief['garment_plan'].get('source_hd_id')==selected['source_hd_id']:
        garment_plan.validate(brief['garment_plan'],selected['source_hd_id'])
        plan['garment_plan']=deepcopy(brief['garment_plan'])
    selection = selection or selected.get('palette_selection')
    if selection is None and brief.get('palette_selection'):
        saved = brief['palette_selection']
        if isinstance(saved, dict) and selected['source_hd_id'] in saved.get('source_hd_ids', []):
            selection = deepcopy(saved)
    if selection:
        plan['palette_selection'] = selection
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
