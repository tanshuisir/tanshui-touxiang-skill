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
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.record = {'id': 25, 'technique': 'flat'}
        self.brief = {'mode': 'flat'}

    def make(self, brief=None, factory=None):
        return variant_plans.make_variant_plans(
            self.brief if brief is None else brief, None, self.record, 'finished',
            'expressive', factory or build_prompt.color_plan_for)

    def test_four_plans_copy_complete_role_relations_from_four_originals(self):
        plans = self.make()
        self.assertEqual(len({p['source_hd_id'] for p in plans}), 4)
        self.assertTrue(all(p['source_hd_id'] in {item['source_hd_id'] for item in source_colorways.eligible_colorways()} for p in plans))
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
        brief = dict(self.brief, art_palette='orange-ember', skin_template_id='TS-067-skin',
                     background_template_id='TS-006-bg-1', color_roles={'hair': '#FFFF00'},
                     gradient={'region': 'hair', 'from': '#FFFF00', 'to': '#FF8800'})
        with mock.patch('secrets.choice', side_effect=AssertionError('No random role selection')):
            plans = self.make(brief, factory)
        factory.assert_not_called()
        self.assertEqual(plans[0]['roles'], source_colorways.colorway(plans[0]['source_hd_id'])['roles'])

    def test_complete_frozen_plans_are_reused_without_new_selection(self):
        plans = self.make()
        with mock.patch('secrets.choice', side_effect=AssertionError('No random selection')):
            result = self.make(dict(self.brief, variant_plans=plans))
        self.assertEqual(result, plans)
        self.assertIsNot(result, plans)

    def test_stale_background_policy_requires_explicit_new_template_choice(self):
        plans = self.make(dict(self.brief,colorway_reference_ids=[25,55,16,47]))
        plans[0]['background_plan']['tone_policy']['id'] = 'prior-library-background'
        with self.assertRaisesRegex(ValueError, '拆换|来源'):
            self.make(dict(self.brief, variant_plans=plans))

    def old_plans(self):
        plans = self.make(dict(self.brief, colorway_reference_ids=[25,55,16,47]))
        for plan in plans:
            plan.pop('gradient_policy_id')
        return plans

    def test_old_gradient_versions_are_rejected_without_reusing_old_artwork(self):
        plans = self.old_plans()
        before = deepcopy(plans)
        with self.assertRaisesRegex(ValueError, '重新选择TS'):
            self.make(dict(self.brief, variant_plans=plans))
        self.assertEqual(plans, before)

    def test_old_source_hash_is_rejected_even_if_numeric_identifier_matches(self):
        plans = self.make(dict(self.brief, colorway_reference_ids=[25,55,16,47]))
        plans[0]['source_colorway']['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, '拆换|来源'):
            self.make(dict(self.brief, variant_plans=plans))

    def test_unversioned_mixed_plans_require_explicit_new_template_selection(self):
        previous = [{'id': 'obsolete', 'roles': {'skin_base': '#FF0000'}} for _ in range(4)]
        with self.assertRaisesRegex(ValueError, '重新选择TS'):
            self.make(dict(self.brief, variant_plans=previous))

    def test_valid_swatches_from_other_originals_are_still_rejected(self):
        plans = self.make(dict(self.brief, colorway_reference_ids=[25,55,16,47]))
        mutations = (
            lambda p: p.pop(),
            lambda p: p[0]['roles'].update(skin_base=p[1]['roles']['skin_base']),
            lambda p: p[0]['roles'].update(background=p[1]['roles']['background']),
            lambda p: p[0]['roles'].update(hair=p[1]['roles']['hair']),
            lambda p: p[0]['roles'].update(clothing=p[1]['roles']['clothing']),
            lambda p: p[0]['roles'].update(outline=p[1]['roles']['outline']),
            lambda p: p[0]['roles'].update(cheek=p[1]['roles']['cheek']),
            lambda p: p[0].update(gradient={'region':'hair','from':'#010203','to':'#040506'}),
            lambda p: p[0]['source_colorway'].update(source_hd_id=p[1]['source_hd_id']),
        )
        for mutate in mutations:
            broken = deepcopy(plans)
            mutate(broken)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.make(dict(self.brief, variant_plans=broken))

    def test_reference_ids_choose_whole_verified_templates_in_requested_order(self):
        plans = self.make(dict(self.brief, colorway_reference_ids=[6, 15, 49, 54]))
        self.assertEqual([p['source_hd_id'] for p in plans], [6, 15, 49, 54])
        for refs in ([25, 25, 16, 47], [25, 55, 16, 71], [25, 55, 16], [True, 55, 16, 47]):
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
        self.assertEqual(final['line_plan']['source_reference_id'], plans[2]['source_hd_id'])
        for invalid in (0, 5, True, '2'):
            with self.subTest(index=invalid), self.assertRaises(ValueError):
                variant_plans.select_variant_plan(brief, invalid)


if __name__ == '__main__':
    unittest.main()
