"""Offline checks for the observed decoded blush-edge speck failure."""
from pathlib import Path
import sys
import unittest
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from semantic_encoding import IDS
from style_language import validate_cheek_edge_specks

class CheekEdgeTests(unittest.TestCase):
    def sample(self):
        ids = Image.new('L', (256, 256), IDS['skin_base'])
        ImageDraw.Draw(ids).ellipse((80, 80, 120, 120), fill=IDS['accent'])
        alpha = Image.new('L', ids.size, 0)
        return ids, alpha

    def test_clean_blush_preserves_both_maps(self):
        ids, alpha = self.sample()
        before = ids.tobytes(), alpha.tobytes()
        result = validate_cheek_edge_specks(ids, alpha, IDS)
        self.assertEqual(result['isolated_ink_regions'], [])
        self.assertEqual((ids.tobytes(), alpha.tobytes()), before)

    def test_exact_clothing_pattern_dot_on_blush_rim_is_rejected(self):
        ids, alpha = self.sample()
        ids.putpixel((100, 79), IDS['clothing_pattern'])
        with self.assertRaisesRegex(ValueError, '腮红边缘存在点状墨粒'):
            validate_cheek_edge_specks(ids, alpha, IDS)

    def test_disconnected_ink_dot_on_blush_rim_is_rejected(self):
        ids, alpha = self.sample()
        alpha.putpixel((100, 79), 255)
        with self.assertRaisesRegex(ValueError, '腮红边缘存在点状墨粒'):
            validate_cheek_edge_specks(ids, alpha, IDS)

    def test_nearby_continuous_outline_is_not_rejected_or_modified(self):
        ids, alpha = self.sample()
        ImageDraw.Draw(alpha).line((79, 50, 79, 150), fill=255, width=2)
        before = alpha.tobytes()
        validate_cheek_edge_specks(ids, alpha, IDS)
        self.assertEqual(alpha.tobytes(), before)

    def test_small_necklace_or_earring_outside_blush_band_is_untouched(self):
        ids, alpha = self.sample()
        alpha.putpixel((150, 170), 255)
        ids.putpixel((150, 171), IDS['accessory'])
        before = ids.tobytes(), alpha.tobytes()
        validate_cheek_edge_specks(ids, alpha, IDS)
        self.assertEqual((ids.tobytes(), alpha.tobytes()), before)

    def test_no_blush_is_a_noop(self):
        ids, alpha = self.sample()
        ids.paste(IDS['skin_base'], (0,0,256,256))
        alpha.putpixel((100, 79), 255)
        validate_cheek_edge_specks(ids, alpha, IDS)

if __name__ == '__main__':
    unittest.main()
