#!/usr/bin/env python3
"""Verify curated source-line samples and rebuild their offline catalogue."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

SKILL = Path(__file__).resolve().parents[1]


def as_hex(rgb):
    return '#' + ''.join(f'{value:02X}' for value in rgb[:3])


def font(size):
    for name in ('/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(name).is_file():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def verify(library):
    """Pixel/hash verification does not replace the curator's visual role judgment."""
    rows, seen = [], set()
    expected = set(range(1, 71)) - {51}
    family_ids = {entry['id'] for entry in library['families']}
    for item in library['portraits']:
        ident = item['id']
        if ident in seen or ident not in expected:
            raise ValueError(f'Duplicate or unexpected HD id: {ident}')
        seen.add(ident)
        if item['line_family'] not in family_ids:
            raise ValueError(f'Unknown family at HD-{ident:03d}')
        source = (SKILL / item['reference_image']).resolve()
        if SKILL.resolve() not in source.parents:
            raise ValueError('Reference path must remain within the skill')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != item['sha256']:
            raise ValueError(f'Source hash mismatch at HD-{ident:03d}')
        with Image.open(source) as opened:
            rgba = opened.convert('RGBA')
            counts = Counter(rgba.getdata())
            samples = [('primary', item['primary_hex'], item['primary_sample_xy'])]
            samples += [(entry['role'], entry['hex'], entry['sample_xy'])
                        for entry in item.get('secondary_colors', [])]
            report = []
            for role, value, point in samples:
                if len(point) != 2 or any(type(v) is not int for v in point):
                    raise ValueError(f'Invalid sampling coordinates at HD-{ident:03d}')
                x, y = point
                if not (0 <= x < rgba.width and 0 <= y < rgba.height):
                    raise ValueError(f'Sample outside source at HD-{ident:03d}')
                pixel = rgba.getpixel((x, y))
                if pixel[3] != 255 or as_hex(pixel) != value.upper():
                    raise ValueError(f'RGB/alpha mismatch at HD-{ident:03d} {role}: {point}')
                # A 3x3 core check helps flag isolated antialias pixels. It is
                # reported as evidence, never as proof of semantic line roles.
                patch = rgba.crop((max(0, x-1), max(0, y-1), min(rgba.width, x+2), min(rgba.height, y+2)))
                core_matches = sum(as_hex(p) == value.upper() and p[3] == 255 for p in patch.getdata())
                report.append({'role': role, 'hex': value.upper(), 'xy': point,
                               'exact_rgb_pixels': sum(n for p, n in counts.items()
                                                       if p[:3] == pixel[:3] and p[3] == 255),
                               'core_3x3_matches': core_matches,
                               'core_3x3_total': patch.width * patch.height})
            rows.append({'id': ident, 'source_sha256': digest, 'samples': report})
    if seen != expected or library.get('count') != len(seen):
        raise ValueError('Library must cover all 69 references, retaining missing HD-051')
    for family in library['families']:
        members = sorted(item['id'] for item in library['portraits']
                         if item['line_family'] == family['id'])
        if family['reference_ids'] != members:
            raise ValueError(f'Family membership mismatch: {family["id"]}')
    return {'status': 'verified', 'scope': 'source hashes and sampled raster RGB; semantic roles are curated',
            'count': len(rows), 'portraits': rows}


def draw_colours(library, target):
    items = library['portraits']
    columns, cw, ch, heading = 6, 220, 104, 64
    canvas = Image.new('RGB', (columns*cw, heading + ((len(items)+columns-1)//columns)*ch), '#FAF9F6')
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 12), '69 reference portraits | sampled core line colours', font=font(25), fill='#262626')
    draw.text((18, 42), 'Exact raster RGB; original brush/source swatches are not available.', font=font(14), fill='#555555')
    for index, item in enumerate(items):
        x, y = (index % columns)*cw, heading + (index // columns)*ch
        draw.rounded_rectangle((x+12, y+6, x+cw-12, y+ch-6), radius=8, fill='white', outline='#DDDAD4')
        draw.line((x+24, y+29, x+cw-24, y+29), fill=item['primary_hex'], width=12)
        draw.text((x+24, y+46), f'HD-{item["id"]:03d}  {item["primary_hex"]}', font=font(18), fill='#222222')
        draw.text((x+24, y+73), item.get('color_family', 'curated')[:25], font=font(12), fill='#555555')
    canvas.save(target, optimize=True)


def draw_atlases(library, target):
    target.mkdir(parents=True, exist_ok=True)
    items = library['portraits']
    files = []
    for page, start in enumerate(range(0, len(items), 18), 1):
        canvas = Image.new('RGB', (6*220, 3*302+50), '#FAF9F6')
        draw = ImageDraw.Draw(canvas)
        draw.text((15, 12), f'Source artwork and curated line samples | {page}/4', font=font(22), fill='#222222')
        for offset, item in enumerate(items[start:start+18]):
            x, y = (offset % 6)*220, 50+(offset//6)*302
            with Image.open(SKILL/item['reference_image']) as opened:
                thumb = ImageOps.contain(opened.convert('RGB'), (204, 204))
                canvas.paste(thumb, (x+8, y+2))
            draw.text((x+8, y+213), f'HD-{item["id"]:03d}  {item["primary_hex"]}', font=font(17), fill='#222222')
            draw.line((x+10, y+246, x+206, y+246), fill=item['primary_hex'], width=8)
            draw.text((x+8, y+260), item['line_family'], font=font(13), fill='#444444')
            draw.text((x+8, y+279), f'core pixel {tuple(item["primary_sample_xy"])}', font=font(12), fill='#555555')
        name = f'line-atlas-{page}.jpg'
        canvas.save(target/name, quality=94, subsampling=0)
        files.append(name)
    return files


def markdown_index(library):
    lines = ['# 逐张线条与核心线色索引', '',
             '依据原PNG中的人工线条角色判断与精确像素取样。色值不是作者源工程色板；类别与相对线宽是Skill的归纳和建议。', '',
             '完整部位观察、辅助线色和取样坐标见 [line-library.json](line-library.json)；执行规则见 [line-design-guide.md](line-design-guide.md)。', '',
             '| 编号 | 核心主线RGB | 线条主类 | 原图取样坐标 | 辅助线色及角色 | 画法观察 |',
             '|---|---|---|---|---|---|']
    family_names = {family['id']: family['name'] for family in library['families']}
    for item in library['portraits']:
        secondary = '；'.join(entry['hex']+' '+entry['role'] for entry in item.get('secondary_colors', [])) or '无另记辅助线色'
        note = item['technique_notes'].replace('|', '／').replace('\n', ' ')
        lines.append(f'| HD-{item["id"]:03d} | `{item["primary_hex"]}` | {family_names[item["line_family"]]} | {tuple(item["primary_sample_xy"])} | {secondary} | {note} |')
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=SKILL/'references/line-library.json')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    library = json.loads(args.library.read_text(encoding='utf-8'))
    report = verify(library)
    out = args.out_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/'line-sampling-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (out/'line-reference-index.md').write_text(markdown_index(library), encoding='utf-8')
    draw_colours(library, out/'line-colors.png')
    pages = draw_atlases(library, out)
    print(json.dumps({'status': report['status'], 'count': report['count'],
                      'out_dir': str(out), 'atlas_pages': pages}, ensure_ascii=False))


if __name__ == '__main__':
    main()
