"""Synthetic semantic masters for offline runner integration tests."""
from PIL import Image, ImageDraw


def encoded_fixture(path, size=(1024, 1024), transparent_background=False):
    image = Image.new('RGB', (180, 220), '#FFFFFF')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((25, 12, 154, 190), radius=40, fill='#FFFF00', outline='#000000', width=4)
    draw.ellipse((48, 40, 130, 155), fill='#FF0000', outline='#000000', width=4)
    draw.rectangle((112, 75, 123, 130), fill='#00FF00')
    draw.polygon(((15, 220), (40, 165), (135, 165), (170, 220)), fill='#00FFFF', outline='#000000', width=4)
    draw.ellipse((61, 90, 69, 100), fill='#000000')
    draw.ellipse((101, 90, 109, 100), fill='#000000')
    draw.ellipse((54, 109, 68, 122), fill='#FF00FF')
    draw.ellipse((105, 109, 119, 122), fill='#FF00FF')
    draw.rectangle((82, 133, 98, 139), fill='#0000FF', outline='#000000', width=1)
    if transparent_background:
        image = image.convert('RGBA')
        alpha = Image.new('L', image.size)
        alpha.putdata([0 if pixel[:3] == (255, 255, 255) else 255 for pixel in image.getdata()])
        image.putalpha(alpha)
    image.resize(size, Image.Resampling.NEAREST).save(path)
