"""Source-role restrictions and provenance, entirely offline."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import build_prompt
import source_colors
import review_avatar


class SourceColorTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-source-color-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root/'photo.png'
        Image.new('RGB', (240, 320), '#125599').save(self.photo)
        self.brief = {'photo': str(self.photo), 'identity_features': ['圆下颌', '短发轮廓', '宽眼距'],
                      'expression': '闭口平视', 'pose': '近正面'}
        self.data = source_colors.library()

    def request(self, name='request', **overrides):
        request = build_prompt.prepare(dict(self.brief, **overrides), self.root/'brief.json', self.root/name)
        return request, Path(request['prompt_file']).read_text()

    def test_every_original_has_role_samples_matching_actual_pixels_and_hash(self):
        catalog = json.loads((SKILL/'references/finished-reference-library.json').read_text())
        expected = {item['id'] for item in catalog['portraits']}
        self.assertEqual(len(expected), 70)
        self.assertEqual({item['source_hd_id'] for item in self.data['skins']}, expected)
        self.assertEqual({item['source_hd_id'] for item in self.data['backgrounds']}, expected)
        by_id = {item['source_hd_id']: item for item in self.data['sources']}
        for number in expected:
            source = SKILL/by_id[number]['source_image']
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), by_id[number]['source_sha256'])
            with Image.open(source) as original:
                image = original.convert('RGB')
                skin = next(item for item in self.data['skins'] if item['source_hd_id'] == number)
                points = [skin['base'], skin['shadow'], *skin['additional_skin_samples']]
                points += [item for item in self.data['backgrounds'] if item['source_hd_id'] == number]
                for point in filter(None, points):
                    self.assertEqual('#%02X%02X%02X' % image.getpixel(tuple(point['xy'])), point['hex'])

    def test_every_skin_identifier_belongs_to_current_template_namespace(self):
        for item in self.data['skins']:
            self.assertEqual(item['id'],f"TS-{item['source_hd_id']:03d}-skin")
            self.assertEqual(self.data['sources'][item['source_hd_id']-1]['source_image'],
                             f"assets/templates/{item['source_hd_id']:03d}.png")

    def test_skin_pair_is_preserved_from_one_current_template(self):
        import source_colorways
        for item in self.data['skins']:
            plan=source_colorways.plan_for(item['source_hd_id'])
            self.assertEqual(plan['roles']['skin_base'],item['base']['hex'])
            self.assertEqual(plan['roles']['skin_shadow'],(item['shadow'] or item['base'])['hex'])

    def test_null_custom_roles_selects_a_source_template(self):
        request, _ = self.request(color_roles=None)
        self.assertIn(request['color_plan']['source_selection']['skin']['template_id'],
                      {item['id'] for item in self.data['skins']})

    def test_all_modes_stages_and_routes_use_only_same_role_colors(self):
        skin_pairs = {(item['base']['hex'], (item['shadow'] or item['base'])['hex']) for item in self.data['skins']}
        backgrounds = {item['hex'] for item in self.data['backgrounds']}
        for mode in build_prompt.MODES:
            for workflow in ('fast', 'review'):
                for stage in ('preview', 'final'):
                    with self.subTest(mode=mode, workflow=workflow, stage=stage):
                        request, prompt = self.request(f'{mode}-{workflow}-{stage}', mode=mode, workflow=workflow, stage=stage)
                        roles = request['color_plan']['roles']
                        self.assertIn((roles['skin_base'], roles['skin_shadow']), skin_pairs)
                        self.assertIn(roles['background'], backgrounds)
                        self.assertEqual(roles['background'], request['color_plan']['source_selection']['background']['hex'])
                        self.assertEqual(request['master_encoding'], 'semantic-props-v3')
                        self.assertEqual(request['variant_plans'][0]['roles'], roles)
                        self.assertIn('所有皮肤主面（脸耳颈手臂）#FF0000', prompt)
                        self.assertIn('皮肤硬边暗面#00FF00', prompt)
                        self.assertIn('背景#FFFFFF', prompt)
                        self.assertEqual(request['argv'].count('--image'), 2)
                        self.assertFalse(request['executed'])

    def test_invalid_old_colors_and_natural_cannot_bypass_role_library(self):
        with self.assertRaises(ValueError):
            self.request(color_mode='natural')
        request, prompt = self.request(color_roles={'skin_base':'#010203','background':'#00DDD6'})
        plan=request['color_plan']
        self.assertEqual(plan['source_selection']['skin']['source_hd_id'],plan['source_hd_id'])
        self.assertEqual(plan['source_selection']['background']['source_hd_id'],plan['source_hd_id'])
        self.assertIn('migration',plan)

    def test_frozen_template_ids_preserve_color_pair_and_background_in_final(self):
        first, _ = self.request(art_palette='TS-047')
        plan = first['color_plan']
        second, _ = self.request('final', stage='final', art_palette=plan['id'],
                                  palette_selection=plan.get('palette_selection'),
                                  color_roles=plan['roles'], gradient=plan['gradient'],
                                  skin_template_id=plan['source_selection']['skin']['template_id'],
                                  background_template_id=plan['source_selection']['background']['template_id'])
        self.assertEqual(first['color_plan'], second['color_plan'])
        self.assertEqual(first['background_plan']['color'], second['background_plan']['color'])

    def test_current_explicit_template_background_is_preserved_in_every_route(self):
        number=69
        for workflow in ('fast','review'):
            for stage in ('preview','final'):
                request,prompt=self.request(f'{workflow}-{stage}',workflow=workflow,stage=stage,
                                            source_colorway_id=f'TS-{number:03d}-colorway')
                selected=request['color_plan']['source_selection']
                self.assertEqual(selected['background']['source_hd_id'],number)
                self.assertEqual(selected['skin']['source_hd_id'],number)
                self.assertEqual(request['background_plan']['color'],selected['background']['hex'])
                self.assertIn('背景#FFFFFF',prompt)
                self.assertFalse(request['executed'])

    def test_unknown_template_ids_migrate_to_one_complete_original(self):
        for field in ('skin_template_id','background_template_id'):
            request,_=self.request(field,**{field:'invented-template'})
            plan=request['color_plan']
            self.assertEqual(plan['source_selection']['skin']['source_hd_id'],plan['source_hd_id'])
            self.assertEqual(plan['source_selection']['background']['source_hd_id'],plan['source_hd_id'])
            self.assertIn('migration',plan)

    def test_missing_library_stops_without_a_designed_fallback(self):
        source_colors.library.cache_clear()
        try:
            with mock.patch.object(source_colors, 'LIBRARY', self.root/'missing-library.json'):
                with self.assertRaises(OSError):
                    self.request()
        finally:
            source_colors.library.cache_clear()

    def test_review_binds_both_selected_roles_and_hair_palettes_cannot_define_them(self):
        request, _ = self.request(workflow='review')
        check = next(item for item in review_avatar.checks_for(request) if item['id'] == 'source_skin_background')
        self.assertIn(request['color_plan']['roles']['skin_base'], check['expected'])
        self.assertIn(request['color_plan']['roles']['background'], check['expected'])
        self.assertTrue(check['expected'])


if __name__ == '__main__':
    unittest.main()
