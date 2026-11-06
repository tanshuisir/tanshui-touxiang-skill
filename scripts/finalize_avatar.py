#!/usr/bin/env python3
"""Deliver a generated square avatar as a 1000×1000 PNG without changing composition.

Keeps the model original. This performs only the size/format normalization the
user requested; it neither rates the artwork nor calls any image model.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


def finalize(source, output, size=1000):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError('输出已存在，请选择新文件，保留原图和此前版本')
    if source == output:
        raise ValueError('交付文件不能覆盖模型原图')
    if output.suffix.lower() != '.png':
        raise ValueError('标准交付文件扩展名必须为 .png')
    if type(size) is not int or size <= 0:
        raise ValueError('目标边长必须为正整数')
    with Image.open(source) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('标准头像需要单帧图片')
        original_size = list(original.size)
        image = original.convert('RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB')
        operations = []
        if image.width != image.height:
            bbox = image.getchannel('A').getbbox() if image.mode == 'RGBA' else None
            if bbox and bbox[2] - bbox[0] == bbox[3] - bbox[1]:
                image = image.crop(bbox)
                operations.append({'operation':'remove_fully_transparent_margin','box':list(bbox)})
            else:
                raise ValueError('模型返回非正方形；不能拉伸、补框或擅自裁切人物，请先说明尺寸不符合要求')
        if image.size != (size, size):
            if image.width < size:
                raise ValueError('模型原图小于目标尺寸；不能把放大图宣称为高清成品')
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            operations.append({'operation':'uniform_lanczos_downsample','size':[size,size]})
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids overwriting an existing deliverable.
        with output.open('xb') as stream:
            image.save(stream, format='PNG')
    with Image.open(output) as delivered:
        if delivered.size != (size, size) or delivered.format != 'PNG':
            raise ValueError('交付文件尺寸或格式校验失败')
    return {
        'status':'completed', 'original':str(source), 'delivery':str(output),
        'original_size':original_size, 'delivery_size':[size,size],
        'operations':operations, 'original_preserved':True,
        'delivery_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'scope':'尺寸与格式整理；未检查人物画面质量、未调用模型',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--size', default=1000, type=int, help='Delivery edge length; default 1000')
    args = parser.parse_args()
    try:
        result = finalize(args.image, args.output, args.size)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
