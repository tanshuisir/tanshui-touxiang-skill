"""Verify frozen colorways against the actual referenced artwork pixels."""
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

from PIL import Image


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from source_colors import is_allowed_background
import source_colorways

REFERENCES = SKILL / 'references'
ROLES = ('outline', 'skin_base', 'skin_shadow', 'hair', 'clothing',
         'background', 'cheek', 'detail')


def read_json(name):
    return json.loads((REFERENCES / name).read_text(encoding='utf-8'))


class SourceColorwayDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = read_json('source-colorways.json')
        cls.source = read_json('source-role-colors.json')
        cls.lines = read_json('line-library.json')

    def assert_hex(self, color):
        self.assertIsInstance(color, str)
        self.assertRegex(color, r'^#[0-9A-F]{6}$')

    def assert_sample(self, image, sample, expected=None):
        self.assertIsInstance(sample, dict)
        self.assert_hex(sample.get('hex'))
        xy = sample.get('xy')
        self.assertIsInstance(xy, list)
        self.assertEqual(len(xy), 2)
        self.assertTrue(all(type(value) is int for value in xy))
        self.assertTrue(0 <= xy[0] < image.width and 0 <= xy[1] < image.height)
        actual = '#' + ''.join(f'{value:02X}' for value in image.getpixel(tuple(xy)))
        self.assertEqual(actual, sample['hex'], f'Incorrect pixel sample at {xy}')
        if expected is not None:
            self.assertEqual(sample['hex'], expected)

    def assert_gradient(self, gradient, samples, image):
        self.assertIn(gradient.get('region'), ('hair', 'clothing'))
        self.assertIsInstance(gradient.get('direction'), str)
        self.assertTrue(gradient['direction'].strip())
        for key in ('from', 'to'):
            self.assert_hex(gradient.get(key))
            self.assert_sample(image, samples['gradient_' + key], gradient[key])
        colors = [bytes.fromhex(gradient[key][1:]) for key in ('from', 'to')]
        self.assertGreaterEqual(math.dist(*colors), 24)

    def test_default_four_are_complete_distinct_source_artworks_with_bright_nonwhite_backgrounds(self):
        self.assertEqual(self.catalog['schema_version'], 1)
        self.assertEqual(self.catalog['policy_id'], 'single-source-colorways-v1')
        self.assertEqual(self.catalog['source_library_count'], self.source['source_count'])
        by_source = {item['source_hd_id']: item for item in self.catalog['colorways']}
        self.assertEqual(len(by_source), len(self.catalog['colorways']))
        self.assertGreaterEqual(len(by_source), 4)
        defaults = self.catalog['default_reference_ids']
        self.assertEqual(len(defaults), 4)
        self.assertEqual(len(set(defaults)), 4)
        for reference_id in defaults:
            with self.subTest(reference=reference_id):
                self.assertIn(reference_id, by_source)
                roles = by_source[reference_id]['roles']
                self.assertTrue(set(ROLES).issubset(roles))
                brightness = sum(value * weight for value, weight in
                                 zip(bytes.fromhex(roles['background'][1:]), (0.299, 0.587, 0.114)))
                self.assertGreaterEqual(brightness, 150)
                self.assertTrue(is_allowed_background(roles['background']))

    def test_every_eligible_colorway_preserves_all_original_roles_and_bans_white(self):
        candidates = source_colorways.eligible_colorways()
        self.assertEqual(len(candidates), len(self.catalog['colorways']))
        for item in candidates:
            with self.subTest(reference=item['source_hd_id']):
                plan = source_colorways.plan_for(item['id'])
                self.assertEqual(plan['roles'], item['roles'])
                self.assertTrue(is_allowed_background(plan['roles']['background']))
                self.assertEqual(plan['background_plan']['color'], item['roles']['background'])
                self.assertIn('严禁白色', plan['background_plan']['instructions'])

    def test_every_role_and_gradient_endpoint_matches_an_exact_source_pixel(self):
        sources = {item['id']: item for item in self.source['sources']}
        for item in self.catalog['colorways']:
            with self.subTest(reference=item['source_hd_id']):
                source = sources[item['source_hd_id']]
                self.assertEqual(item['source_image'], source['image'])
                relative = Path(item['source_image'])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn('..', relative.parts)
                image_path = (SKILL / item['source_image']).resolve()
                self.assertTrue(image_path.is_relative_to((SKILL / 'assets').resolve()))
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                self.assertEqual(item['source_sha256'], digest)
                self.assertEqual(item['source_sha256'], source['sha256'])
                with Image.open(image_path) as original:
                    image = original.convert('RGB')
                for role in ROLES:
                    self.assert_hex(item['roles'][role])
                    self.assert_sample(image, item['samples'][role], item['roles'][role])
                self.assert_gradient(item['gradient'], item['samples'], image)
                for option in item.get('gradient_options', []):
                    option_samples = {
                        'gradient_from': option['samples']['from'],
                        'gradient_to': option['samples']['to'],
                    }
                    self.assert_gradient(option, option_samples, image)
                for sample in item['samples'].values():
                    self.assert_sample(image, sample)

    def test_skin_shadow_background_and_ink_keep_the_same_source_identity(self):
        skins = {item['id']: item for item in self.source['skins']}
        backgrounds = {item['id']: item for item in self.source['backgrounds']}
        lines = {item['id']: item for item in self.lines['portraits']}
        for item in self.catalog['colorways']:
            with self.subTest(reference=item['source_hd_id']):
                source_id, roles = item['source_hd_id'], item['roles']
                skin = skins[item['skin_template_id']]
                background = backgrounds[item['background_template_id']]
                line = lines[source_id]
                self.assertEqual(skin['source_hd_id'], source_id)
                self.assertEqual(background['source_hd_id'], source_id)
                self.assertEqual(line['sha256'], item['source_sha256'])
                self.assertEqual(roles['skin_base'], skin['base']['hex'])
                self.assertEqual(roles['skin_shadow'], (skin['shadow'] or skin['base'])['hex'])
                self.assertEqual(roles['background'], background['hex'])
                self.assertEqual(roles['outline'], line['primary_hex'])

    def test_025_keeps_both_yellow_and_orange_end_colors(self):
        item = next(x for x in self.catalog['colorways'] if x['source_hd_id'] == 25)
        start = bytes.fromhex(item['gradient']['from'][1:])
        end = bytes.fromhex(item['gradient']['to'][1:])
        self.assertEqual(item['gradient']['region'], 'hair')
        # The previous endpoint stopped halfway through the source gradient,
        # turning the yellow/orange reference into nearly flat pale yellow.
        self.assertGreaterEqual(start[1] - end[1], 50)
        self.assertGreaterEqual(start[2] - end[2], 50)
        self.assertGreater(item['samples']['gradient_to']['xy'][1],
                           item['samples']['gradient_from']['xy'][1])


if __name__ == '__main__':
    unittest.main()
