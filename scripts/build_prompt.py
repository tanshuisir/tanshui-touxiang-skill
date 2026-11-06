#!/usr/bin/env python3
"""Prepare a photo-edit prompt and gen-img argv; never submit an image request."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
from pathlib import Path
from string import Template

SKILL = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
GEN_IMG_SKILL = Path(os.environ.get('GEN_IMG_SKILL_DIR', str(CODEX_HOME / 'skills/gen-img'))).expanduser()
GEN_IMG = GEN_IMG_SKILL / 'scripts/run.py'
MODES = {
    'flat': '平涂大面为主，常规轮廓、实心眉眼和圆腮红，少量硬边暗面；局部必须保留指定渐变，不铺网点。',
    'gradient': '彩色平涂为基础，只在一两个头发、衣服或背景封闭区域作克制的二色渐变，主轮廓锐利，面部不作写实渐变。',
    'texture': '保持清楚平涂，只在照片原本可见的衣服区域加入与该服装相符的简化线纹或网点。保留照片服装类别，不照搬参考衣领或图案。',
    'bold': '使用有力、平顺、较粗的外轮廓，减少内部结构线和小细节；保持照片的头型、五官比例和年龄。',
    'cartoon': '用较粗轮廓、简化短眉眼、少量弧线和圆腮红概括成卡通头像。简化细节但保持照片面部结构和年龄，不统一成大眼幼态脸。',
    'duotone': '使用双色或少量同类色组织、单一主线、清楚负形留白与有限色块，保持人物轮廓与五官位置，不删除必要辨识信息。',
    'glitch': '先完成清楚高对比平面头像，再沿少量外轮廓加极窄青色和粉色偏移边，保留艺术角色色与指定渐变。保持脸部五官锐利，不做全脸重影、模糊或噪声文字。',
}


def color_plan_for(brief, record, reference_set, color_mode):
    """Choose art colors locally; never sample a photo's skin/hair/clothes."""
    library = json.loads((SKILL/'references/artistic-palettes.json').read_text(encoding='utf-8'))
    palettes = library['palettes']
    choice = brief.get('art_palette', 'auto')
    if not isinstance(choice, str):
        raise ValueError('art_palette 必须为 auto、reference 或艺术色组id')
    if choice == 'auto':
        palette = secrets.choice(palettes)
    elif choice == 'reference':
        palette = next((item for item in palettes if reference_set == 'finished' and
                        item['source_hd_id'] == record['id']), None)
        if palette is None:
            # Unlabelled samples cannot be assigned to skin/hair by frequency.
            # The actual style image supplies those roles visually instead.
            palette = {'id': 'reference', 'source_hd_id': record['id'] if reference_set == 'finished' else None,
                       'color_roles': record.get('sampled_color_roles', {}),
                       'gradient': {'region': 'background', 'from': '#FFDA74',
                                    'to': '#97DFF0', 'direction': '从上到下'}}
    else:
        palette = next((item for item in palettes if item['id'] == choice), None)
        if palette is None:
            raise ValueError('未知 art_palette: ' + choice)
    roles = dict(palette['color_roles'])
    if color_mode == 'natural':
        roles = {key: value for key, value in roles.items() if key not in ('skin_base', 'hair')}
    custom_roles = brief.get('color_roles')
    if custom_roles is not None:
        if not isinstance(custom_roles, dict) or not custom_roles or any(
                not isinstance(value, str) or not value.strip() for value in custom_roles.values()):
            raise ValueError('color_roles 必须为非空字符串值组成的对象')
        roles.update(custom_roles)
    raw_gradient = brief.get('gradient', palette['gradient'])
    if not isinstance(raw_gradient, dict):
        raise ValueError('gradient 必须为包含 region/from/to 的对象')
    gradient = dict(raw_gradient)
    if gradient.get('region') not in ('hair', 'clothing', 'background'):
        raise ValueError('gradient.region 必须为 hair、clothing 或 background')
    for key in ('from', 'to'):
        if not isinstance(gradient.get(key), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', gradient[key]):
            raise ValueError('gradient.from/to 必须为 #RRGGBB')
    if gradient['from'].lower() == gradient['to'].lower():
        raise ValueError('渐变起止色不能相同')
    if not isinstance(gradient.get('direction', '从上到下'), str) or not gradient.get('direction', '从上到下').strip():
        raise ValueError('gradient.direction 必须为非空字符串')
    gradient.setdefault('direction', '从上到下')
    # A partial override of the gradient's region must influence its start;
    # otherwise the palette and the explicit region color would contradict.
    if 'gradient' not in brief and custom_roles:
        region_color = custom_roles.get(gradient['region'])
        if isinstance(region_color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', region_color):
            gradient['from'] = region_color
            if gradient['from'].lower() == gradient['to'].lower():
                gradient['to'] = palette['gradient']['from']
    if color_mode == 'natural' and gradient['region'] == 'hair':
        # Natural is an explicit compatibility mode. Keep its gradient in the
        # background so it cannot require an invented natural hair color.
        gradient['region'] = 'background'
        gradient['direction'] = '从上到下'
    distance = sum((int(gradient['from'][i:i+2], 16) - int(gradient['to'][i:i+2], 16))**2
                   for i in (1, 3, 5)) ** 0.5
    if distance < 24:
        raise ValueError('渐变起止色差过小，必须在正常头像尺寸下清楚可见')
    color_text = '；'.join(f'{key}: {value}' for key, value in roles.items())
    if not color_text:
        color_text = '按图2实际角色重组背景、主线、肤面、头发与服装颜色，不按采样频率硬套'
    region = {'hair': '头发', 'clothing': '衣服', 'background': '背景'}[gradient['region']]
    gradient_text = (f"必须在{region}的一个清楚可见色块内，{gradient['direction']}由{gradient['from']}连续过渡至"
                     f"{gradient['to']}；若该区域不可见则放背景。渐变有可见面积和色差、外缘锐利，"
                     '渐变端点优先于该区域基色；不能用两块硬切色、亮线或噪点代替，不给全脸刷柔焦渐变。')
    return {'id': palette['id'], 'source_hd_id': palette['source_hd_id'],
            'roles': roles, 'gradient': gradient, 'color_text': color_text,
            'gradient_instructions': gradient_text}


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


def prepare(brief, brief_path, out_dir):
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
    features = brief.get('identity_features')
    if not isinstance(features, list) or len(features) < 3 or any(not isinstance(s, str) or not s.strip() for s in features):
        raise ValueError('identity_features 必须包含至少 3 个从照片观察到的非空人物特征')
    identity_plan = identity_plan_for(brief, features)
    for key in ('expression','pose'):
        if not isinstance(brief.get(key), str) or not brief[key].strip():
            raise ValueError(f'缺少从照片观察到的 {key}')
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
    if mode in ('duotone','glitch') and color_mode == 'natural':
        raise ValueError('双色/同色系/黑白偏色边会重新组织肤发颜色；选择 expressive，或改用 flat 保留自然色')
    color_plan = color_plan_for(brief, record, reference_set, color_mode)
    color_roles = color_plan['color_text']
    color_source = (f"HD-{color_plan['source_hd_id']:03d}" if color_plan['source_hd_id'] is not None else f"旧版{record['id']:03d}")
    palette_summary = (f"本次艺术色组 {color_plan['id']}，参考{color_source}的色彩关系与角色重分配；"
                       '不是作者源工程色板；本次角色色和渐变端点优先于图2原配色。')
    color_instructions = (
        '本次明确选natural：保留照片肤发基调，衣服与背景按角色色重配；仍必须有一处局部渐变。'
        if color_mode == 'natural' else
        '艺术重配色：肤色、发色、服饰色和背景全部按下列方案，不受照片原色约束；肤面可黄、白、粉紫或青。照片中颜色词只是原照观察；旧brief内保留原色或禁止改色约束不再生效，本次角色色优先。只锁定脸型、五官关系、发型剪影、衣型与神态。'
    )
    size = brief.get('size', '512x512' if stage == 'preview' else '1000x1000')
    render_size = brief.get('render_size','1024x1024' if size == '1000x1000' else size)
    for key, value in [('size',size), ('render_size',render_size)]:
        if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}',value):
            raise ValueError(f'{key} 应为宽x高，例如 1000x1000')
        w,h=(int(v) for v in value.split('x'))
        if w != h:
            raise ValueError(f'{key} 必须为正方形；标准头像不能拉伸或擅自裁切')
    if int(render_size.split('x')[0]) < int(size.split('x')[0]):
        raise ValueError('render_size 不得小于交付 size，避免放大冒充高清')
    for key in ('clothing','framing','user_notes','stylization','shadow_plan'):
        if key in brief and (not isinstance(brief[key],str) or not brief[key].strip()):
            raise ValueError(f'{key} 若提供，必须为非空字符串')
    width,height=(int(v) for v in size.split('x'))
    aspect='正方形' if width==height else ('竖幅' if width<height else '横幅')
    values = {
        'identity_features': '；'.join(features), 'expression':brief['expression'], 'pose':brief['pose'],
        'identity_plan': '\n'.join(
            f"{item['feature_index']}. 照片依据：{item['photo_evidence']}；画成：{item['render_as']}；"
            f"处理：{'同方向适度加强' if item['emphasis'] == 'emphasize' else '保留辨识关系'}；"
            f"不可改变：{item['do_not_change']}" for item in identity_plan),
        'stylization':brief.get('stylization','从照片可见的辨识特征中选 1–2 项适度放大，可加强已有的头倾、视线或表情；保持个体轮廓与五官关系，次要信息简化，不要求 1:1 复刻角度。'),
        'shadow_plan':brief.get('shadow_plan','依据照片头肩结构与参考的简化光向，按需要安排一块脸侧结构暗面和下颌投在颈部的硬边影；在发根、耳后或领口仅补必要接触暗部。暗面留在对应表面，边界通常不另描线；皮肤暗色与腮红可复用但形状和作用分开。不加人物落地影或背景悬浮投影，不把皮肤画成写实光照。'),
        'clothing':brief.get('clothing','沿照片保留可见衣领、实际配饰与遮挡，不添加参考中的物品'),
        'mode_instructions':MODES[mode], 'palette_summary':palette_summary, 'color_roles':color_roles,
        'color_instructions':color_instructions,
        'gradient_instructions':color_plan['gradient_instructions'],
        # Deliberately leave subject-specific hair/props out of the prompt. The
        # selected crop remains available visually as a style-only reference.
        'transferable_cues': '借用参考中的轮廓概括、特征选择与适度夸张的方法、平涂/渐变方式、腮红形状和背景色彩关系；夸张应用于照片人物已有特征',
        'framing':brief.get('framing',f'{aspect}头肩像，以照片头部角度和肩线为起点，按特征转译方案处理倾斜与动作节奏，头顶留白，肩部可在下缘裁切，脸与关键配饰位于中心安全区'),
        'size':render_size, 'delivery_size':size, 'user_notes':brief.get('user_notes','无额外要求'),
    }
    # The ordinary route states observations once. Keep the detailed template
    # available for explicitly requested review, not every portrait conversion.
    if workflow == 'fast':
        if 'identity_plan' in brief:
            values['identity_drawing'] = '；'.join(
                ('适度加强：' if item['emphasis'] == 'emphasize' else '保留：') +
                item['render_as'] + '（' + item['do_not_change'] + '）'
                for item in identity_plan)
        else:
            values['identity_drawing'] = '；'.join(features)
        # Only forward custom treatments when supplied; shared defaults live
        # once in the short template rather than being expanded per feature.
        values['fast_stylization'] = brief.get('stylization',
            '只加强逐项标注的特征，其余保留，不另选夸张目标。' if 'identity_plan' in brief else
            '选择已有的1–2项特征适度加强，其余概括；角度可适当调整。')
        values['fast_shadow'] = brief.get('shadow_plan', '少量脸侧硬边暗面、下颌颈影和必要接触暗部，暗形不另描边，不加背景投影。')
        values['fast_framing'] = brief.get('framing', '单人头肩像，头顶留白，肩部延伸至下缘，省略手机、手和原背景。')
        values['fast_colors'] = color_instructions + '角色色：' + color_roles
    template_name = 'avatar-fast-prompt.txt' if workflow == 'fast' else 'avatar-prompt.txt'
    template = Template((SKILL/'references'/template_name).read_text(encoding='utf-8'))
    prompt = template.substitute(values)
    if stage == 'preview':
        prompt += '\n本轮为小尺寸预览，优先让脸型、发型、眉眼关系和神态清楚可辨；保持所选画法与必需局部渐变，减少微小装饰。\n'
    if approved_preview is not None:
        prompt += '\n图3是用户已确认的预览；沿用其构图、人物处理、角色色与局部渐变，只提高线条和细节清晰度。图1仍决定人物结构，图2仍只提供画风，不重设计已确认内容。\n'
    if out_dir.exists():
        raise ValueError('输出目录已存在，请选择新目录以保留先前提示词')
    out_dir.mkdir(parents=True)
    prompt_path = out_dir/'avatar-prompt.txt'
    prompt_path.write_text(prompt,encoding='utf-8')
    argv = ['python3',str(GEN_IMG),'edit','--image',str(photo),'--image',str(style_image.resolve())]
    if approved_preview is not None:
        argv.extend(['--image', str(approved_preview)])
    argv.extend(['--prompt-file',str(prompt_path.resolve()),'--size',render_size,'--output-format','png','--quality',quality])
    if model is not None:
        argv.extend(['--model', model])
    result = {'status':'prepared','executed':False,'stage':stage,'quality':quality,'workflow':workflow,'palette_id':palette_id,'mode':mode,'color_mode':color_mode,
              'reference_set':reference_set,'reference_id':record['id'],'render_size':render_size,'delivery_size':size,
              'color_plan':color_plan,
              'delivery':{'format':'PNG','size':size,'preserve_original':True,'finalizer_script':str(SKILL/'scripts/finalize_avatar.py')},
              'prompt_file':str(prompt_path.resolve()),'photo':str(photo),'style_reference':str(style_image.resolve()),
              'cwd':str(Path.cwd()),'argv':argv,'shell_command':shlex.join(argv),
              'next_step':'Read the global gen-img SKILL.md, then run argv from the project workspace. No model is selected here.'}
    if approved_preview is not None:
        result['approved_preview'] = str(approved_preview)
    result['review_spec'] = {
        'schema_version': 1, 'identity_plan': identity_plan,
        'plan_source': 'explicit' if 'identity_plan' in brief else 'legacy_identity_features',
        'expression_pose': f"表情：{brief['expression']}；姿态：{brief['pose']}；转译：{values['stylization']}",
        'style_lock': {
            'reference_set': reference_set, 'reference_id': record['id'], 'mode': mode,
            'color_mode': color_mode, 'color_roles': color_roles,
            'color_policy': color_instructions,
            'gradient': color_plan['gradient'],
            'shadow_plan': values['shadow_plan'], 'framing': values['framing'],
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
        '通过全局 gen-img 从项目工作区调用一次，整理实际输出尺寸后立即展示交付PNG；不自动复检或重画。'
        if workflow == 'fast' else
        '通过全局 gen-img 从项目工作区调用一次，整理尺寸后按 quality-workflow.md 做显式请求的视觉自检。')
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
