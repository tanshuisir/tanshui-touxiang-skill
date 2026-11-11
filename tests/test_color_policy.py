"""All original palettes admitted unchanged; provenance remains mandatory."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest import mock

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import source_colors
import source_colorways
import variant_plans


class ColorPolicyTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)

    def make_variants(self,brief=None):
        return variant_plans.make_variant_plans(brief or {},None,{'id':25},'finished','expressive',None)

    def test_exactly_70_complete_palettes_are_available_without_tone_or_gradient_filter(self):
        candidates=source_colorways.eligible_colorways()
        self.assertEqual(len(candidates),70)
        self.assertEqual({x['source_hd_id'] for x in candidates},
                         {x['source_hd_id'] for x in source_colors.library()['sources']})
        self.assertEqual({x['source_hd_id'] for x in candidates}, set(range(1,71)))
        self.assertTrue(any(source_colors.background_brightness(x['roles']['background'])<150 for x in candidates))
        self.assertTrue(any(x['gradient'] is None for x in candidates))

    def test_white_nearwhite_dark_and_flat_sources_remain_exact_whole_palettes(self):
        for number in (1,4,34,53,63,69):
            with self.subTest(source=number):
                original=source_colorways.colorway(number)
                plan=source_colorways.plan_for(number)
                self.assertEqual(plan['roles'],original['roles'])
                self.assertEqual(plan['gradient'],original['gradient'])
                self.assertEqual(plan['background_plan']['color'],original['roles']['background'])
                source_colorways.validate_plan(plan)
                selected=source_colors.background_source(original['roles']['background'],original['background_template_id'])
                self.assertEqual(selected['source_hd_id'],number)

    def test_four_white_sources_can_be_explicitly_selected_and_frozen(self):
        plans=self.make_variants({'colorway_reference_ids':[4,34,53,63]})
        self.assertEqual([p['source_hd_id'] for p in plans],[4,34,53,63])
        before=deepcopy(plans)
        self.assertEqual(self.make_variants({'variant_plans':plans}),before)
        self.assertEqual(plans,before)

    def test_cross_source_background_changes_still_stop_without_silent_repair(self):
        plans=self.make_variants({'colorway_reference_ids':[25,55,16,47]})
        white=source_colorways.plan_for(63)
        plans[0]['roles']['background']=white['roles']['background']
        plans[0]['source_selection']['background']=white['source_selection']['background']
        plans[0]['background_plan']['color']=white['roles']['background']
        before=deepcopy(plans)
        with self.assertRaisesRegex(ValueError,'拆换|来源'):
            self.make_variants({'variant_plans':plans})
        self.assertEqual(plans,before)

    def test_flat_source_cannot_acquire_invented_gradient(self):
        flat=next(x for x in source_colorways.eligible_colorways() if x['gradient'] is None)
        plan=source_colorways.plan_for(flat['id'])
        self.assertIsNone(plan['gradient'])
        plan['gradient']={'region':'hair','from':'#FF98CF','to':'#FFFF00','direction':'从上到下'}
        with self.assertRaisesRegex(ValueError,'拆换|来源'):
            source_colorways.validate_plan(plan)

    def test_missing_catalog_does_not_fall_back_to_other_color_libraries(self):
        with mock.patch.object(source_colorways,'catalog',return_value={'colorways':[]}):
            with self.assertRaisesRegex(ValueError,'目录为空'):
                source_colorways.eligible_colorways()

    def test_insufficient_whole_palette_catalog_is_not_padded_with_duplicate_sources(self):
        available=source_colorways.eligible_colorways()[:3]
        with mock.patch.object(variant_plans,'eligible_colorways',return_value=available):
            with self.assertRaisesRegex(ValueError,'不足四套'):
                self.make_variants()

if __name__=='__main__':unittest.main()
