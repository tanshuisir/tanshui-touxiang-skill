#!/usr/bin/env python3
"""Prepare visual comparisons and validate evidence-backed avatar review records.

No face recognition, similarity score, model request, or image retouching. Passing
requires an agent to actually view and compare the photo, result, and style image.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

VERDICTS = {'unreviewed', 'pass', 'fail', 'uncertain'}
VIEW_FLAGS = ('photo_viewed', 'image_viewed', 'style_reference_viewed', 'thumbnail_viewed')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def load_request(path):
    path = Path(path).resolve()
    request = json.loads(path.read_text(encoding='utf-8'))
    if request.get('review_spec', {}).get('schema_version') != 1:
        raise ValueError('请求缺少自检计划；请用当前 build_prompt.py 重新准备，不会提交生图')
    return path, request


def checks_for(request):
    checks = []
    for i, item in enumerate(request['review_spec']['identity_plan']):
        check = {'id': f'identity.{i + 1}', 'expected': item['render_as'],
                 'emphasis': item['emphasis'], 'do_not_change': item['do_not_change']}
        source_key = 'requirement' if request['review_spec'].get('plan_source') == 'photo_requirements' else 'photo_evidence'
        check[source_key] = item[source_key]
        checks.append(check)
    checks += [
        {'id': 'expression_pose', 'expected':
         '保留照片神态、视线及头肩关系；只接受计划中同方向的适度夸张。'
         + request['review_spec']['expression_pose']},
        {'id': 'age_asymmetry', 'expected': '保留照片可见年龄感、个体比例和不对称，不套通用美化脸或幼态脸'},
        {'id': 'props_occlusion', 'expected': '配饰、衣领、道具及遮挡来自照片或用户要求，不移植参考人物物品，不补不可见关键五官'},
        {'id': 'anatomy', 'expected': '头颈肩、耳根、镜腿及可见手部接触关系合理，没有多余手指或穿插结构'},
        {'id': 'style', 'expected': '保持本次选定参考的平顺轮廓、五官符号、色面、腮红与主模式；'
         + json.dumps(request['review_spec']['style_lock'], ensure_ascii=False)},
        {'id': 'art_color_gradient', 'expected': '肤发、服饰和背景按本次角色色组织，不按照片颜色判人物一致性；'
         '有已采样渐变的模板版本保留连续二色渐变；纯平涂模板不补造渐变。有渐变时，在普通头像尺寸看清两端颜色与中间连续过渡，两端各占可辨认面积；微弱同色变化、细边、硬边色块/亮线/噪点不算；'
         + request.get('color_plan', {}).get('gradient_instructions', '渐变只在头发或服饰内部，背景为单一纯色')},
        {'id': 'shadow_detail', 'expected': '暗面留在对应脸、颈或衣面；线条、纹理与局部细节服从本次 shadow_plan，不改画风'},
        {'id': 'bottom_anchor', 'expected': '逐张单图检查衣服或身体连续区域到达画布最后一行；四宫格逐格贴底，不能只检查整张拼图底边。只在顶部与左右留白，人物下方没有背景横带，不以发梢或孤立像素冒充身体贴底。'},
        {'id': 'background_contrast', 'expected': '背景为均匀单一纯色，铺满整幅且不透明，与头发和服装等大色面形成清楚反差；'
         '背景须为本次模板精确采样色，允许模板白、近白和深色；'
         '禁止背景渐变、纹理、图案或投影；'
         '不能把透明区、查看器灰底或白色画板当作已绘制背景。'
         + request.get('background_plan', {}).get('instructions', '')},
        {'id': 'framing_readability', 'expected': '实际交付图及128像素缩略图中关键面部特征可读；按framing_plan核对头高、顶空、侧边留白与肩胸可见，避免大头挤满画面'},
    ]
    checks += [
        {'id': 'jaw_neck_shadow', 'expected': '可见下颌下方颈部有依头颈方向的同源skin_shadow硬边结构影；检查实际位置及可见色差，不能仅凭有此HEX或若干像素通过。禁衣服暗片不删除肤影。'},
        {'id': 'garment_occlusion_continuity', 'expected': '沿照片已见或用户明确要求的内搭、衣襟、领带及配饰追踪遮挡前后的对应关系；重新露出的部分须接续方向、宽度和部位色，不能全部变成外套色。手臂/头发/道具只遮住实际覆盖范围，后方轮廓不画穿前景；完全隐藏或仍在画外的部分不强行露出，不新增无依据的领结或部件。'},
        {'id': 'garment_accents', 'expected': '核对同源内搭、领袖滚边和装饰辅色；白底也保留服饰细节。用户要求增强时可添加少量同源滚边/几何小装饰，保留原照衣型；不加模板首饰/标志，不借肤发背景色，不用粗阴影代替装饰。'},
        {'id': 'light_cheeks', 'expected': '模板有腮红、面颊可见时男女均保留，侧脸保留可见一侧，不能省略；对照各版模板cheek采样，轻淡程度一致；无深色圆块、描边；腮红内区平涂、边界平顺，无点状颗粒、散点、杂色、锯齿或描边式断点；正常抗锯齿保留。皮肤内不能出现服饰色误码。'},
        {'id': 'jewelry_cleanliness', 'expected': '项链等配饰沿照片保留形状和遮挡；连续轮廓、少量完整色面，内部无针尖杂点、编码杂色、密集网纹或细碎链节。明确银色时仅该配饰用干净银白/浅灰面，保留必要主线；不得误改皮肤或衣服，不把所有首饰默认银色。'},
        {'id': 'symbol_mouth', 'expected': '嘴形先按本次明确要求，再按原照片判断：默认 `mouth_style: auto` 区分闭嘴、微张与露齿；闭嘴且没有辨识性唇形时用符号口线，双唇清楚可见且确为人物特征时可保留简化双唇，微张与露齿保留相应开口和嘴角。不能把所有嘴都缩成短线或复制模板的厚唇。明确的 `line` 只用口线，`upper-lip` 用简化上唇配独立短下唇线，`full-lips` 允许简化双唇；明确“不露牙”时不画牙齿。所有模式均为平面概括，无写实唇纹、高光或唇部体积；不按性别决定唇形，腮红编码不作唇色。'},
        {'id': 'toothy_smile_proportions', 'expected': '露齿表情先保留原照嘴角方向、开口与笑容，再概括唇形：牙齿用一块干净连续的浅色面，不逐颗分割、不画牙龈；上唇以细轮廓概括，下唇仅用短弧或省略，不用一圈浓色厚唇包住牙齿。嘴宽、开口高度和唇厚按原照相对面部的比例，不得沿用模板的夸大厚唇，也不能因简化而把露齿笑画成闭嘴。牙齿只用同套色板中已有的白或近白浅色；detail角色可能是粉色或深色，不能未经判断就当作牙色。编码底稿仍将牙区独立画为detail；若同套detail不适合作牙色，成品需按已观察的明确牙齿局部蒙版，复用同套已有白/近白色重填并记录，仅修改牙区，不改全局detail映射；不能可靠分出牙区时停止说明。不借腮红、发色或服饰色涂牙。007的男性露齿笑按此处理；性别不替代对原照结构的判断，原有明确双唇与闭嘴要求继续按本次指令执行。'},
        {'id': 'strap_and_bag_roles', 'expected': '肩带逐侧核对数量、宽度、扣件与衣片的连接：照片可见或本次明确要求的第二条不能遗漏；真实遮挡保留，不强行穿过头发或手臂。用服饰底色加细轮廓/缝线表达，不能把整条肩带和扣件合成粗实心墨块。背包、背包肩带、胸带和内搭按实际部件区分，明暗分配服从照片或本次明确要求，不把背包与内搭的色位颠倒；不将某次“深背包、浅内搭”推广到所有照片。'},
        {'id': 'line_folds', 'expected': '褶皱为细疏、圆端且随衣片受力的结构曲线；无粗楔形/镰刀形填充或大块投影。真实衣层、花纹、领袖和模板衣料渐变保留。即使暗片与主线同色、或连着外轮廓，也属于禁用填充衣褶；逐段检查线条是否仍是细线，不能仅凭没有clothing_shadow编码判通过。'},
    ]
    # Use the request's frozen criteria, with no extra model call.
    checks.extend(dict(item) for item in request['review_spec'].get('confirmed_corrections', {}).get('checks', []))
    eye_style = request['review_spec']['style_lock'].get('eye_style')
    if request['review_spec'].get('garment_layers'):
        checks.append({'id':'garment_layers','expected':
                       '对照照片逐件确认外套、内搭、领口、领结、帽饰与道具；两件衣服独立且可辨色。'
                       '单衣用真实领袖、同源服饰辅色、模板衣料渐变和细结构线；禁止粗楔形暗片或投影式填充。'
                       '花纹、纽扣、带扣、口袋来自照片或用户本次明确增强服饰的要求；格纹/条纹跟随衣片，不侵入皮肤。'
                       '服饰色对照该版garment_plan的原图坐标；旧底稿没有的内层不能靠程序猜出。'})
    if eye_style:
        checks.append({'id': 'eye_style', 'expected': eye_style['instructions']})
    source_colors = request['review_spec']['style_lock'].get('source_colors')
    if source_colors:
        checks.append({'id': 'source_skin_background', 'expected':
                       '肤面及皮肤暗面严格使用70张模板库内同一模板的指定HEX，不能调亮、调暗、混色或新增皮肤高光；'
                       '腮红和线条为独立角色，边缘抗锯齿不作为新肤色。背景为本次模板背景采样的模板单色；'
                       '若编码语义分错区导致发衣色落入皮肤，仍判失败，不因填色程序通过就声称合格。'
                       + json.dumps(source_colors, ensure_ascii=False)})
    for index, plan in enumerate(request.get('variant_plans', []), 1):
        if plan.get('source_colorway'):
            checks.append({'id': f'source_colorway.{index}', 'expected':
                           f'第{index}版逐角色对照其对应模板TS-{plan["source_hd_id"]:03d}；'
                           '肤面/肤影、模板纯色背景、发衣、腮红、细节、主线和人物渐变均沿用该套来源，'
                           '不能全部按造型参考025判配色。分区语义错误或库外肤色仍判失败。'
                           + json.dumps({'source_colorway': plan['source_colorway'],
                                         'roles': plan['roles'], 'gradient': plan['gradient'],
                                         'garment_plan':plan.get('garment_plan')}, ensure_ascii=False)})
    source_colorway = request['review_spec']['style_lock'].get('source_colorway')
    if source_colorway:
        checks.append({'id': 'complete_source_colorway', 'expected':
                       '单图与四图逐版核对同一张模板的肤色、肤影、背景、头发、服装、腮红、细节、主线与渐变；'
                       '全部角色必须保持该模板的配对关系，不能因各颜色分别在库内而接受跨模板混搭。'
                       + json.dumps(source_colorway, ensure_ascii=False)})
    return checks


def bindings_for(request_path, request, image):
    files = {'request': request_path, 'photo': Path(request['photo']),
             'style_reference': Path(request['style_reference']), 'image': Path(image).resolve()}
    result = {}
    for key, path in files.items():
        if not path.is_file():
            raise ValueError(f'自检输入不存在: {path}')
        result[key] = {'path': str(path.resolve()), 'sha256': digest(path)}
    for key in ('photo', 'style_reference'):
        expected = request['review_spec']['input_sha256'][key]
        if result[key]['sha256'] != expected:
            raise ValueError(f'{key} 已不同于准备提示词时的文件，须重新准备，不能沿用旧自检')
    return result


def automatic_checks(image, request):
    size = request.get('delivery_size', 'native')
    target = None if size in ('native', 'auto', None) else tuple(int(v) for v in size.split('x'))
    with Image.open(image) as im:
        im.load()
        alpha = im.convert('RGBA').getchannel('A').getextrema()
        checks = []
        if target is not None:
            checks.append({'id': 'delivery_size', 'passed': im.size == target,
                           'observed': list(im.size), 'expected': list(target)})
        return checks + [
            {'id': 'png_single_frame', 'passed': im.format == 'PNG' and getattr(im, 'n_frames', 1) == 1,
             'observed': im.format, 'expected': 'single-frame PNG'},
            {'id': 'opaque_pixels', 'passed': alpha == (255, 255),
             'observed': list(alpha), 'expected': [255, 255]},
        ]


def save_json(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def make_comparison(files, destination, thumbnail):
    canvas = Image.new('RGB', (1440, 530), '#ececec')
    draw = ImageDraw.Draw(canvas)
    for index, (key, title) in enumerate([
        ('photo', 'SOURCE PHOTO'), ('image', 'GENERATED AVATAR'), ('style_reference', 'STYLE ONLY')
    ]):
        with Image.open(files[key]['path']) as source:
            im = ImageOps.exif_transpose(source).convert('RGBA')
            im.thumbnail((450, 450), Image.Resampling.LANCZOS)
            x, y = index * 480 + (480 - im.width) // 2, 48 + (450 - im.height) // 2
            canvas.paste(im, (x, y), im)
        draw.text((index * 480 + 16, 16), title, fill='#202020')
    with destination.open('xb') as stream:
        canvas.save(stream, format='PNG')
    with Image.open(files['image']['path']) as source:
        im = source.convert('RGBA')
        im.thumbnail((128, 128), Image.Resampling.LANCZOS)
        with thumbnail.open('xb') as stream:
            im.save(stream, format='PNG')


def prepare(request_path, image, out_dir):
    request_path, request = load_request(request_path)
    files = bindings_for(request_path, request, image)
    auto = automatic_checks(files['image']['path'], request)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    comparison, thumbnail = out_dir / 'comparison.png', out_dir / 'thumbnail-128.png'
    make_comparison(files, comparison, thumbnail)
    checks = [dict(item, verdict='unreviewed', observed='', correction='') for item in checks_for(request)]
    report = {
        'schema_version': 1, 'files': files, 'automatic_checks': auto,
        'visual_review': {**{key: False for key in VIEW_FLAGS}, 'reviewer': ''},
        'checks': checks,
        'scope': '逐项视觉特征与画风核对，不是身份识别；脚本不计算人物相似度',
    }
    review_path = out_dir / 'review.json'
    save_json(review_path, report)
    return {'status': 'awaiting_visual_review', 'review': str(review_path),
            'comparison': str(comparison), 'thumbnail': str(thumbnail),
            'automatic_checks': auto, 'image_modified': False,
            'next_step': '实际查看照片、生成图、独立风格图和缩略图，再填写 observed/verdict；准备成功不是自检通过'}


def assess(review_path):
    report = json.loads(Path(review_path).read_text(encoding='utf-8'))
    if report.get('schema_version') != 1:
        raise ValueError('不支持的自检记录版本')
    old_files = report['files']
    request_path, request = load_request(old_files['request']['path'])
    current_files = bindings_for(request_path, request, old_files['image']['path'])
    if old_files != current_files:
        raise ValueError('照片、参考、请求或成品文件已变化；旧自检失效，请为实际版本重新 prepare')
    canonical = checks_for(request)
    submitted = report.get('checks', [])
    if not isinstance(submitted, list) or len(submitted) != len(canonical):
        raise ValueError('自检条目缺失或多出，不能跳过已锁定的人物与画风检查')
    for expected, actual in zip(canonical, submitted):
        if not isinstance(actual, dict):
            raise ValueError('自检条目必须为对象')
        if any(actual.get(k) != v for k, v in expected.items()):
            raise ValueError('自检条目或期望被改变，请保留计划，只填写观察、结论与修正')
        if actual.get('verdict') not in VERDICTS:
            raise ValueError('verdict 必须为 unreviewed/pass/fail/uncertain')
        if actual['verdict'] != 'unreviewed' and not nonempty_text(actual.get('observed')):
            raise ValueError(f"{actual['id']} 缺少实际照片与成品对照的观察依据")
        if actual['verdict'] == 'fail' and not nonempty_text(actual.get('correction')):
            raise ValueError(f"{actual['id']} 未说明失败后的局部修正")
    auto = automatic_checks(current_files['image']['path'], request)
    visual = report.get('visual_review', {})
    viewed = all(visual.get(k) is True for k in VIEW_FLAGS) and nonempty_text(visual.get('reviewer'))
    failed = [c['id'] for c in submitted if c['verdict'] == 'fail']
    pending = [c['id'] for c in submitted if c['verdict'] == 'unreviewed']
    uncertain = [c['id'] for c in submitted if c['verdict'] == 'uncertain']
    if failed or any(not check['passed'] for check in auto):
        status = 'needs_revision'
    elif pending or not viewed:
        status = 'awaiting_visual_review'
    elif uncertain:
        status = 'needs_manual_review'
    else:
        status = 'passed'
    return {'status': status, 'image': current_files['image']['path'],
            'image_sha256': current_files['image']['sha256'], 'automatic_checks': auto,
            'failed_checks': failed, 'unreviewed_checks': pending, 'uncertain_checks': uncertain,
            'visual_evidence_complete': viewed,
            'scope': '按已填写观察判断工作流是否通过；不独立证明人物相似度，不调用生图或修图'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('prepare')
    setup.add_argument('--request', required=True, type=Path)
    setup.add_argument('--image', required=True, type=Path)
    setup.add_argument('--out-dir', required=True, type=Path)
    check = commands.add_parser('check')
    check.add_argument('--review', required=True, type=Path)
    check.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.request, args.image, args.out_dir)
        else:
            result = assess(args.review)
            if args.output:
                save_json(args.output, result)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'check' and result['status'] != 'passed':
        parser.exit(3)


if __name__ == '__main__':
    main()
