"""Offline color-policy checks; none of these claim a generated image passed."""
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
import review_avatar


class ArtisticColorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='avatar-art-color-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.photo = self.root/'photo.png'
        Image.new('RGB', (240, 320), '#BC8866').save(self.photo)
        self.brief = {'photo': str(self.photo),
                      'identity_features': ['圆下颌', '侧分棕发剪影', '长眼与宽眉眼间距'],
                      'expression': '闭口平静', 'pose': '轻微侧转'}
        self.palettes = json.loads((SKILL/'references/artistic-palettes.json').read_text())['palettes']

    def prepare(self, name='request', **kwargs):
        result = build_prompt.prepare(dict(self.brief, **kwargs), self.root/'brief.json', self.root/name)
        return result, Path(result['prompt_file']).read_text()

    def test_default_uses_art_colors_and_explicit_continuous_gradient_in_both_routes(self):
        for workflow in ('fast', 'review'):
            result, prompt = self.prepare(workflow, workflow=workflow)
            self.assertEqual(result['color_mode'], 'expressive')
            self.assertIn('不受照片原色约束', prompt)
            self.assertIn('连续过渡至', prompt)
            self.assertIn(result['color_plan']['gradient']['from'], prompt)
            self.assertIn(result['color_plan']['gradient']['to'], prompt)
            self.assertNotIn('不自动添加渐变', prompt)
            self.assertNotIn('保留照片肤发基调', prompt)

    def test_fixed_white_and_yellow_skin_palettes_override_photo_colors(self):
        for palette_id, expected in [('cobalt-white', '#FFFFFF'), ('forest-yellow', '#FFF265')]:
            result, prompt = self.prepare(palette_id, art_palette=palette_id)
            self.assertEqual(result['color_plan']['id'], palette_id)
            self.assertEqual(result['color_plan']['roles']['skin_base'], expected)
            self.assertIn('skin_base: '+expected, prompt)
            self.assertIn('颜色词只是原照观察', prompt)

    def test_all_modes_require_a_gradient_even_when_main_mode_is_flat(self):
        for mode in build_prompt.MODES:
            brief = {'mode': mode, 'art_palette': 'sky-lemon'}
            if mode == 'glitch':
                brief['palette_id'] = 40
            result, prompt = self.prepare(mode, **brief)
            self.assertEqual(result['mode'], mode)
            self.assertIn('渐变：必须在', prompt)
            self.assertIn('不能用两块硬切色', prompt)
            self.assertEqual(result['review_spec']['style_lock']['gradient'],
                             result['color_plan']['gradient'])

    def test_auto_can_select_different_palettes_without_inspecting_photo_colors(self):
        selected = []
        for index in (0, len(self.palettes)-1):
            with mock.patch.object(build_prompt.secrets, 'choice', side_effect=lambda values: values[index]):
                result, _ = self.prepare(str(index))
            selected.append(result['color_plan']['id'])
        self.assertNotEqual(*selected)

    def test_partial_color_override_keeps_remaining_roles_and_supports_explicit_gradient(self):
        gradient = {'region': 'background', 'from': '#3400FF', 'to': '#FFB300', 'direction': '从左向右'}
        result, prompt = self.prepare(art_palette='cobalt-white',
                                      color_roles={'background': '#3400FF'}, gradient=gradient)
        self.assertEqual(result['color_plan']['roles']['skin_base'], '#FFFFFF')
        self.assertEqual(result['color_plan']['roles']['background'], '#3400FF')
        self.assertEqual(result['color_plan']['gradient'], gradient)
        self.assertIn('从左向右', prompt)

    def test_invalid_or_zero_color_change_cannot_disable_required_gradient(self):
        for i, gradient in enumerate((None, False, {},
            {'region': 'hair', 'from': '#112233', 'to': '#112233'},
            {'region': 'hair', 'from': '#112233', 'to': '#112234'},
            {'region': 'face', 'from': '#112233', 'to': '#FFFFFF'})):
            with self.subTest(gradient=gradient), self.assertRaises(ValueError):
                self.prepare(str(i), gradient=gradient)

    def test_sample_provenance_matches_original_reference_data(self):
        catalog = json.loads((SKILL/'references/finished-reference-library.json').read_text())['portraits']
        by_id = {record['id']: record for record in catalog}
        seen = set()
        for palette in self.palettes:
            self.assertNotIn(palette['id'], seen)
            seen.add(palette['id'])
            original = {item['hex'].upper() for item in by_id[palette['source_hd_id']]['most_frequent_colors']}
            sampled = {color.upper() for color in palette['sampled_hex']}
            designed = {color.upper() for color in palette['designed_hex']}
            self.assertTrue(sampled <= original)
            used = set(palette['color_roles'].values()) | {palette['gradient']['from'], palette['gradient']['to']}
            self.assertTrue({color.upper() for color in used} <= sampled | designed)

    def test_explicit_review_has_color_and_gradient_evidence_item(self):
        result, _ = self.prepare(workflow='review')
        check = next(item for item in review_avatar.checks_for(result) if item['id'] == 'art_color_gradient')
        self.assertIn('连续二色渐变', check['expected'])
        self.assertIn(result['color_plan']['gradient']['to'], check['expected'])

    def test_legacy_reference_palette_does_not_claim_an_hd_source(self):
        result, _ = self.prepare(palette_id=24, art_palette='reference')
        self.assertIsNone(result['color_plan']['source_hd_id'])
        self.assertEqual(result['reference_set'], 'legacy')

    def test_old_color_locks_are_explicitly_superseded_without_losing_structure(self):
        plan = build_prompt.identity_plan_for(self.brief, self.brief['identity_features'])
        plan[1]['do_not_change'] = '不能改成金发；保留侧分发型轮廓'
        result, prompt = self.prepare(identity_plan=plan, art_palette='mint-apricot')
        self.assertIn('保留侧分发型轮廓', prompt)
        self.assertIn('旧brief内保留原色或禁止改色约束不再生效', prompt)
        self.assertEqual(result['color_plan']['roles']['hair'], '#FFE4A6')
        self.assertIn('本次角色色优先', result['review_spec']['style_lock']['color_policy'])


if __name__ == '__main__':
    unittest.main()
