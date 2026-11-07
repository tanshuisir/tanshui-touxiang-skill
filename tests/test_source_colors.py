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
        self.assertEqual(len(expected), 69)
        self.assertEqual({item['source_hd_id'] for item in self.data['skins']}, expected)
        self.assertEqual({item['source_hd_id'] for item in self.data['backgrounds']}, expected)
        by_id = {item['id']: item for item in self.data['sources']}
        for number in expected:
            source = SKILL/by_id[number]['image']
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), by_id[number]['sha256'])
            with Image.open(source) as original:
                image = original.convert('RGB')
                skin = next(item for item in self.data['skins'] if item['source_hd_id'] == number)
                points = [skin['base'], skin['shadow'], *skin['additional_skin_samples']]
                points += [item for item in self.data['backgrounds'] if item['source_hd_id'] == number]
                for point in filter(None, points):
                    self.assertEqual('#%02X%02X%02X' % image.getpixel(tuple(point['xy'])), point['hex'])

    def test_hd035_uses_warm_skin_instead_of_its_cyan_hair(self):
        item = next(item for item in self.data['skins'] if item['source_hd_id'] == 35)
        self.assertEqual(item['base']['hex'], '#FCBBB8')
        self.assertNotEqual(item['base']['hex'], '#B2EAEE')

    def test_hd043_keeps_main_skin_separate_from_cheek_color(self):
        item = next(item for item in self.data['skins'] if item['source_hd_id'] == 43)
        self.assertEqual(item['base']['hex'], '#FFCEDA')
        self.assertEqual(item['shadow']['hex'], '#FFA4BA')

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
                        self.assertGreaterEqual(request['background_plan']['tone_policy']['selected_brightness'], 150)
                        self.assertFalse(source_colors.is_white_background(roles['background']))
                        self.assertEqual(request['master_encoding'], 'semantic-cube-v1')
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
        first, _ = self.request(art_palette='teal-coral')
        plan = first['color_plan']
        second, _ = self.request('final', stage='final', art_palette=plan['id'],
                                  color_roles=plan['roles'], gradient=plan['gradient'],
                                  skin_template_id=plan['source_selection']['skin']['template_id'],
                                  background_template_id=plan['source_selection']['background']['template_id'])
        self.assertEqual(first['color_plan'], second['color_plan'])
        self.assertEqual(first['background_plan']['color'], second['background_plan']['color'])

    def test_saved_dark_template_migrates_in_all_color_modes_stages_and_routes(self):
        dark_id = 'HD-069-bg-1'
        dark = next(item['hex'] for item in self.data['backgrounds'] if item['id'] == dark_id)
        for color_mode in ('expressive',):
            for workflow in ('fast', 'review'):
                for stage in ('preview', 'final'):
                    with self.subTest(color_mode=color_mode, workflow=workflow, stage=stage):
                        request, prompt = self.request(f'dark-{color_mode}-{workflow}-{stage}',
                            color_mode=color_mode, workflow=workflow, stage=stage,
                            background_template_id=dark_id,
                            color_roles={'background': dark, 'hair': '#125599'} if color_mode == 'natural'
                            else {'background': dark},
                            skin_template_id='HD-022-skin')
                        selected = request['color_plan']['source_selection']
                        self.assertNotEqual(selected['background']['template_id'], dark_id)
                        self.assertNotEqual(selected['background']['hex'], dark)
                        self.assertEqual(request['variant_plans'][0]['roles']['background'],
                                         selected['background']['hex'])
                        self.assertIn('背景#FFFFFF', prompt)
                        self.assertFalse(source_colors.is_white_background(selected['background']['hex']))
                        self.assertGreaterEqual(request['background_plan']['tone_policy']['selected_brightness'], 150)
                        self.assertEqual(selected['skin']['source_hd_id'], selected['background']['source_hd_id'])
                        self.assertIn('migration', request['color_plan'])
                        self.assertFalse(request['executed'])

    def test_unknown_template_ids_migrate_to_one_complete_original(self):
        for field in ('skin_template_id','background_template_id'):
            request,_=self.request(field,**{field:'invented-template'})
            plan=request['color_plan']
            self.assertEqual(plan['source_hd_id'],25)
            self.assertEqual(plan['source_selection']['skin']['source_hd_id'],25)
            self.assertEqual(plan['source_selection']['background']['source_hd_id'],25)
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
        palettes = json.loads((SKILL/'references/artistic-palettes.json').read_text())['palettes']
        for palette in palettes:
            self.assertFalse({'skin_base', 'skin_shadow', 'background'} & set(palette['color_roles']))


if __name__ == '__main__':
    unittest.main()
