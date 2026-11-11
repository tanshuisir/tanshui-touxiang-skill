"""Independent prop surfaces and tongue; reuse exact same-palette colors."""
from collections import deque
from copy import deepcopy
import re

from PIL import ImageFilter

POLICY_ID = 'clean-props-independent-tongue-v1'
ROLES = ('object_primary', 'object_secondary', 'tongue')
INSTRUCTIONS = (
    '道具按真实部件分区，内部是干净连续的平涂大面，不画颗粒、网点、抖色、喷点或渐变；'
    '例如冰淇淋球和甜筒分别用object_primary与object_secondary编码，不合成一个配饰色。'
    '照片可见舌头时独立用tongue编码，保留舔食动作、接触位置和嘴内必要短线，不能把舌面涂成黑色或衣服花纹色；'
    '不可见时不添加。各部件保留平顺轮廓、手指遮挡和连接，甜筒被手遮住的几段仍是同一材料。'
    '最终道具与舌头可复用本版同套色卡中的其他已有颜色，程序会独立填色；'
    '这项灵活映射只适用于道具/舌头，不改变脸、肤影、背景、头发和衣服的原有角色色。'
)


def _rgb(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9A-F]{6}', value):
        raise ValueError('道具色必须为现有色卡内的#RRGGBB')
    return tuple(bytes.fromhex(value[1:]))


def _distance(first, second):
    return sum((a - b) ** 2 for a, b in zip(_rgb(first), _rgb(second))) ** .5


def palette_colors(plan):
    colors = list(plan['roles'].values())
    colors += list(plan['garment_plan']['render_roles'].values())
    gradients = list(plan.get('gradient_options', [])) + list(plan['garment_plan'].get('gradients', []))
    if plan.get('gradient'):
        gradients.append(plan['gradient'])
    for gradient in gradients:
        colors.extend((gradient['from'], gradient['to']))
    return list(dict.fromkeys(colors))


def _is_fill(color, outline):
    return max(_rgb(color)) >= 100 and _distance(color, outline) >= 32


def default_plan(plan):
    roles = plan['roles']
    all_colors = palette_colors(plan)
    usable = [color for color in all_colors if _is_fill(color, roles['outline'])]
    if not usable:
        raise ValueError('同套色卡没有可辨识的道具/舌头填色，不回退为黑色')
    tongue_preferences = [roles['cheek'], roles['skin_shadow'], roles['clothing'],
                          roles['hair'], roles['detail']] + usable
    tongue = next((c for c in tongue_preferences if c in usable and _distance(c, roles['skin_base']) >= 16), usable[0])
    primary_preferences = [roles['detail'], roles['skin_base'], roles['clothing']] + usable
    primary = next((c for c in primary_preferences if c in usable and max(_rgb(c)) >= 160), usable[0])
    secondary_preferences = [plan['garment_plan']['render_roles']['clothing_trim'],
                             roles['clothing'], roles['hair'], roles['skin_shadow'],
                             roles['cheek']] + usable
    secondary = next((c for c in secondary_preferences if c in usable and _distance(c, primary) >= 24), None)
    if secondary is None:
        raise ValueError('同套色卡没有可区分的两种道具色，不合并材料或跨色卡补色')
    return {'policy_id': POLICY_ID, 'source_hd_id': plan['source_hd_id'],
            'roles': dict(zip(ROLES, (primary, secondary, tongue))),
            'assignment': 'same-palette-reuse'}


def validate(details, plan):
    if not isinstance(details, dict) or details.get('policy_id') != POLICY_ID or details.get('source_hd_id') != plan['source_hd_id']:
        raise ValueError('道具分区配色来源不符')
    colors = details.get('roles')
    if not isinstance(colors, dict) or set(colors) != set(ROLES):
        raise ValueError('道具主面、次面和舌头必须独立记录')
    allowed = set(palette_colors(plan))
    for color in colors.values():
        _rgb(color)
        if color not in allowed or not _is_fill(color, plan['roles']['outline']):
            raise ValueError('道具/舌头只能复用同套色卡内可辨识的非墨色填色')
    if _distance(colors['object_primary'], colors['object_secondary']) < 24:
        raise ValueError('道具两个材料必须有可辨识的色差')
    return details


def upgrade(plan, supplied=None):
    result = deepcopy(plan)
    details = supplied if supplied is not None else result.get('object_plan')
    if details is None:
        details = default_plan(result)
    validate(details, result)
    result['object_plan'] = deepcopy(details)
    return result


def validate_clean_regions(ids, line_alpha, role_ids):
    """Reject tiny foreign fill/ink islands enclosed in explicit prop regions.

    Uses no guessed face landmarks and never edits the artwork. Continuous
    contour, tongue crease and printed lines remain intact.
    """
    prop_ids = {role_ids[r] for r in ROLES}
    mask = ids.point([255 if v in prop_ids else 0 for v in range(256)])
    if not mask.getbbox():
        return {'policy_id': POLICY_ID, 'scope': 'no explicit prop/tongue regions', 'suspects': []}
    core = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MinFilter(3))
    labels, ink, enclosed = ids.tobytes(), line_alpha.tobytes(), core.tobytes()
    width, height = ids.size
    max_area = max(2, round(16 * (min(ids.size) / 1024) ** 2))
    box = core.getbbox()
    if box is None:
        raise ValueError('道具/舌头仅剩孤立编码点，没有可靠可见区域；按照片核对，不把碎点当物体')
    suspects = []
    for kind in ('fill', 'ink'):
        visited = set()
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                seed = y * width + x
                if not enclosed[seed] or seed in visited:
                    continue
                if kind == 'fill' and (labels[seed] in prop_ids or labels[seed] == 0 or ink[seed] >= 64):
                    continue
                if kind == 'ink' and ink[seed] < 64:
                    continue
                label = labels[seed]
                component = []
                todo = deque([seed])
                visited.add(seed)
                while todo:
                    pos = todo.popleft()
                    component.append(pos)
                    cy, cx = divmod(pos, width)
                    for ny in range(max(0, cy - 1), min(height, cy + 2)):
                        for nx in range(max(0, cx - 1), min(width, cx + 2)):
                            nxt = ny * width + nx
                            matches = (labels[nxt] == label and ink[nxt] < 64) if kind == 'fill' else ink[nxt] >= 32
                            if matches and nxt not in visited:
                                visited.add(nxt)
                                todo.append(nxt)
                if len(component) <= max_area and all(enclosed[p] for p in component):
                    suspects.append({'kind': kind, 'pixels': len(component),
                                     'xy': [x, y], 'role_id': label})
    if suspects:
        raise ValueError('道具/舌头表面存在孤立颗粒或角色误码；仅按已确认局部蒙版修复，不全图降噪。证据：' + str(suspects))
    return {'policy_id': POLICY_ID, 'scope': 'tiny islands enclosed in explicit prop/tongue regions only',
            'max_speck_pixels': max_area, 'suspects': []}
