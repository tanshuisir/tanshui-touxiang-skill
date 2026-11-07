"""Four complete original palettes; no mixed source roles or model requests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import build_prompt
import source_colorways
import variant_plans


class VariantPlanTests(unittest.TestCase):
    def setUp(self):
        self.record = {'id': 25, 'technique': 'flat'}
        self.brief = {'mode': 'flat'}

    def make(self, brief=None, factory=None):
        return variant_plans.make_variant_plans(
            self.brief if brief is None else brief, None, self.record, 'finished',
            'expressive', factory or build_prompt.color_plan_for)

    def test_four_plans_copy_complete_role_relations_from_four_originals(self):
        plans = self.make()
        self.assertEqual([p['source_hd_id'] for p in plans], [25, 55, 16, 47])
        self.assertEqual([p['variant_index'] for p in plans], [1, 2, 3, 4])
        for plan in plans:
            source = source_colorways.colorway(plan['source_hd_id'])
            self.assertEqual(plan['roles'], source['roles'])
            self.assertEqual(plan['gradient'], source['gradient'])
            self.assertEqual(plan['source_selection']['skin']['source_hd_id'], source['source_hd_id'])
            self.assertEqual(plan['source_selection']['background']['source_hd_id'], source['source_hd_id'])
            self.assertEqual(plan['line_plan']['source_reference_id'], source['source_hd_id'])
            self.assertEqual(plan['roles']['outline'], plan['line_plan']['primary_hex'])
            self.assertFalse(plan['background_plan']['adjusted'])

    def test_random_mixed_factory_and_old_custom_swatches_cannot_change_reference_roles(self):
        factory = mock.Mock(side_effect=AssertionError('Mixed palette route must not run'))
        brief = dict(self.brief, art_palette='orange-ember', skin_template_id='HD-067-skin',
                     background_template_id='HD-006-bg-1', color_roles={'hair': '#FFFF00'},
                     gradient={'region': 'hair', 'from': '#FFFF00', 'to': '#FF8800'})
        with mock.patch('secrets.choice', side_effect=AssertionError('No random role selection')):
            plans = self.make(brief, factory)
        factory.assert_not_called()
        self.assertEqual(plans[0]['roles'], source_colorways.colorway(25)['roles'])

    def test_complete_frozen_plans_are_reused_without_new_selection(self):
        plans = self.make()
        with mock.patch('secrets.choice', side_effect=AssertionError('No random selection')):
            result = self.make(dict(self.brief, variant_plans=plans))
        self.assertEqual(result, plans)
        self.assertIsNot(result, plans)

    def test_previous_complete_policy_refreshes_metadata_without_changing_any_swatches(self):
        plans = self.make()
        before = deepcopy(plans)
        for plan in plans:
            background = plan['background_plan']
            background['instructions'] = (
                f"背景只用原作HD-{plan['source_hd_id']:03d}的{plan['roles']['background']}，"
                '满幅均匀不透明纯色；禁止渐变、纹理、投影或另换背景。')
            background['tone_policy'] = {
                'id': 'complete-source-bright-background-v1', 'minimum_brightness': 150,
                'selected_brightness': background['tone_policy']['selected_brightness']}
            background['scope'] = '完整同源色板与明亮背景约束；不是对新图效果的视觉验收'
        old = deepcopy(plans)
        refreshed = self.make(dict(self.brief, variant_plans=plans))
        self.assertEqual(plans, old)
        for original, current in zip(before, refreshed):
            self.assertEqual(current['roles'], original['roles'])
            self.assertEqual(current['gradient'], original['gradient'])
            self.assertEqual(current['source_colorway'], original['source_colorway'])
            self.assertEqual(current['background_plan'], original['background_plan'])
            self.assertEqual(current['background_policy_migration']['from'],
                             'complete-source-bright-background-v1')
            self.assertEqual(current['background_policy_migration']['to'],
                             'complete-source-bright-nonwhite-background-v2')
        selected = variant_plans.select_variant_plan(dict(self.brief, variant_plans=plans), 2)
        self.assertEqual(selected['background_policy_migration'],
                         refreshed[1]['background_policy_migration'])
        self.assertEqual(selected['color_roles'], before[1]['roles'])
        plans[0]['background_plan']['color'] = '#FFFFFF'
        with self.assertRaisesRegex(ValueError, '拆换|来源'):
            self.make(dict(self.brief, variant_plans=plans))

    def legacy_plans(self):
        plans = self.make()
        for plan in plans:
            legacy = source_colorways.colorway(plan['id'])['legacy_gradient_v1']
            plan.pop('gradient_policy_id')
            plan['gradient'] = deepcopy(legacy['gradient'])
            plan['gradient_options'] = deepcopy(legacy['gradient_options'])
            plan['background_plan']['gradient'] = deepcopy(legacy['gradient'])
            plan['source_colorway']['samples'].update(deepcopy(legacy['samples']))
        return plans

    def test_saved_original_colorways_refresh_gradients_without_changing_other_roles(self):
        legacy = self.legacy_plans()
        before = deepcopy(legacy)
        upgraded = self.make(dict(self.brief, variant_plans=legacy))
        self.assertEqual(legacy, before)
        for old, new in zip(legacy, upgraded):
            self.assertEqual(new['roles'], old['roles'])
            self.assertEqual(new['source_hd_id'], old['source_hd_id'])
            self.assertEqual(new['gradient'], source_colorways.colorway(new['id'])['gradient'])
            self.assertEqual(new['gradient_policy_id'], source_colorways.GRADIENT_POLICY_ID)
            self.assertIn('gradient_migration', new)
        self.assertNotEqual(upgraded[0]['gradient']['to'], legacy[0]['gradient']['to'])
        selected = variant_plans.select_variant_plan(dict(self.brief, variant_plans=legacy), 1)
        self.assertEqual(selected['gradient'], upgraded[0]['gradient'])

    def test_legacy_gradient_refresh_rejects_tampered_colors_and_endpoints(self):
        for mutate in (
                lambda p: p[0]['gradient'].update(to='#FF0000'),
                lambda p: p[0]['roles'].update(background=p[1]['roles']['background']),
                lambda p: p[0]['source_colorway']['samples']['gradient_to'].update(hex='#FF0000'),
                lambda p: p[0].update(gradient_policy_id='unknown')):
            broken = self.legacy_plans()
            mutate(broken)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.make(dict(self.brief, variant_plans=broken))

    def test_legacy_mixed_plans_migrate_as_whole_palettes_and_record_reason(self):
        legacy = [{'id': 'mint-apricot', 'roles': {'skin_base': '#FF0000', 'background': '#00FF00'}} for _ in range(4)]
        plans = self.make(dict(self.brief, variant_plans=legacy))
        self.assertEqual([p['source_hd_id'] for p in plans], [25, 55, 16, 47])
        self.assertTrue(all(p['migration']['from'] == 'legacy-mixed-colorways' for p in plans))
        self.assertEqual(legacy[0]['roles']['skin_base'], '#FF0000')

    def test_valid_swatches_from_other_originals_are_still_rejected(self):
        plans = self.make()
        mutations = (
            lambda p: p.pop(),
            lambda p: p[0]['roles'].update(skin_base=p[1]['roles']['skin_base']),
            lambda p: p[0]['roles'].update(background=p[1]['roles']['background']),
            lambda p: p[0]['roles'].update(hair=p[1]['roles']['hair']),
            lambda p: p[0]['roles'].update(clothing=p[1]['roles']['clothing']),
            lambda p: p[0]['roles'].update(outline=p[1]['roles']['outline']),
            lambda p: p[0]['roles'].update(cheek=p[1]['roles']['cheek']),
            lambda p: p[0]['gradient'].update(to=p[1]['gradient']['to']),
            lambda p: p[0]['source_colorway'].update(source_hd_id=55),
        )
        for mutate in mutations:
            broken = deepcopy(plans)
            mutate(broken)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.make(dict(self.brief, variant_plans=broken))

    def test_reference_ids_choose_whole_verified_templates_in_requested_order(self):
        plans = self.make(dict(self.brief, colorway_reference_ids=[6, 15, 49, 54]))
        self.assertEqual([p['source_hd_id'] for p in plans], [6, 15, 49, 54])
        for refs in ([25, 25, 16, 47], [25, 55, 16, 26], [25, 55, 16], [True, 55, 16, 47]):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.make(dict(self.brief, colorway_reference_ids=refs))

    def test_natural_four_colors_stops_instead_of_silently_overwriting_hair(self):
        with self.assertRaisesRegex(ValueError, '--variants 1'):
            variant_plans.make_variant_plans(self.brief, None, self.record, 'finished', 'natural', None)

    def test_selected_final_keeps_the_entire_original_colorway(self):
        plans = self.make()
        brief = dict(self.brief, variant_plans=plans, variants=4, photo='/input/photo.png')
        result = variant_plans.select_variant_plan(brief, 3)
        self.assertEqual(result['variants'], 1)
        self.assertEqual(result['source_colorway_id'], plans[2]['id'])
        self.assertNotIn('variant_plans', result)
        final = build_prompt.color_plan_for(result, self.record, 'finished', 'expressive')
        self.assertEqual(final['roles'], plans[2]['roles'])
        self.assertEqual(final['gradient'], plans[2]['gradient'])
        self.assertEqual(final['line_plan']['source_reference_id'], 16)
        for invalid in (0, 5, True, '2'):
            with self.subTest(index=invalid), self.assertRaises(ValueError):
                variant_plans.select_variant_plan(brief, invalid)


if __name__ == '__main__':
    unittest.main()
