"""Read traced reference inks and drawing categories; never invent line colors."""
import re


FAMILY_IDS = ('rounded-monoline', 'bold-graphic', 'fine-structured',
              'open-duotone', 'offset-accent')
CORE_ROLES = ('contour', 'face', 'hair', 'clothing')
MODE_FAMILIES = {'bold': 'bold-graphic', 'cartoon': 'bold-graphic',
                 'texture': 'fine-structured', 'duotone': 'open-duotone',
                 'glitch': 'offset-accent'}


def _hex(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError(f'{field} 必须为线条库中已有的 #RRGGBB 核心线色')
    return value.upper()


def _reference_id(value, field):
    if type(value) is not int:
        raise ValueError(f'{field} 必须为现有高清参考的整数编号')
    return value


def plan_lines(brief, library, palette_source_id, reference_id, mode):
    """Resolve explicit choices first, then the palette, TS template, and TS-025.

    An explicit outline color can select any existing primary ink. Supplying a
    different line_reference_id at the same time is a conflict, not permission
    to silently override one of the user's choices. Secondary colors are only
    retained as source evidence; this version never renders secondary inks.
    """
    portraits = library.get('portraits')
    families = library.get('families')
    rules = library.get('role_rules')
    if not isinstance(portraits, list) or not portraits:
        raise ValueError('线条库缺少逐图采样记录，请先完成本地线条库安装')
    if not isinstance(families, list) or not isinstance(rules, dict):
        raise ValueError('线条库缺少分类或分部画法，不能临时编造线条规范')
    by_id = {item['id']: item for item in portraits}
    by_family = {item['id']: item for item in families}
    explicit_id = brief.get('line_reference_id')
    if explicit_id is not None:
        _reference_id(explicit_id, 'line_reference_id')
        if explicit_id not in by_id:
            raise ValueError(f'线条库不存在 TS-{explicit_id:03d}，请选择现有编号')
        selected = by_id[explicit_id]
        reason = '用户明确指定线色参考'
    else:
        candidates = ((palette_source_id, '当前艺术色组的高清来源'),
                      (reference_id, '当前高清造型参考'), (25, 'TS-025 默认参考'))
        selected = next((by_id[number] for number, _ in candidates if number in by_id), None)
        if selected is None:
            raise ValueError('线条库中没有可追溯的默认主线色，不能随机生成替代色')
        reason = next(label for number, label in candidates if number == selected['id'])
    selected_hex = _hex(selected['primary_hex'], '线条库 primary_hex')
    custom_roles = brief.get('color_roles')
    explicit_color = custom_roles.get('outline') if isinstance(custom_roles, dict) else None
    if explicit_color is not None:
        explicit_color = _hex(explicit_color, 'color_roles.outline')
        matches = [item for item in portraits if _hex(item['primary_hex'], '线条库 primary_hex') == explicit_color]
        if not matches:
            raise ValueError(f'color_roles.outline={explicit_color} 不在逐图核心线色库；'
                             '旧 brief 请删除该 outline 字段，并用 line_reference_id 从库中重选')
        if explicit_id is not None and explicit_color != selected_hex:
            raise ValueError(f'line_reference_id=TS-{explicit_id:03d} 的主线色为 {selected_hex}，'
                             f'与显式 outline={explicit_color} 冲突；删除旧 outline 或使用一致的库内颜色')
        if explicit_color != selected_hex:
            selected = min(matches, key=lambda item: item['id'])
            selected_hex = explicit_color
            reason = '显式 outline 对应的库内核心线色；同色来源取最小 TS 编号'
    family_id = brief.get('line_family')
    if family_id is None:
        family_id = MODE_FAMILIES.get(mode, selected['line_family'])
    if not isinstance(family_id, str) or family_id not in by_family:
        raise ValueError('line_family 必须为线条库中的分类：' + '、'.join(by_family))
    family = by_family[family_id]
    role_instructions = {}
    role_labels = {}
    short_rules = {}
    for role in CORE_ROLES:
        rule = rules.get(role)
        if not isinstance(rule, dict) or not isinstance(rule.get('instructions'), str):
            raise ValueError(f'线条库缺少 {role} 部位规则')
        role_instructions[role] = rule['instructions']
        role_labels[role] = rule.get('label', role)
        short_rules[role] = rule.get('short_instructions', rule['instructions'])
    source_xy = selected.get('primary_sample_xy')
    if (not isinstance(source_xy, list) or len(source_xy) != 2 or
            any(type(value) is not int or value < 0 for value in source_xy)):
        raise ValueError('核心线色缺少原图精确采样坐标，不能作为已验证色使用')
    role_text = '；'.join(f'{role_labels[role]}：{role_instructions[role]}' for role in CORE_ROLES)
    texture_rule = rules.get('texture', {})
    if mode == 'texture' and texture_rule.get('instructions'):
        role_text += '；衣服纹理：' + texture_rule['instructions'] + '，使用同一核心线色，不另选新线色'
    instructions = (
        f"从已沉淀线条库读取 TS-{selected['id']:03d} 核心线色 {selected_hex}；"
        f"轮廓、眉眼鼻口、头发内部结构线与衣服结构线统一用该色，不随机换色。"
        f"分类 {family['name']}（{family_id}）：{family['instructions']}；{role_text}。"
        '阴影色面边界不另描线；不因线条分类补回碎发、眼白或眼内高光。'
        '辅助亮线与偏色边仅存档，本版执行器不添加；不能凭空增加其他线色。')
    short_labels = {'contour': '轮廓', 'face': '五官', 'hair': '发内', 'clothing': '衣饰'}
    short_instructions = (
        f"TS-{selected['id']:03d} {selected_hex}统一用于轮廓/五官/发内/衣饰；"
        f"{family_id}：{family.get('short_instructions', family['instructions'])}；"
        + '；'.join(f'{short_labels[role]}：{short_rules[role]}' for role in CORE_ROLES)
        + '。辅助色仅存档，执行不添加；不加库外线色。')
    return {
        'schema_version': 1,
        'source_reference_id': selected['id'],
        'source_label': selected.get('label', f"TS-{selected['id']:03d}"),
        'source_image': selected.get('reference_image', f"assets/templates/{selected['id']:03d}.png"),
        'source_sha256': selected.get('sha256'),
        'primary_hex': selected_hex,
        'primary_sample_xy': list(source_xy),
        'family_id': family_id,
        'family_name': family['name'],
        'source_family_id': selected['line_family'],
        'family_instructions': family['instructions'],
        'role_colors': {role: selected_hex for role in CORE_ROLES},
        'role_instructions': role_instructions,
        'role_short_instructions': short_rules,
        'hair_policy_id': rules['hair'].get('policy_id'),
        'hair_precedence': rules['hair'].get('precedence', ''),
        'role_width_ratios': {role: rules[role].get('width_ratio') for role in CORE_ROLES},
        'optional_role_rules': {role: rules[role] for role in ('texture', 'accent') if role in rules},
        'secondary_candidates': selected.get('secondary_colors', []),
        'secondary_enabled': False,
        'selection_reason': reason,
        'color_basis': '参考 PNG 轮廓或面部墨色的精确像素；不是背景、发块填色或作者工程笔刷色',
        'instructions': instructions,
        'short_instructions': short_instructions,
    }
