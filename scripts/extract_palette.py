#!/usr/bin/env python3
"""Extract exact decoded RGB histograms and representative palettes from references.

Requires Pillow. This analyzes reference artwork; it does not generate portraits.
"""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps


def extract(path, index, out, colors):
    with Image.open(path) as opened:
        oriented = ImageOps.exif_transpose(opened)
        rgba = oriented.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        counts = Counter(rgb.getdata())
        total = rgb.width * rgb.height
        hist_name = f"{index:02d}-{path.stem}-rgb.csv.gz"
        with gzip.open(out / hist_name, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["hex", "r", "g", "b", "pixels", "fraction"])
            for color, count in sorted(counts.items(), key=lambda row: (-row[1], row[0])):
                writer.writerow(["#%02X%02X%02X" % color, *color, count, f"{count / total:.10f}"])
        # Full-resolution pixel weights, deterministic quantization, no dithering.
        quantized = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                                 dither=Image.Dither.NONE)
        palette = quantized.getpalette()
        entries = []
        for count, number in sorted(quantized.getcolors(), reverse=True):
            color = palette[number * 3:number * 3 + 3]
            entries.append({"hex": "#%02X%02X%02X" % tuple(color), "rgb": color,
                            "pixels": count, "fraction": count / total})
        return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "width": rgb.width, "height": rgb.height, "pixel_count": total,
                "unique_decoded_rgb_colors": len(counts), "histogram": hist_name,
                "palette": entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--colors", type=int, default=24)
    args = parser.parse_args()
    if not 2 <= args.colors <= 256:
        parser.error("--colors must be between 2 and 256")
    if args.out_dir.exists():
        parser.error("--out-dir must be new; preserve earlier analyses")
    for path in args.images:
        if not path.is_file():
            parser.error(f"Missing image: {path}")
    args.out_dir.mkdir(parents=True)
    records = [extract(path, i, args.out_dir, args.colors)
               for i, path in enumerate(args.images, 1)]
    report = {"method": "Pillow MEDIANCUT, full resolution, no dithering",
              "color_space": "decoded RGB values; no ICC conversion; alpha composited on white",
              "scope": "All supplied image pixels, including borders, captions and watermarks. "
                       "Crop artwork first for an artwork-only palette.",
              "meaning": "Histograms contain every unique decoded RGB color. Palette entries "
                         "are quantized representatives, not original author swatches.",
              "images": records}
    (args.out_dir / "palette.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="%d" viewBox="0 0 1040 %d">' %
           (70 + len(records) * 310, 70 + len(records) * 310),
           '<rect width="100%" height="100%" fill="#F7F7F4"/>',
           '<text x="24" y="34" font-family="sans-serif" font-size="21">Reference color sampling · quantized representatives</text>']
    for i, record in enumerate(records):
        y = 70 + i * 310
        svg.append(f'<text x="24" y="{y}" font-family="monospace" font-size="16">Reference {i + 1:02d} · {record["width"]} × {record["height"]} · {record["unique_decoded_rgb_colors"]} RGB colors</text>')
        for j, entry in enumerate(record["palette"][:24]):
            x, sy = 24 + (j % 8) * 126, y + 18 + (j // 8) * 88
            svg.extend([f'<rect x="{x}" y="{sy}" width="112" height="48" rx="5" fill="{entry["hex"]}"/>',
                        f'<text x="{x}" y="{sy + 65}" font-family="monospace" font-size="12">{entry["hex"]} · {entry["fraction"]:.1%}</text>'])
    svg.append("</svg>")
    (args.out_dir / "swatches.svg").write_text("\n".join(svg) + "\n")
    print(json.dumps({"status": "completed", "out_dir": str(args.out_dir.resolve()),
                      "images": len(records), "unique_rgb_counts": [r["unique_decoded_rgb_colors"] for r in records]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
