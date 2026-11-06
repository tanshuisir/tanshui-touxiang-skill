#!/usr/bin/env python3
"""Import finished PNG references without resampling visible pixels; sample palettes.

The destination must be new. It contains assets/finished, references and contact
sheets, ready to merge into this Skill. No image-generation service is called.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_references(source, destination):
    files = sorted(source.glob('*.png'), key=lambda p: int(p.stem))
    if not files:
        raise ValueError('No numerically named PNG references found')
    if destination.exists():
        raise ValueError('Destination already exists; choose a new directory')
    assets = destination / 'assets/finished'
    references = destination / 'references'
    assets.mkdir(parents=True)
    references.mkdir()
    records = []
    for path in files:
        with Image.open(path) as original:
            rgba = original.convert('RGBA')
            bbox = rgba.getchannel('A').getbbox()
            if bbox is None:
                raise ValueError(f'Empty image: {path}')
            visible = rgba.crop(bbox)
            if visible.size != (1000, 1000):
                raise ValueError(f'Visible image must be 1000×1000, got {visible.size}: {path}')
            if visible.getchannel('A').getextrema() != (255, 255):
                raise ValueError(f'Partially transparent artwork needs separate handling: {path}')
            rgb = visible.convert('RGB')
            counts = Counter(rgb.getdata())
            exact = [
                {'hex': '#%02X%02X%02X' % color, 'pixels': count,
                 'fraction': round(count / 1_000_000, 6)}
                for color, count in counts.most_common(16)
            ]
            quantized = rgb.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert('RGB')
            representatives = [
                {'hex': '#%02X%02X%02X' % color, 'fraction': round(count / 1_000_000, 6)}
                for color, count in Counter(quantized.getdata()).most_common()
            ]
            number = int(path.stem)
            output = assets / f'{number:03d}.png'
            if original.size == visible.size and bbox == (0, 0, 1000, 1000):
                output.write_bytes(path.read_bytes())
            else:
                visible.save(output, format='PNG')
            # Pixel equality concerns visible RGBA only; hidden transparent-column
            # RGB values are deliberately excluded from palette measurements.
            with Image.open(output) as check:
                assert check.convert('RGBA').tobytes() == visible.tobytes()
            records.append({
                'id': number, 'label': f'HD-{number:03d}',
                'source_filename': path.name, 'source_size': list(original.size),
                'source_sha256': digest(path), 'visible_crop_box': list(bbox),
                'normalization': 'none' if original.size == visible.size else 'remove_fully_transparent_edge_column',
                'reference_image': f'assets/finished/{number:03d}.png',
                'size': [1000, 1000], 'sha256': digest(output),
                'visible_pixel_equivalence': True,
                'exact_color_count': len(counts), 'most_frequent_colors': exact,
                'quantized_representatives': representatives,
                'background_corner_samples': [
                    {'xy': [x, y], 'hex': '#%02X%02X%02X' % rgb.getpixel((x, y))}
                    for x, y in [(10, 10), (989, 10), (10, 989), (989, 989)]
                ],
            })
    for page in range((len(records) + 19) // 20):
        subset = records[page * 20:(page + 1) * 20]
        rows = (len(subset) + 4) // 5
        sheet = Image.new('RGB', (1250, rows * 270), '#EEEEEE')
        draw = ImageDraw.Draw(sheet)
        for i, record in enumerate(subset):
            with Image.open(destination / record['reference_image']) as image:
                thumb = image.convert('RGB').resize((240, 240), Image.Resampling.LANCZOS)
            x, y = (i % 5) * 250 + 5, (i // 5) * 270 + 24
            sheet.paste(thumb, (x, y))
            draw.text((x, y - 19), record['label'], fill='#222222')
        sheet.save(assets / f'contact-{page + 1}.jpg', quality=95)
    library = {
        'schema_version': 1, 'source': str(source.resolve()),
        'analysis_scope': 'User-supplied finished images; exact RGB frequencies and 12-color quantization are raster measurements, not author source swatches.',
        'count': len(records),
        'missing_numeric_ids': sorted(set(range(1, max(r['id'] for r in records) + 1)) - {r['id'] for r in records}),
        'normalization': 'Only fully transparent outer margins removed; visible pixels never resampled.',
        'portraits': records,
    }
    target = references / 'finished-reference-library.json'
    target.write_text(json.dumps(library, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'count': len(records), 'library': str(target), 'destination': str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = import_references(args.source.resolve(), args.out_dir.resolve())
    except (OSError, ValueError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
