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

    def test_example_four_are_complete_distinct_source_artworks_with_bright_nonwhite_backgrounds(self):
        self.assertEqual(self.catalog['schema_version'], 1)
        self.assertEqual(self.catalog['policy_id'], 'single-source-colorways-v1')
        self.assertEqual(self.catalog['source_library_count'], self.source['source_count'])
        by_source = {item['source_hd_id']: item for item in self.catalog['colorways']}
        self.assertEqual(len(by_source), len(self.catalog['colorways']))
        self.assertGreaterEqual(len(by_source), 4)
        defaults = self.catalog['example_reference_ids']
        self.assertGreaterEqual(len(defaults), 4)
        self.assertEqual(len(set(defaults)), len(defaults))
        for reference_id in defaults:
            with self.subTest(reference=reference_id):
                self.assertIn(reference_id, by_source)
                roles = by_source[reference_id]['roles']
                self.assertTrue(set(ROLES).issubset(roles))
                brightness = sum(value * weight for value, weight in
                                 zip(bytes.fromhex(roles['background'][1:]), (0.299, 0.587, 0.114)))
                self.assertIsInstance(brightness, float)

    def test_all_70_colorways_preserve_all_original_roles_including_white_and_dark(self):
        candidates = source_colorways.eligible_colorways()
        self.assertEqual(len(candidates), self.catalog['eligible_colorway_count'])
        self.assertEqual(len(candidates), 70)
        for item in candidates:
            with self.subTest(reference=item['source_hd_id']):
                plan = source_colorways.plan_for(item['id'])
                self.assertEqual(plan['roles'], item['roles'])
                self.assertEqual(plan['background_plan']['color'], item['roles']['background'])
                self.assertTrue(plan['background_plan']['tone_policy']['white_and_dark_source_backgrounds_allowed'])

    def test_every_role_and_gradient_endpoint_matches_an_exact_source_pixel(self):
        sources = {item['source_hd_id']: item for item in self.source['sources']}
        for item in self.catalog['colorways']:
            with self.subTest(reference=item['source_hd_id']):
                source = sources[item['source_hd_id']]
                self.assertEqual(item['source_image'], source['source_image'])
                relative = Path(item['source_image'])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn('..', relative.parts)
                image_path = (SKILL / item['source_image']).resolve()
                self.assertTrue(image_path.is_relative_to((SKILL / 'assets').resolve()))
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                self.assertEqual(item['source_sha256'], digest)
                self.assertEqual(item['source_sha256'], source['source_sha256'])
                with Image.open(image_path) as original:
                    image = original.convert('RGB')
                for role in ROLES:
                    self.assert_hex(item['roles'][role])
                    self.assert_sample(image, item['samples'][role], item['roles'][role])
                if item['gradient'] is not None:
                    self.assert_gradient(item['gradient'], item['samples'], image)
                else:
                    self.assertEqual(item['gradient_options'], [])
                for option in item.get('gradient_options', []):
                    option_samples = {
                        'gradient_from': option['samples']['from'],
                        'gradient_to': option['samples']['to'],
                    }
                    self.assert_gradient(option, option_samples, image)
                for sample in item['samples'].values():
                    self.assert_sample(image, sample)
                for sample in item.get('dominant_swatches',[]) + item['background_samples'] + item['additional_skin_samples']:
                    self.assert_sample(image, sample)
                for sample in item.get('observed_gradient_stops', {}).get('samples', []):
                    self.assert_sample(image, sample)

    def test_every_original_has_one_independent_palette_and_matching_index(self):
        expected = {x['source_hd_id'] for x in self.source['sources']}
        actual = {x['source_hd_id'] for x in self.catalog['colorways']}
        self.assertEqual(len(actual), 70)
        self.assertEqual(actual, expected)
        self.assertIn(51, actual)
        files = list((REFERENCES/'colorways').glob('TS-*-colorway.json'))
        self.assertEqual(len(files), 70)
        for item in self.catalog['colorways']:
            self.assertEqual(read_json('colorways/' + item['id'] + '.json'), item)

    def test_archive_preserves_flat_white_and_dark_artworks_without_faking_gradients(self):
        rejected = []
        for item in self.catalog['colorways']:
            source_colorways.validate_template(item, require_eligible=False)
            reasons = source_colorways.eligibility_reasons(item)
            self.assertEqual(item['generation_eligibility']['reasons'], reasons)
            self.assertEqual(item['generation_eligibility']['eligible'], not reasons)
            if reasons:
                rejected.append(item)
                with self.assertRaises(ValueError):
                    source_colorways.plan_for(item['id'])
        self.assertEqual(rejected, [])
        for item in self.catalog['colorways']:
            if item['gradient'] is not None:
                continue
            self.assertIsNone(item['gradient'])
            self.assertEqual(item['gradient_options'], [])

    def test_absent_roles_use_explicit_same_source_fallback_samples(self):
        for item in self.catalog['colorways']:
            for role, observation in item.get('role_presence', {}).items():
                if not observation['present']:
                    fallback = observation.get('fallback_role',observation.get('fallback'))
                    self.assertEqual(item['samples'][role], item['samples'][fallback])
                    self.assertEqual(item['roles'][role], item['roles'][fallback])

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

    def test_all_current_template_numbers_resolve_without_old_missing_slot(self):
        for number in range(1, 71):
            item = source_colorways.colorway(f'TS-{number:03d}')
            self.assertEqual(item['source_hd_id'], number)
            self.assertEqual(item['id'], f'TS-{number:03d}-colorway')
            self.assertEqual(item['source_image'], f'assets/templates/{number:03d}.png')
        for old in ('HD-025', 'HD-025-colorway', 'pink-plum'):
            with self.assertRaises(ValueError):
                source_colorways.colorway(old)


if __name__ == '__main__':
    unittest.main()
