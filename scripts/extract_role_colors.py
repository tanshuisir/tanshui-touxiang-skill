#!/usr/bin/env python3
"""Build role-specific color templates from visually annotated source pixels.

Run only when maintaining the library, never for an ordinary avatar request.
Coordinates identify actual skin/background regions, not frequent-color guesses.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def sample(image, xy):
    if not isinstance(xy, list) or len(xy) != 2 or any(type(v) is not int for v in xy):
        raise ValueError('sample coordinate must be [integer x, integer y]')
    x, y = xy
    if not (4 <= x < image.width - 4 and 4 <= y < image.height - 4):
        raise ValueError('sample coordinate outside image interior')
    pixel = image.getpixel((x, y))
    patch = image.crop((x - 4, y - 4, x + 5, y + 5))
    return {'xy': xy, 'hex': '#%02X%02X%02X' % pixel,
            'patch_exact_fraction': round(Counter(patch.getdata())[pixel] / 81, 4)}


def extract(skill, annotations, destination):
    catalog = json.loads((skill/'references/finished-reference-library.json').read_text())
    records = sorted(annotations, key=lambda item: item['id'])
    expected = {item['id'] for item in catalog['portraits']}
    if {item['id'] for item in records} != expected or len(records) != len(expected):
        raise ValueError('Annotations must cover every source artwork exactly once')
    skins, backgrounds, sources = [], [], []
    for record in records:
        number = record['id']
        relative = f'assets/finished/{number:03d}.png'
        path = skill/relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as original:
            image = original.convert('RGB')
            base = sample(image, record['skin_xy'])
            shadow = sample(image, record['skin_shadow_xy']) if record.get('skin_shadow_xy') else None
            if shadow and shadow['hex'] == base['hex']:
                shadow = None
            skins.append({'id': f'HD-{number:03d}-skin', 'source_hd_id': number,
                          'base': base, 'shadow': shadow,
                          'additional_skin_samples': [sample(image, xy) for xy in record.get('extra_skin_xy', [])]})
            points = [record['background_xy']] + record.get('background_extra_xy', [])
            for index, xy in enumerate(points):
                backgrounds.append({'id': f'HD-{number:03d}-bg-{index + 1}',
                                    'source_hd_id': number, **sample(image, xy),
                                    'usage': 'solid_fill'})
        sources.append({'id': number, 'image': relative, 'sha256': digest,
                        'notes': record.get('notes', '')})
    library = {
        'schema_version': 1, 'policy_id': 'source-role-colors-v1',
        'source_count': len(sources), 'missing_numeric_ids': catalog['missing_numeric_ids'],
        'method': '人工逐张识别肤面、皮肤暗面和背景区域，读取原PNG指定坐标的精确RGB；不取缩略图色、不量化、不跨角色重分配。',
        'background_policy': '原作即使有渐变，也只将已采样背景RGB用作新头像的单一纯色底；不重建背景渐变。',
        'skin_policy': '随机选择真实肤色模板，皮肤暗色跟随同一原作；无可靠暗色时复用肤面基色，不生成新肤色。',
        'sources': sources, 'skins': skins, 'backgrounds': backgrounds,
        'unique_skin_base_count': len({item['base']['hex'] for item in skins}),
        'unique_skin_color_count': len({point['hex'] for item in skins
                                        for point in [item['base'], item['shadow'], *item['additional_skin_samples']] if point}),
        'unique_background_color_count': len({item['hex'] for item in backgrounds}),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(library, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return library


def swatches(library, destination):
    columns, width, height = 9, 128, 83
    rows = (len(library['skins']) + columns - 1)//columns
    sheet = Image.new('RGB', (columns*width, rows*height*2 + 64), '#F4F4F4')
    draw = ImageDraw.Draw(sheet)
    for section, key in enumerate(('skins', 'backgrounds')):
        top = section*(rows*height + 32)
        draw.text((10, top + 8), 'SKIN: source base + same-artwork shadow' if key == 'skins'
                  else 'BACKGROUND: exact source pixels, used as solid fills', fill='#222222')
        # First background per artwork keeps this overview aligned with skins.
        items = library[key] if key == 'skins' else [item for item in library[key] if item['id'].endswith('-1')]
        for index, item in enumerate(items):
            x, y = index%columns*width, top + 32 + index//columns*height
            color = item['base']['hex'] if key == 'skins' else item['hex']
            draw.rectangle((x + 4, y + 2, x + width - 5, y + 45), fill=color, outline='#D0D0D0')
            if key == 'skins' and item['shadow']:
                draw.rectangle((x + 91, y + 3, x + width - 6, y + 44), fill=item['shadow']['hex'])
            draw.text((x + 6, y + 49), f"HD-{item['source_hd_id']:03d} {color}", fill='#222222')
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--swatches', type=Path)
    args = parser.parse_args()
    library = extract(args.skill, json.loads(args.annotations.read_text()), args.output)
    if args.swatches:
        swatches(library, args.swatches)
    print(json.dumps({key: library[key] for key in ('source_count', 'unique_skin_base_count',
                                                  'unique_skin_color_count', 'unique_background_color_count')}))


if __name__ == '__main__':
    main()
