"""Source-only, nonwhite background contracts without image/API requests."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import background_plan
import source_colors
import source_colorways
import variant_plans


class ColorPolicyTests(unittest.TestCase):
    @contextmanager
    def synthetic_backgrounds(self, replacements):
        """Change matching fixture roles/provenance, never real source data."""
        catalog = deepcopy(source_colorways.catalog())
        roles = deepcopy(source_colors.library())
        for item in catalog['colorways']:
            if item['source_hd_id'] not in replacements:
                continue
            color = replacements[item['source_hd_id']]
            item['roles']['background'] = color
            item['samples']['background']['hex'] = color
            source = next(bg for bg in roles['backgrounds']
                          if bg['id'] == item['background_template_id'])
            source['hex'] = color
        with mock.patch.object(source_colorways, 'catalog', return_value=catalog), \
                mock.patch.object(variant_plans, 'catalog', return_value=catalog), \
                mock.patch.object(source_colorways, 'role_library', return_value=roles):
            yield catalog

    def make_variants(self, brief=None, first_plan=None):
        return variant_plans.make_variant_plans(
            brief or {}, first_plan, {'id': 25, 'technique': 'flat'}, 'finished',
            'expressive', mock.Mock(side_effect=AssertionError('Do not mix individual swatches')))

    def test_white_family_is_blocked_but_chromatic_pastels_remain_eligible(self):
        for color in ('#FFFFFF', '#FAF7FA', '#F5F5F5', '#FFF1D7', '#FFE9F0'):
            with self.subTest(color=color):
                self.assertTrue(source_colors.is_white_background(color))
                self.assertFalse(source_colors.is_allowed_background(color))
        for color in ('#A1E5D2', '#FFE4A6', '#E56DE9', '#E6FF00'):
            with self.subTest(color=color):
                self.assertFalse(source_colors.is_white_background(color))
                self.assertTrue(source_colors.is_allowed_background(color))
        self.assertFalse(source_colors.is_allowed_background('#292945'))

    def test_current_library_candidates_are_source_only_bright_and_nonwhite(self):
        original = source_colors.background_templates()
        allowed = source_colors.eligible_background_templates()
        self.assertGreaterEqual(len({item['hex'] for item in allowed}), 4)
        for item in allowed:
            self.assertIn(item, original)
            self.assertGreaterEqual(source_colors.background_brightness(item['hex']), 150)
            self.assertFalse(source_colors.is_white_background(item['hex']))

    def test_old_or_explicit_white_background_template_is_migrated_without_new_rgb(self):
        white = next(item for item in source_colors.background_templates()
                     if item['hex'] == '#FFFFFF')
        roles = {'hair': '#000000', 'clothing': '#000000'}
        source_colors.background_request({'background_template_id': white['id']}, roles)
        self.assertEqual(roles['background'], '#FFFFFF')
        planned = background_plan.plan_background(roles, None)
        self.assertTrue(planned['adjusted'])
        self.assertTrue(source_colors.is_allowed_background(planned['color']))
        self.assertIn(planned['color'], {item['hex'] for item in source_colors.background_templates()})
        self.assertGreater(planned['tone_policy']['excluded_white_count'], 0)
        self.assertIn('背景严禁白色', planned['instructions'])
        with self.assertRaisesRegex(ValueError, '禁止白色'):
            source_colors.background_source('#FFFFFF', white['id'])

    def test_no_white_fallback_when_source_pool_has_only_white_neutrals_or_dark_colors(self):
        entries = [{'id': str(index), 'hex': color} for index, color in enumerate(
            ('#FFFFFF', '#FAF7FA', '#FFF1D7', '#292945'))]
        with mock.patch.object(background_plan, 'background_templates', return_value=entries):
            with self.assertRaisesRegex(ValueError, '非白'):
                background_plan.plan_background({'hair': '#000000'}, None)

    def test_frozen_quad_with_a_swapped_white_background_stops_without_repair(self):
        plans = self.make_variants()
        white = next(item for item in source_colors.background_templates()
                     if item['hex'] == '#FAF7FA')
        plans[0]['roles']['background'] = white['hex']
        plans[0]['source_selection']['background'] = {
            'template_id': white['id'], 'source_hd_id': white['source_hd_id'], 'hex': white['hex']}
        plans[0]['background_plan']['color'] = white['hex']
        before = deepcopy(plans)
        with self.assertRaisesRegex(ValueError, '拆换|来源'):
            self.make_variants({'variant_plans': plans})
        self.assertEqual(plans, before)

    def test_old_first_plan_is_superseded_only_by_complete_original_palettes(self):
        first = {'roles': {'skin_base': '#FF0000', 'background': '#FFFFFF'}}
        before = deepcopy(first)
        plans = self.make_variants(first_plan=first)
        self.assertEqual(first, before)
        for plan in plans:
            self.assertEqual(plan['roles'], source_colorways.colorway(plan['source_hd_id'])['roles'])
            self.assertTrue(source_colors.is_allowed_background(plan['roles']['background']))

    def test_default_white_colorway_is_skipped_as_a_whole_without_swapping_background(self):
        with self.synthetic_backgrounds({25: '#FFFFFF'}):
            plans = self.make_variants()
            self.assertEqual([plan['source_hd_id'] for plan in plans], [55, 16, 47, 15])
            for plan in plans:
                self.assertEqual(plan['roles'], source_colorways.colorway(plan['source_hd_id'])['roles'])
                self.assertEqual(plan['source_selection']['background']['source_hd_id'], plan['source_hd_id'])
                self.assertEqual(plan['source_selection']['skin']['source_hd_id'], plan['source_hd_id'])
            with self.assertRaisesRegex(ValueError, '白色.*另一套'):
                source_colorways.plan_for(25)
            with self.assertRaisesRegex(ValueError, '白色.*另一套'):
                self.make_variants({'colorway_reference_ids': [25, 55, 16, 47]})

    def test_complete_frozen_near_white_colorway_stops_instead_of_splitting_the_palette(self):
        plans = self.make_variants()
        before = deepcopy(plans)
        with self.synthetic_backgrounds({25: '#FFF1D7'}):
            with self.assertRaisesRegex(ValueError, '白色.*另一套'):
                self.make_variants({'variant_plans': plans})
        self.assertEqual(plans, before)

    def test_no_compliant_complete_catalog_stops_without_legacy_fallback(self):
        replacements = {item['source_hd_id']: '#FFFFFF'
                        for item in source_colorways.catalog()['colorways']}
        with self.synthetic_backgrounds(replacements):
            with self.assertRaisesRegex(ValueError, '没有.*合规整套'):
                source_colorways.eligible_colorways()
            with self.assertRaisesRegex(ValueError, '没有.*合规整套'):
                self.make_variants()

    def test_fewer_than_four_compliant_complete_palettes_cannot_be_padded_with_white(self):
        replacements = {item['source_hd_id']: '#FAF7FA'
                        for item in source_colorways.catalog()['colorways'][3:]}
        with self.synthetic_backgrounds(replacements):
            with self.assertRaisesRegex(ValueError, '不足四套'):
                self.make_variants()


if __name__ == '__main__':
    unittest.main()
