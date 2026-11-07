#!/usr/bin/env python3
"""Deliver an opaque avatar at native dimensions unless a size is requested.

Keeps the model original. Normalizes format and, when needed, composites
existing alpha over the planned background; never calls an image model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from PIL import Image


def background_image(size, plan):
    if not isinstance(plan, dict) or not re.fullmatch(r'#[0-9a-fA-F]{6}', str(plan.get('color', ''))):
        raise ValueError('透明原图需要明确的对比背景色 #RRGGBB，不能直接删除透明通道')
    # Old request files may carry a background gradient; the current solid
    # background rule takes precedence during local alpha compositing.
    return Image.new('RGBA', size, plan['color'])


def finalize(source, output, size=None, background=None, fit_square=False):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError('输出已存在，请选择新文件，保留原图和此前版本')
    if source == output:
        raise ValueError('交付文件不能覆盖模型原图')
    if output.suffix.lower() != '.png':
        raise ValueError('标准交付文件扩展名必须为 .png')
    if size is not None and (type(size) is not int or size <= 0):
        raise ValueError('目标边长必须为正整数')
    with Image.open(source) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('标准头像需要单帧图片')
        original_size = list(original.size)
        image = original.convert('RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB')
        operations = []
        if image.mode == 'RGBA' and image.getchannel('A').getextrema()[1] == 0:
            raise ValueError('模型原图完全透明，没有可见人物；不能交付纯背景冒充头像')
        if size is not None and image.width != image.height:
            bbox = image.getchannel('A').getbbox() if image.mode == 'RGBA' else None
            if bbox and bbox[2] - bbox[0] == bbox[3] - bbox[1]:
                image = image.crop(bbox)
                operations.append({'operation':'remove_fully_transparent_margin','box':list(bbox)})
            elif fit_square:
                if max(image.size) < size:
                    raise ValueError('模型原图小于目标尺寸；不能把放大图宣称为高清成品')
                scale = size / max(image.size)
                fitted_size = tuple(max(1, round(edge * scale)) for edge in image.size)
                if fitted_size != image.size:
                    image = image.resize(fitted_size, Image.Resampling.LANCZOS)
                canvas = background_image((size, size), background)
                offset = ((size - image.width) // 2, size - image.height)
                canvas.alpha_composite(image.convert('RGBA'), offset)
                image = canvas
                operations.append({'operation': 'fit_square_background',
                                   'fitted_size': list(fitted_size), 'offset': list(offset),
                                   'size': [size, size], 'background': background['color'],
                                   'scope': 'uniform fit; no subject crop, stretch, upscale or model call'})
            else:
                raise ValueError('模型返回非正方形；不能拉伸、补框或擅自裁切人物，请先说明尺寸不符合要求')
        if size is not None and image.size != (size, size):
            if image.width < size:
                raise ValueError('模型原图小于目标尺寸；不能把放大图宣称为高清成品')
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            operations.append({'operation':'uniform_lanczos_downsample','size':[size,size]})
        composited = image.mode == 'RGBA' and image.getchannel('A').getextrema()[0] < 255
        if composited:
            image = Image.alpha_composite(background_image(image.size, background), image)
            operations.append({'operation':'composite_opaque_background', 'background':background})
        image = image.convert('RGB')
        delivery_size = list(image.size)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids overwriting an existing deliverable.
        with output.open('xb') as stream:
            image.save(stream, format='PNG')
    with Image.open(output) as delivered:
        if list(delivered.size) != delivery_size or delivered.format != 'PNG' or delivered.mode != 'RGB':
            raise ValueError('交付文件尺寸、格式或不透明背景校验失败')
    return {
        'status':'completed', 'original':str(source), 'delivery':str(output),
        'original_size':original_size, 'delivery_size':delivery_size,
        'operations':operations, 'original_preserved':True,
        'opaque':True, 'background_composited':composited,
        'delivery_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'scope':'尺寸、格式与不透明交付；必要时本地合成计划背景，未评判人物画面或调用模型',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--size', type=int, help='Explicit delivery edge length; omit to keep native dimensions')
    bg = parser.add_mutually_exclusive_group()
    bg.add_argument('--request', type=Path, help='Use background_plan from generation-request.json')
    bg.add_argument('--background-color', help='Explicit #RRGGBB opaque background for a transparent original')
    args = parser.parse_args()
    try:
        background = {'color':args.background_color} if args.background_color else None
        fit_square = False
        if args.request:
            request = json.loads(args.request.read_text(encoding='utf-8'))
            background = request['background_plan']
            if args.size is None and request.get('delivery_size') not in (None, 'native', 'auto'):
                args.size = int(request['delivery_size'].split('x')[0])
            fit_square = request.get('size_policy') == 'square'
        result = finalize(args.image, args.output, args.size, background=background, fit_square=fit_square)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
