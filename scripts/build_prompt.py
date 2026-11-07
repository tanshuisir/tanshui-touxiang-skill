#!/usr/bin/env python3
"""Prepare a photo-edit prompt and gen-img argv; never submit an image request."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from string import Template
from background_plan import plan_background
from eye_style import EYE_STYLE_ID, EYE_INSTRUCTIONS, EYE_PRECEDENCE
from line_plan import plan_lines
from composition import DEFAULT_SIZE, FRAMING_PLAN, FRAMING_INSTRUCTIONS
from source_colors import skin_for, background_request, background_source, library as source_color_library

SKILL = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
GEN_IMG_SKILL = Path(os.environ.get('GEN_IMG_SKILL_DIR', str(CODEX_HOME / 'skills/gen-img'))).expanduser()
GEN_IMG = GEN_IMG_SKILL / 'scripts/run.py'
MODES = {
    'flat': '平涂大面为主，常规轮廓、实心眉眼和圆腮红，少量硬边暗面；局部必须保留指定渐变，不铺网点。',
    'gradient': '彩色平涂为基础，在头发或服饰可见大面保留清楚的二色连续渐变；正常头像尺寸须看见两端颜色及过渡，主轮廓锐利，面部不作写实渐变，背景始终为单一纯色。',
    'texture': '保持清楚平涂，只在照片原本可见的衣服区域加入与该服装相符的简化线纹或网点。保留照片服装类别，不照搬参考衣领或图案。',
    'bold': '使用有力、平顺、较粗的外轮廓，减少内部结构线和小细节；保持照片的头型、五官比例和年龄。',
    'cartoon': '用较粗轮廓、简化短眉眼、少量弧线和圆腮红概括成卡通头像。简化细节但保持照片面部结构和年龄，不统一成大眼幼态脸。',
    'duotone': '使用双色或少量同类色组织、单一主线、清楚负形留白与有限色块，保持人物轮廓与五官位置，不删除必要辨识信息。',
    'glitch': '先完成清楚高对比平面头像，保留艺术角色色与指定渐变；本版辅助偏色边只存档，执行时不绘制，沿用统一核心主线。保持脸部五官锐利，不做全脸重影、模糊或噪声文字。',
}


def color_plan_for(brief, record, reference_set, color_mode):
    """Every avatar uses one complete source palette, regardless of tile count."""
    from source_colorways import single_plan_for
    return single_plan_for(brief, record['id'] if reference_set == 'finished' else None,
                           color_mode)


def identity_plan_for(brief, features):
    """Bind each observed feature to its drawing treatment, without inventing facts."""
    supplied = brief.get('identity_plan')
    if supplied is None:
        # Preserve old briefs and optional review tooling without requiring the
        # agent to author a second copy of every observation on the fast path.
        return [{'feature_index': i + 1, 'photo_evidence': feature,
                 'render_as': feature + '；用本次选定画风概括，保持其方向与个体差异',
                 'emphasis': 'preserve', 'do_not_change': '不改变照片的年龄、可见遮挡和该特征的辨识关系'}
                for i, feature in enumerate(features)]
    if not isinstance(supplied, list) or len(supplied) != len(features):
        raise ValueError('identity_plan 必须逐项覆盖 identity_features，不可遗漏或只用配饰替代面部特征')
    result, indices = [], set()
    for item in supplied:
        if not isinstance(item, dict):
            raise ValueError('identity_plan 的每一项必须是对象')
        index = item.get('feature_index')
        if type(index) is not int or not 1 <= index <= len(features) or index in indices:
            raise ValueError('identity_plan.feature_index 必须为从1开始且不重复的特征编号')
        indices.add(index)
        for key in ('photo_evidence', 'render_as', 'do_not_change'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f'identity_plan 缺少非空的 {key}')
        if item.get('emphasis') not in ('preserve', 'emphasize'):
            raise ValueError('identity_plan.emphasis 必须为 preserve 或 emphasize')
        result.append({key: item[key] for key in
                       ('feature_index', 'photo_evidence', 'render_as', 'emphasis', 'do_not_change')})
    if sum(item['emphasis'] == 'emphasize' for item in result) > 2:
        raise ValueError('最多加强两项主特征，其余保留；不能同时夸大所有五官')
    return sorted(result, key=lambda item: item['feature_index'])


def photo_identity_plan_for(brief):
    """Describe what the image model must read, without asserting observations."""
    supplied = brief.get('identity_plan')
    if supplied is None:
        requirements = [
            '直接查看图1，读取可见脸型、下颌轮廓及五官之间的比例和位置关系',
            '直接查看图1，读取发型长短、体积、分缝、刘海遮挡和原有卷度，提取整体剪影',
            '直接查看图1，读取表情、视线、眉眼关系和左右差异；眼部只转译为统一实心符号',
            '直接查看图1，读取头部方向、倾斜和肩线之间的关系',
            '直接查看图1，读取可见衣领、实际配饰及它们与人物的遮挡关系',
        ]
        features = brief.get('identity_features')
        if features is not None:
            if not isinstance(features, list) or len(features) < 3 or any(
                    not isinstance(feature, str) or not feature.strip() for feature in features):
                raise ValueError('identity_features 若提供，必须包含至少 3 个非空人物描述')
            # Supplied text remains a condition to check against the image; it
            # never becomes an observation attributed to this preparation step.
            requirements.extend('按图1可见依据核对并保留补充描述：' + feature for feature in features)
        return [
            {'feature_index': index + 1, 'requirement': requirement,
             'render_as': '由生图模型从图1提取该项可见关系，按本次画风概括，保持个体差异',
             'emphasis': 'preserve',
             'do_not_change': '保留照片可见年龄、不对称和遮挡；看不清处不猜补，不套通用幼态脸'}
            for index, requirement in enumerate(requirements)
        ]
    if not isinstance(supplied, list) or len(supplied) < 3:
        raise ValueError('photo 来源的 identity_plan 必须包含至少 3 项照片读取要求')
    result, indices = [], set()
    for item in supplied:
        if not isinstance(item, dict):
            raise ValueError('identity_plan 的每一项必须是对象')
        index = item.get('feature_index')
        if type(index) is not int or not 1 <= index <= len(supplied) or index in indices:
            raise ValueError('identity_plan.feature_index 必须为从1开始且不重复的特征编号')
        indices.add(index)
        if 'photo_evidence' in item:
            raise ValueError('photo 来源的 identity_plan 使用 requirement，不得把读取要求标为 photo_evidence')
        for key in ('requirement', 'render_as', 'do_not_change'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f'identity_plan 缺少非空的 {key}')
        if item.get('emphasis') not in ('preserve', 'emphasize'):
            raise ValueError('identity_plan.emphasis 必须为 preserve 或 emphasize')
        result.append({key: item[key] for key in
                       ('feature_index', 'requirement', 'render_as', 'emphasis', 'do_not_change')})
    if sum(item['emphasis'] == 'emphasize' for item in result) > 2:
        raise ValueError('最多加强两项主特征，其余保留；不能同时夸大所有五官')
    return sorted(result, key=lambda item: item['feature_index'])


def single_variant_plan(color_plan, color_mode):
    """Freeze exact local fill roles while retaining complete source palettes."""
    plan = deepcopy(color_plan)
    roles = plan['roles']
    if color_mode == 'natural' and not re.fullmatch(r'#[0-9a-fA-F]{6}', roles.get('hair', '')):
        raise ValueError('natural 单图需要在 brief.color_roles.hair 提供已观察的原照发色 #RRGGBB；编码底稿不能还原原照发色，不猜测或退回模型直接上色')
    for role in ('outline', 'skin_base', 'skin_shadow', 'hair', 'clothing', 'background'):
        value = roles.get(role)
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError(f'单图本地填色需要明确的 {role} #RRGGBB，不能从参考图猜测角色颜色')
        roles[role] = value.upper()
    # Complete source colorways already carry their own sampled accent/detail.
    # Ordinary single palettes retain the historical default for these roles.
    roles.setdefault('cheek', '#F6B4BE')
    roles.setdefault('detail', '#FFFFFF')
    plan['variant_index'] = 1
    plan['color_text'] = '；'.join(f'{key}: {value}' for key, value in roles.items())
    return plan


def prepare(brief, brief_path, out_dir):
    variant_count = brief.get('variants', 1)
    if type(variant_count) is not int or variant_count not in (1, 4):
        raise ValueError('variants 必须为 1 或 4')
    stage = brief.get('stage', 'preview')
    if stage not in ('preview', 'final'):
        raise ValueError('stage 必须为 preview 或 final；高清阶段仅在用户对话确认后调用')
    workflow = brief.get('workflow', 'fast')
    if workflow not in ('fast', 'review'):
        raise ValueError('workflow 必须为 fast 或 review')
    model = brief.get('model')
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError('model 若提供，必须为非空字符串；由全局 gen-img 校验和过滤')
    quality = brief.get('quality', 'low' if stage == 'preview' else 'high')
    if not isinstance(quality, str) or not quality.strip():
        raise ValueError('quality 必须为非空字符串')
    photo = Path(brief['photo']).expanduser()
    if not photo.is_absolute():
        photo = brief_path.parent / photo
    photo = photo.resolve()
    if not photo.is_file():
        raise ValueError(f'照片路径不存在: {photo}')
    approved_preview = brief.get('approved_preview')
    if approved_preview is not None:
        if stage != 'final':
            raise ValueError('approved_preview 仅用于用户已确认后的 final 阶段')
        if not isinstance(approved_preview, str) or not approved_preview.strip():
            raise ValueError('approved_preview 必须为已确认预览的文件路径')
        approved_preview = Path(approved_preview).expanduser()
        if not approved_preview.is_absolute():
            approved_preview = brief_path.parent / approved_preview
        approved_preview = approved_preview.resolve()
        if not approved_preview.is_file():
            raise ValueError(f'已确认预览不存在: {approved_preview}')
    identity_source = brief.get('identity_source', 'observations')
    if identity_source not in ('photo', 'observations'):
        raise ValueError('identity_source 必须为 photo 或 observations')
    if identity_source == 'photo':
        identity_plan = photo_identity_plan_for(brief)
        features = [item['requirement'] for item in identity_plan]
        expression = '由生图模型直接从图1读取可见表情、视线及眉眼关系，保留含义与左右差异'
        pose = '由生图模型直接从图1读取头肩方向、倾斜及肩线关系，不猜补被遮挡结构'
        for key in ('expression', 'pose'):
            if key in brief and (not isinstance(brief[key], str) or not brief[key].strip()):
                raise ValueError(f'{key} 若提供，必须为非空字符串')
        if 'expression' in brief:
            expression = ('执行用户明确表情与视线要求：' + brief['expression'] +
                          '；其余可见眉眼关系与左右差异由生图模型从图1读取并保留')
        if 'pose' in brief:
            pose = ('执行用户明确头肩姿态要求：' + brief['pose'] +
                    '；其余可见头肩结构由生图模型从图1读取，不猜补遮挡处')
        plan_source = 'photo_requirements'
    else:
        features = brief.get('identity_features')
        if not isinstance(features, list) or len(features) < 3 or any(not isinstance(s, str) or not s.strip() for s in features):
            raise ValueError('identity_features 必须包含至少 3 个从照片观察到的非空人物特征')
        identity_plan = identity_plan_for(brief, features)
        for key in ('expression','pose'):
            if not isinstance(brief.get(key), str) or not brief[key].strip():
                raise ValueError(f'缺少从照片观察到的 {key}')
        expression, pose = brief['expression'], brief['pose']
        plan_source = 'explicit' if 'identity_plan' in brief else 'legacy_identity_features'
    if 'hd_reference_id' in brief and 'palette_id' in brief:
        raise ValueError('hd_reference_id 与旧版 palette_id 是独立编号，请只指定一项')
    palette_id = brief.get('palette_id')
    if 'palette_id' in brief:
        if type(palette_id) is not int or not 1 <= palette_id <= 100:
            raise ValueError('旧版 palette_id 必须为 1–100 的整数')
        catalog = json.loads((SKILL/'references/palette-library.json').read_text(encoding='utf-8'))
        record = catalog['portraits'][palette_id-1]
        if record['id'] != palette_id:
            raise ValueError('旧版色库编号顺序不正确')
        reference_set = 'legacy'
    else:
        hd_id = brief.get('hd_reference_id', 25)
        if type(hd_id) is not int:
            raise ValueError('hd_reference_id 必须为现有高清参考的整数编号')
        catalog = json.loads((SKILL/'references/finished-reference-library.json').read_text(encoding='utf-8'))
        record = next((r for r in catalog['portraits'] if r['id'] == hd_id), None)
        if record is None:
            raise ValueError(f'不存在 HD-{hd_id:03d}；高清参考保留原编号，51 缺号')
        reference_set = 'finished'
    style_image = SKILL / record['reference_image']
    if not style_image.is_file():
        raise ValueError(f'缺少风格参考图片: {style_image}')
    mode = brief.get('mode', 'auto')
    if mode == 'auto':
        mode = record['technique']
    if mode not in MODES:
        raise ValueError('mode 必须为 auto 或 ' + ', '.join(MODES))
    color_mode = brief.get('color_mode', 'expressive')
    if color_mode not in ('natural','expressive'):
        raise ValueError('color_mode 必须为 natural 或 expressive')
    if color_mode != 'expressive':
        raise ValueError('单图与四图均须使用完整同源方案，natural 已停用')
    if variant_count == 4:
        from variant_plans import make_variant_plans
        variant_plans = make_variant_plans(brief, None, record, reference_set,
                                          color_mode, color_plan_for)
    else:
        variant_plans = [single_variant_plan(
            color_plan_for(brief, record, reference_set, color_mode), color_mode)]
    color_plan = dict(variant_plans[0])
    # Store one copy of the background decision, separately from the palette.
    background = color_plan.pop('background_plan')
    lines = color_plan.pop('line_plan')
    color_roles = color_plan['color_text']
    color_source = (f"HD-{color_plan['source_hd_id']:03d}" if color_plan['source_hd_id'] is not None else f"旧版{record['id']:03d}")
    palette_summary = f"整套沿用原作{color_source}（{color_plan['id']}）的角色色与渐变，不跨图拼色。"
    color_instructions = '照片仅决定结构神态；肤色、肤影、背景、发衣、腮红、细节、线色及渐变全部沿用同一原作，不独立换色。'
    # Historical native output migrates to the fixed square default.
    size_policy = brief.get('size_policy', 'square')
    if size_policy == 'native':
        size_policy = 'square'
    if size_policy not in ('square', 'explicit'):
        raise ValueError('size_policy 必须为 square 或 explicit')
    size, render_size, aspect = DEFAULT_SIZE, DEFAULT_SIZE, '正方形'
    if size_policy == 'explicit':
        size = brief.get('size')
        render_size = brief.get('render_size', size)
        for key, value in [('size', size), ('render_size', render_size)]:
            if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}', value):
                raise ValueError(f'{key} 应为宽x高，例如 1000x1000')
            w, h = (int(v) for v in value.split('x'))
            if w != h:
                raise ValueError(f'{key} 的显式交付目前只支持正方形，不能拉伸或擅自裁切')
        if int(render_size.split('x')[0]) < int(size.split('x')[0]):
            raise ValueError('render_size 不得小于交付 size，避免放大冒充高清')
        aspect = '正方形'
    for key in ('clothing','framing','user_notes','stylization','shadow_plan'):
        if key in brief and (not isinstance(brief[key],str) or not brief[key].strip()):
            raise ValueError(f'{key} 若提供，必须为非空字符串')
    values = {
        'identity_features': '；'.join(features), 'expression':expression, 'pose':pose,
        'identity_plan': '\n'.join(
            f"{item['feature_index']}. " +
            (f"读取要求：{item['requirement']}" if identity_source == 'photo' else
             f"照片依据：{item['photo_evidence']}") + f"；画成：{item['render_as']}；"
            f"处理：{'同方向适度加强' if item['emphasis'] == 'emphasize' else '保留辨识关系'}；"
            f"不可改变：{item['do_not_change']}" for item in identity_plan),
        'stylization':brief.get('stylization','从照片可见的辨识特征中选 1–2 项适度放大，可加强已有的头倾、视线或表情；保持个体轮廓与五官关系，次要信息简化，不要求 1:1 复刻角度。'),
        'shadow_plan':brief.get('shadow_plan','依据照片头肩结构与参考的简化光向，按需要安排一块脸侧结构暗面和下颌投在颈部的硬边影；在发根、耳后或领口仅补必要接触暗部。暗面留在对应表面，边界通常不另描线；皮肤暗色与腮红可复用但形状和作用分开。不加人物落地影或背景悬浮投影，不把皮肤画成写实光照。'),
        'clothing':brief.get('clothing','沿照片保留可见衣领、实际配饰与遮挡，不添加参考中的物品'),
        'mode_instructions':MODES[mode], 'palette_summary':palette_summary, 'color_roles':color_roles,
        'color_instructions':color_instructions,
        'gradient_instructions':color_plan['gradient_instructions'],
        'background_instructions':background['instructions'],
        'line_instructions':lines['short_instructions'] if workflow == 'fast' else lines['instructions'],
        # Deliberately leave subject-specific hair/props out of the prompt. The
        # selected crop remains available visually as a style-only reference.
        'transferable_cues': '借用参考中的轮廓概括、特征选择与适度夸张的方法、平涂/渐变方式、腮红形状和背景色彩关系；夸张应用于照片人物已有特征',
        'framing': FRAMING_INSTRUCTIONS + (' 本次补充：' + brief['framing'] if brief.get('framing_policy') == 'custom' and brief.get('framing') else ''),
        'size':render_size,
        'delivery_size':size,
        'user_notes':brief.get('user_notes','无额外要求'),
    }
    # The ordinary route states observations once. Keep the detailed template
    # available for explicitly requested review, not every portrait conversion.
    if workflow == 'fast':
        if identity_source == 'photo':
            values['identity_drawing'] = '由生图模型直接查看图1并提取人物特征，以下是读取要求，不是已完成的观察：'
            if 'identity_plan' in brief:
                values['identity_drawing'] += '；'.join(
                    ('适度加强：' if item['emphasis'] == 'emphasize' else '保留：') +
                    item['requirement'] + '；画成：' + item['render_as'] +
                    '（' + item['do_not_change'] + '）' for item in identity_plan)
            else:
                values['identity_drawing'] += '；'.join(features)
        elif 'identity_plan' in brief:
            values['identity_drawing'] = '；'.join(
                ('适度加强：' if item['emphasis'] == 'emphasize' else '保留：') +
                item['render_as'] + '（' + item['do_not_change'] + '）'
                for item in identity_plan)
        else:
            values['identity_drawing'] = '；'.join(features)
        # Only forward custom treatments when supplied; shared defaults live
        # once in the short template rather than being expanded per feature.
        if identity_source == 'photo':
            default_stylization = (
                '只加强逐项要求允许的特征，其余保留，不另选夸张目标。' if 'identity_plan' in brief else
                '从图1已可见特征中选择1–2项同方向适度加强，其余概括；不补造特征。')
        else:
            default_stylization = (
                '只加强逐项标注的特征，其余保留，不另选夸张目标。' if 'identity_plan' in brief else
                '选择已有的1–2项特征适度加强，其余概括；角度可适当调整。')
        values['fast_stylization'] = brief.get('stylization', default_stylization)
        values['fast_shadow'] = brief.get('shadow_plan', '少量脸侧硬边暗面、下颌颈影与接触暗部；暗形不描边，无背景投影。')
        values['fast_framing'] = values['framing']
        fast_color_policy = f"整套颜色来自原作{color_source}，不跨图拼色；旧brief/图3冲突色以本方案为准。"
        # Core ink and skin shadow have dedicated exact-value rules.
        fast_roles = '；'.join(f'{key}: {value}' for key, value in color_plan['roles'].items()
                              if key not in ('outline', 'skin_shadow'))
        values['fast_colors'] = fast_color_policy + '角色色：' + fast_roles
    template_name = 'avatar-fast-prompt.txt' if workflow == 'fast' else 'avatar-prompt.txt'
    template_text = (SKILL/'references'/template_name).read_text(encoding='utf-8')
    if identity_source == 'photo' and workflow == 'review':
        # The shared detailed template's observation labels belong to the
        # manual route. Relabel only this route without inventing photo facts.
        template_text = template_text.replace(
            '人物结构观察（其中颜色仅为照片事实，艺术配色按后述方案）：',
            '人物读取要求（由生图模型直接查看图1，以下不是已完成的人物观察）：')
        template_text = template_text.replace('照片表情：', '表情视线读取要求：')
        template_text = template_text.replace('照片头部与肩部姿势：', '头肩姿态读取要求：')
        template_text = template_text.replace('逐项人物转译与保留边界：', '逐项照片读取要求与保留边界：')
    template = Template(template_text)
    prompt = template.substitute(values)
    if stage == 'preview':
        prompt += '\n快速预览：脸型、发型、眉眼关系与神态清楚，遵守所选画法与局部渐变，少装饰。\n'
    if approved_preview is not None:
        prompt += '\n图3是用户已确认的预览；沿用其构图、人物处理、角色色与局部渐变，提高边缘清晰度；发型仍按本次简化规则合并发束、删去超出预算的内部线，不继承旧预览的复杂发丝或新增高光。图1仍决定人物结构，图2仍只提供画风，不重设计已确认内容。\n'
        prompt += '背景以本次单一纯色要求为准；原预览若含背景渐变或透明区域，也须改为本次指定纯色。\n'
    prompt += ('\n构图优先级：' + render_size + '、1:1及上述留白胸像优先于旧brief、图2/3的大头构图，其余已确认内容保留。\n')
    skin = color_plan['source_selection']['skin']
    bg = color_plan['source_selection']['background']
    if workflow == 'fast':
        prompt += (f"\n采样颜色锁定：肤面{skin['base']}、肤影{skin['shadow']}（HD-{skin['source_hd_id']:03d}肤色）；"
                   f"背景{bg['hex']}（HD-{bg['source_hd_id']:03d}背景）。按值使用，禁止发衣移作肤色或混出新肤色/背景；"
                   '优先于照片、图2、旧brief、图3配色。皮肤平涂，渐变只在发衣。\n')
    else:
        prompt += (f"\n采样颜色锁定：肤面只用{skin['base']}、皮肤硬边暗面只用{skin['shadow']}"
                   f"（原作HD-{skin['source_hd_id']:03d}肤色）；背景只用{bg['hex']}"
                   f"（原作HD-{bg['source_hd_id']:03d}背景），均按指定值。禁止将发衣色移作肤色、调色或合成新肤色/背景色；"
                   '照片、图2、旧brief和图3的冲突配色均以本锁定为准。皮肤平涂，渐变仅在发或衣。\n')
    # Apply after observations, custom treatments and approved-preview guidance
    # so no route silently restores the former detailed eye rendering.
    prompt += '\n主线与分类按本次库，覆盖旧brief、图2和旧预览线色。\n'
    if lines['hair_precedence']:
        prompt += '\n' + lines['hair_precedence'] + '\n'
    prompt += '\n' + EYE_PRECEDENCE + '\n统一眼睛：' + EYE_INSTRUCTIONS + '\n'
    if variant_plans:
        # Use one semantic master in every route, so exact skin values are
        # applied locally rather than left to model color reproduction.
        master_values = dict(values)
        master_values['master_identity'] = values.get('identity_drawing', values['identity_plan'])
        if identity_source == 'photo' and workflow == 'review':
            master_values['master_identity'] = ('由生图模型直接查看图1并提取人物特征，以下是读取要求，不是已完成的观察：\n' + values['identity_plan'])
        master_values['master_stylization'] = values.get('fast_stylization', values['stylization'])
        master_values['master_line_style'] = lines['family_instructions']
        rule_field = 'role_short_instructions' if workflow == 'fast' else 'role_instructions'
        master_values['master_role_rules'] = '；'.join(
            f'{role}：{rule}' for role, rule in lines[rule_field].items())
        master_values['master_hair_precedence'] = ''
        master_template = Template((SKILL/'references/avatar-master-prompt.txt').read_text(encoding='utf-8'))
        prompt = master_template.substitute(master_values)
        if 'shadow_plan' in brief:
            prompt += ('\n暗面形状与位置要求：' + values['shadow_plan']
                       + '；皮肤暗面仍只用#00FF00区域编码，不执行文字中的成品配色或渐变。\n')
        if approved_preview is not None:
            prompt += '\n图3是用户认可的单个头像预览，沿用人物神态，构图遵循本次留白胸像；重新输出上述区域编码底稿，禁止照搬其成品颜色。\n'
        if lines['hair_precedence']:
            prompt += '\n' + lines['hair_precedence'] + '\n'
        # Put the shared grammar after old observations, user notes and the
        # approved-preview instruction, with a single canonical copy.
        prompt += '\n' + EYE_PRECEDENCE + '\n统一眼睛：' + EYE_INSTRUCTIONS + '\n'
    if out_dir.exists():
        raise ValueError('输出目录已存在，请选择新目录以保留先前提示词')
    out_dir.mkdir(parents=True)
    prompt_path = out_dir/'avatar-prompt.txt'
    prompt_path.write_text(prompt,encoding='utf-8')
    argv = ['python3',str(GEN_IMG),'edit','--image',str(photo),'--image',str(style_image.resolve())]
    if approved_preview is not None:
        argv.extend(['--image', str(approved_preview)])
    argv.extend(['--prompt-file',str(prompt_path.resolve()),
                 '--output-format','png','--background','opaque','--quality',quality])
    argv.extend(['--size', render_size])
    if model is not None:
        argv.extend(['--model', model])
    result = {'status':'prepared','executed':False,'stage':stage,'quality':quality,'workflow':workflow,'palette_id':palette_id,'mode':mode,'color_mode':color_mode,
              'reference_set':reference_set,'reference_id':record['id'],'identity_source':identity_source,
              'size_policy':size_policy,'render_size':render_size,'delivery_size':size,
              'framing_plan': dict(FRAMING_PLAN),
              'color_plan':color_plan,
              'background_plan':background,
              'line_plan':lines,
              'delivery':{'format':'PNG','size':size,'preserve_original':True,'finalizer_script':str(SKILL/'scripts/finalize_avatar.py')},
              'prompt_file':str(prompt_path.resolve()),'photo':str(photo),'style_reference':str(style_image.resolve()),
              'cwd':str(Path.cwd()),'argv':argv,'shell_command':shlex.join(argv),
              'next_step':'Read the global gen-img SKILL.md, then run argv from the project workspace. No model is selected here.'}
    result['variants'] = variant_count
    result['variant_plans'] = variant_plans
    result['master_encoding'] = 'semantic-cube-v1'
    if approved_preview is not None:
        result['approved_preview'] = str(approved_preview)
    result['review_spec'] = {
        'schema_version': 1, 'identity_source': identity_source, 'identity_plan': identity_plan,
        'plan_source': plan_source,
        'expression_pose': f"表情：{expression}；姿态：{pose}；转译：{values['stylization']}",
        'style_lock': {
            'reference_set': reference_set, 'reference_id': record['id'], 'mode': mode,
            'color_mode': color_mode, 'color_roles': color_roles,
            'color_policy': color_instructions,
            'gradient': color_plan['gradient'],
            'gradient_visibility': {
                'required_per_image': True, 'allowed_regions': ['hair', 'clothing'],
                'criterion': '普通头像尺寸看清两端颜色、连续过渡及可辨认面积；微弱同色变化或细边不通过',
                'verification': 'final-rgb-local-check-plus-visual',
            },
            'background': background,
            'source_colors': color_plan['source_selection'],
            'source_colorway': color_plan['source_colorway'],
            'eye_style': {'id': EYE_STYLE_ID, 'instructions': EYE_INSTRUCTIONS},
            'lines': lines,
            'shadow_plan': values['shadow_plan'], 'framing': values['framing'],
            'framing_plan': dict(FRAMING_PLAN),
            'delivery_size': size,
        },
        'input_sha256': {
            'photo': hashlib.sha256(photo.read_bytes()).hexdigest(),
            'style_reference': hashlib.sha256(style_image.read_bytes()).hexdigest(),
        },
        'review_script': str(SKILL/'scripts/review_avatar.py'),
        'enabled': workflow == 'review',
        'max_automatic_corrections': 1 if workflow == 'review' else 0,
        'scope': '逐项视觉对照人物特征与画风，不是身份识别，不计算相似度分数',
    }
    result['next_step'] = (
        '通过全局 gen-img 从项目工作区调用一次，整理为不透明PNG；同一次看成品核对实心眼睛、人物特征、局部渐变及纯色对比背景，再展示；不自动重画。'
        if workflow == 'fast' else
        '通过全局 gen-img 从项目工作区调用一次，整理为正方形后按 quality-workflow.md 做显式请求的视觉自检。')
    if stage == 'preview':
        result['next_step'] += ' 本轮只展示预览并等待用户对话确认，不自动继续生成高清。'
    (out_dir/'generation-request.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brief',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        path=args.brief.resolve()
        brief=json.loads(path.read_text(encoding='utf-8'))
        result=prepare(brief,path,args.out_dir.resolve())
    except (ValueError,KeyError,OSError,TypeError) as exc:
        parser.exit(2,f'Error: {exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
