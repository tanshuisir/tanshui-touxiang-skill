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
    checks = [
        {'id': f'identity.{i + 1}', 'expected': item['render_as'],
         'photo_evidence': item['photo_evidence'], 'emphasis': item['emphasis'],
         'do_not_change': item['do_not_change']}
        for i, item in enumerate(request['review_spec']['identity_plan'])
    ]
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
         '至少一处有可见面积与色差的连续二色渐变，硬边色块/亮线/噪点不算；'
         + request.get('color_plan', {}).get('gradient_instructions', '渐变在头发、服饰或背景内部，外缘清楚')},
        {'id': 'shadow_detail', 'expected': '暗面留在对应脸、颈或衣面；线条、纹理与局部细节服从本次 shadow_plan，不改画风'},
        {'id': 'framing_readability', 'expected': '实际交付图及128像素缩略图中关键面部特征可读；头顶、道具和肩部按本次构图保留'},
    ]
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
    target = tuple(int(v) for v in request['delivery_size'].split('x'))
    with Image.open(image) as im:
        im.load()
        return [
            {'id': 'delivery_size', 'passed': im.size == target,
             'observed': list(im.size), 'expected': list(target)},
            {'id': 'png_single_frame', 'passed': im.format == 'PNG' and getattr(im, 'n_frames', 1) == 1,
             'observed': im.format, 'expected': 'single-frame PNG'},
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
