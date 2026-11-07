"""Native output behavior, tested offline without an image API call."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import finalize_avatar
import review_avatar
import run_avatar


class NativeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-native-output-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        Image.new('RGB', (240, 320), '#ba8968').save(self.photo)
        self.brief = {
            'photo': str(self.photo),
            'identity_features': ['圆下颌', '短发剪影', '细长眼与闭口微笑'],
            'expression': '闭口微笑', 'pose': '近正面',
        }

    def prepare(self, name, **changes):
        return build_prompt.prepare(dict(self.brief, **changes),
                                    self.root / 'brief.json', self.root / name)

    def test_native_rgb_preserves_every_pixel_and_non_square_dimensions(self):
        source, output = self.root / 'model.png', self.root / 'avatar.png'
        image = Image.new('RGB', (41, 29), '#123456')
        image.putpixel((0, 0), (1, 2, 3))
        image.putpixel((40, 28), (200, 201, 202))
        image.save(source)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        result = finalize_avatar.finalize(source, output)
        with Image.open(output) as delivered:
            self.assertEqual(delivered.size, image.size)
            self.assertEqual(delivered.tobytes(), image.tobytes())
        self.assertEqual(result['original_size'], [41, 29])
        self.assertEqual(result['delivery_size'], [41, 29])
        self.assertEqual(result['operations'], [])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)

    def test_native_transparent_margins_are_filled_without_cropping(self):
        source, output = self.root / 'cutout.png', self.root / 'opaque.png'
        image = Image.new('RGBA', (40, 24), (0, 0, 0, 0))
        image.paste((80, 20, 130, 255), (16, 8, 24, 16))
        image.save(source)
        result = finalize_avatar.finalize(source, output, background={'color': '#FFDC70'})
        with Image.open(output) as delivered:
            self.assertEqual(delivered.size, (40, 24))
            self.assertEqual(delivered.getpixel((0, 0)), (255, 220, 112))
            self.assertEqual(delivered.getpixel((39, 23)), (255, 220, 112))
            self.assertEqual(delivered.getpixel((20, 12)), (80, 20, 130))
            self.assertEqual(delivered.convert('RGBA').getchannel('A').getextrema(), (255, 255))
        self.assertEqual([op['operation'] for op in result['operations']],
                         ['composite_opaque_background'])



if __name__ == '__main__':
    unittest.main()
