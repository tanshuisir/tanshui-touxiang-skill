"""Offline background-planning checks; no generated-picture quality claims."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import background_plan
import source_colors


class BackgroundPlanTests(unittest.TestCase):
    def setUp(self):
        self.palettes = json.loads((SKILL / 'references/artistic-palettes.json').read_text())['palettes']
        self.background_colors = {item['hex'] for item in source_colors.background_templates()}

    def test_all_eight_palettes_have_traceable_separated_background_plans(self):
        self.assertEqual(len(self.palettes), 8)
        for palette in self.palettes:
            with self.subTest(palette=palette['id']):
                roles, gradient = deepcopy(palette['color_roles']), deepcopy(palette['gradient'])
                before = deepcopy((roles, gradient))
                subject_gradient = gradient if gradient['region'] in ('hair', 'clothing') else None
                result = background_plan.plan_background(roles, subject_gradient)
                self.assertRegex(result['color'], r'^#[0-9A-F]{6}$')
                self.assertEqual((roles, gradient), before)
                self.assertTrue(result['meets_plan'], result)
                self.assertIsNone(result['original_color'])
                self.assertIn(result['color'], self.background_colors)
                self.assertIn('完全不透明', result['instructions'])
                self.assertEqual(result['gradient'], subject_gradient)

    def test_purple_hair_and_clothes_with_white_skin_get_a_distinct_background(self):
        roles = {'background': '#7B61FE', 'hair': '#4706F3', 'clothing': '#7B61FE',
                 'skin_base': '#FFFFFF', 'outline': '#350F91'}
        result = background_plan.plan_background(roles, None)
        self.assertTrue(result['adjusted'])
        self.assertTrue(result['meets_plan'])
        self.assertNotIn(result['color'], (roles['hair'], roles['clothing'], roles['skin_base']))
        self.assertIn(result['color'], self.background_colors)

    def test_same_background_and_subject_is_corrected_without_changing_subject(self):
        roles = {'background': '#663399', 'hair': '#663399', 'clothing': '#663399'}
        result = background_plan.plan_background(roles, {'region': 'hair', 'from': '#663399', 'to': '#CA8CE2'})
        self.assertTrue(result['adjusted'])
        self.assertTrue(result['meets_plan'])
        self.assertEqual(roles, {'background': '#663399', 'hair': '#663399', 'clothing': '#663399'})
        self.assertEqual(result['gradient']['region'], 'hair')
        self.assertEqual(result['gradient']['from'], '#663399')

    def test_suitable_existing_background_and_subject_gradient_are_preserved(self):
        roles = {'background': '#A1E5D2', 'hair': '#000000', 'clothing': '#000000'}
        gradient = {'region': 'hair', 'from': '#000000', 'to': '#222222'}
        self.assertIn(roles['background'], self.background_colors)
        result = background_plan.plan_background(roles, gradient)
        self.assertFalse(result['adjusted'])
        self.assertEqual(result['color'], roles['background'])
        self.assertEqual(result['gradient'], gradient)

    def test_outside_background_cannot_survive_even_if_it_has_good_contrast(self):
        outside = '#010203'
        self.assertNotIn(outside, self.background_colors)
        roles = {'background': outside, 'hair': '#FFFFFF', 'clothing': '#FFFFFF'}
        result = background_plan.plan_background(roles, None)
        self.assertTrue(result['adjusted'])
        self.assertNotEqual(result['color'], outside)
        self.assertIn(result['color'], self.background_colors)

    def test_insufficient_source_contrast_never_introduces_designed_fallback_colors(self):
        # An impossible source pool must stay source-only and disclose its
        # contrast limitation rather than inventing a convenient new RGB.
        with mock.patch.object(background_plan, 'background_templates',
                               return_value=[{'id': 'only-source', 'hex': '#FFCEDA'},
                                             {'id': 'dark-source', 'hex': '#101010'}]):
            result = background_plan.plan_background(
                {'background': '#101010', 'hair': '#FFCEDA', 'clothing': '#FFCEDA'}, None)
        self.assertEqual(result['color'], '#FFCEDA')
        self.assertFalse(result['meets_plan'])

    def test_saved_dark_source_background_is_migrated_even_when_contrast_is_good(self):
        for dark in ('#292945', '#281D48', '#034C33', '#4E3440', '#0732F7'):
            with self.subTest(background=dark):
                self.assertIn(dark, self.background_colors)
                result = background_plan.plan_background(
                    {'background': dark, 'hair': '#FFFFFF', 'clothing': '#FFE4A6'}, None)
                self.assertTrue(result['adjusted'])
                self.assertNotEqual(result['color'], dark)
                self.assertIn(result['color'], self.background_colors)
                self.assertGreaterEqual(result['tone_policy']['selected_brightness'], 150)

    def test_no_foreground_still_chooses_only_bright_source_backgrounds(self):
        light = {'id': 'light-source', 'hex': '#A1E5D2'}
        dark = {'id': 'dark-source', 'hex': '#292945'}
        with mock.patch.object(background_plan, 'background_templates', return_value=[dark, light]):
            result = background_plan.plan_background({'background': dark['hex']}, None)
        self.assertEqual(result['color'], light['hex'])
        self.assertEqual(result['tone_policy']['candidate_count'], 1)
        self.assertEqual(result['tone_policy']['excluded_dark_count'], 1)

    def test_all_dark_source_pool_stops_instead_of_restoring_dark_fallback(self):
        with mock.patch.object(background_plan, 'background_templates',
                               return_value=[{'id': 'only-dark', 'hex': '#292945'}]):
            with self.assertRaisesRegex(ValueError, '没有符合明亮偏好'):
                background_plan.plan_background({'hair': '#FFFFFF'}, None)

    def test_natural_hair_missing_uses_known_clothes_without_inventing_hair(self):
        result = background_plan.plan_background({'background': '#112244', 'clothing': '#112244',
                                                  'outline': '#101010'}, None)
        self.assertTrue(result['adjusted'])
        self.assertTrue(result['meets_plan'])
        self.assertNotIn('hair', result['evaluated_roles'])
        self.assertIn('hair', result['unevaluated_roles'])
        self.assertIn('clothing', result['evaluated_roles'])

    def test_planner_rejects_background_gradients_even_when_they_have_valid_colors(self):
        gradient = {'region': 'background', 'from': '#6655AA', 'to': '#6655AA', 'direction': '从左向右'}
        roles = {'background': '#6655AA', 'hair': '#6655AA', 'clothing': '#7766BB', 'skin_base': '#FFFFFF'}
        with self.assertRaises(ValueError):
            background_plan.plan_background(roles, gradient)

    def test_even_previously_suitable_palette_background_gradient_is_rejected(self):
        palette = next(item for item in self.palettes if item['id'] == 'sky-lemon')
        with self.assertRaises(ValueError):
            background_plan.plan_background(palette['color_roles'], palette['gradient'])

    def test_frozen_palette_keeps_background_and_gradient_across_stages(self):
        for palette in self.palettes:
            for natural in (False, True):
                with self.subTest(palette=palette['id'], natural=natural):
                    roles = deepcopy(palette['color_roles'])
                    if natural:
                        roles.pop('hair', None)
                    gradient = palette['gradient'] if palette['gradient']['region'] in ('hair', 'clothing') else None
                    first = background_plan.plan_background(roles, gradient)
                    roles['background'] = first['color']
                    second = background_plan.plan_background(roles, first['gradient'])
                    self.assertEqual(first['color'], second['color'])
                    self.assertEqual(first['gradient'], second['gradient'])

    def test_unknown_textual_roles_are_disclosed_and_not_changed(self):
        roles = {'background': '#123456', 'hair': '自然黑发', 'clothing': '#FFFFFF'}
        result = background_plan.plan_background(roles, None)
        self.assertEqual(result['unevaluated_roles'], ['hair'])
        self.assertIn('未计算非HEX角色', result['reason'])
        self.assertEqual(roles['hair'], '自然黑发')
        no_colors = background_plan.plan_background({'hair': '自然发色'}, None)
        self.assertFalse(no_colors['meets_plan'])
        self.assertIn('无法判断', no_colors['reason'])
        self.assertIn(no_colors['color'], self.background_colors)

    def test_invalid_input_is_not_silently_treated_as_a_valid_plan(self):
        for roles, gradient in (([], None), ({}, []),
                                ({'clothing': '#112233'}, {'region': 'background', 'from': 'red', 'to': '#FFFFFF'})):
            with self.subTest(roles=roles, gradient=gradient), self.assertRaises(ValueError):
                background_plan.plan_background(roles, gradient)


if __name__ == '__main__':
    unittest.main()
