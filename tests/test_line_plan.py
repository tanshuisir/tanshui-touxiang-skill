"""Verify traced ink selection and its use in both prompt routes, offline."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import run_avatar
from line_plan import CORE_ROLES, FAMILY_IDS, plan_lines
from avatar_test_fixture import encoded_fixture
from recolor_avatar import ENCODING


def fixture_library():
    return {
        'schema_version': 1,
        'portraits': [
            {'id': number, 'label': f'TS-{number:03d}', 'line_family': family,
             'primary_hex': color, 'primary_sample_xy': [100, 200],
             'secondary_colors': [{'hex': '#FFFF00', 'role': 'accent', 'sample_xy': [10, 20]}]}
            for number, color, family in ((25, '#0A654B', 'rounded-monoline'),
                                           (26, '#092356', 'rounded-monoline'),
                                           (67, '#C53B27', 'rounded-monoline'))],
        'families': [{'id': family, 'name': family, 'instructions': '按此分类概括轮廓'}
                     for family in FAMILY_IDS],
        'role_rules': {role: {'label': role, 'instructions': '保留必要结构线', 'width_ratio': 1}
                       for role in CORE_ROLES},
    }


class LineSelectionTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.library = fixture_library()

    def plan(self, brief=None, palette=25, reference=25, mode='flat'):
        return plan_lines(brief or {}, self.library, palette, reference, mode)

    def test_palette_source_then_hd_reference_then_default_are_deterministic(self):
        self.assertEqual(self.plan(palette=26)['source_reference_id'], 26)
        self.assertEqual(self.plan(palette=None, reference=26)['source_reference_id'], 26)
        self.assertEqual(self.plan(palette=None, reference=None)['source_reference_id'], 25)
        self.assertEqual(self.plan(palette=26), self.plan(palette=26))

    def test_explicit_reference_and_family_select_independent_library_properties(self):
        plan = self.plan({'line_reference_id': 67, 'line_family': 'fine-structured'})
        self.assertEqual(plan['primary_hex'], '#C53B27')
        self.assertEqual(plan['family_id'], 'fine-structured')
        self.assertEqual(plan['source_reference_id'], 67)
        self.assertEqual(set(plan['role_colors']), set(CORE_ROLES))
        self.assertEqual(set(plan['role_colors'].values()), {'#C53B27'})
        self.assertFalse(plan['secondary_enabled'])

    def test_explicit_known_ink_resolves_to_real_source_even_if_not_palette_ink(self):
        plan = self.plan({'color_roles': {'outline': '#092356'}})
        self.assertEqual(plan['source_reference_id'], 26)
        self.assertEqual(plan['primary_hex'], '#092356')

    def test_unknown_ink_is_rejected_instead_of_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, '旧 brief'):
            self.plan({'color_roles': {'outline': '#123456'}})

    def test_conflicting_explicit_reference_and_ink_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '冲突'):
            self.plan({'line_reference_id': 25, 'color_roles': {'outline': '#092356'}})
        accepted = self.plan({'line_reference_id': 25, 'color_roles': {'outline': '#0a654b'}})
        self.assertEqual(accepted['primary_hex'], '#0A654B')

    def test_modes_use_library_categories_without_enabling_accents(self):
        for mode, family in (('bold', 'bold-graphic'), ('cartoon', 'bold-graphic'),
                             ('texture', 'fine-structured'), ('duotone', 'open-duotone'),
                             ('glitch', 'offset-accent')):
            with self.subTest(mode=mode):
                plan = self.plan(mode=mode)
                self.assertEqual(plan['family_id'], family)
                self.assertFalse(plan['secondary_enabled'])
                self.assertEqual(plan['primary_hex'], '#0A654B')

    def test_missing_or_unknown_evidence_cannot_become_a_verified_line_plan(self):
        for brief in ({'line_reference_id': 71}, {'line_reference_id': True},
                      {'line_family': 'arbitrary-brush'},
                      {'color_roles': {'outline': 'random green'}}):
            with self.subTest(brief=brief), self.assertRaises(ValueError):
                self.plan(brief)
        del self.library['portraits'][0]['primary_sample_xy']
        with self.assertRaisesRegex(ValueError, '采样坐标'):
            self.plan()


class LineLibraryIntegrationTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-lines-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        Image.new('RGB', (240, 320), '#BA8968').save(self.photo)
        self.brief = {'photo': str(self.photo), 'identity_features': ['圆下颌', '短发轮廓', '窄眉眼'],
                      'expression': '闭口平静', 'pose': '近正面'}
        self.library = json.loads((SKILL / 'references/line-library.json').read_text())

    def prepare(self, name='request', **changes):
        result = build_prompt.prepare(dict(self.brief, **changes), self.root / 'brief.json',
                                      self.root / name)
        return result, Path(result['prompt_file']).read_text()

    def test_every_finished_reference_has_exact_raster_color_evidence(self):
        image_ids = {int(path.stem) for path in (SKILL / 'assets/templates').glob('*.png')}
        records = self.library['portraits']
        self.assertEqual(len(records), len(image_ids))
        self.assertEqual({item['id'] for item in records}, image_ids)
        for item in records:
            with self.subTest(reference=item['id']):
                path = SKILL / item['reference_image']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
                with Image.open(path) as original:
                    pixel = original.convert('RGB').getpixel(tuple(item['primary_sample_xy']))
                    self.assertEqual('#' + ''.join(f'{channel:02X}' for channel in pixel),
                                     item['primary_hex'].upper())
                    for sample in item.get('secondary_colors', []):
                        pixel = original.convert('RGB').getpixel(tuple(sample['sample_xy']))
                        self.assertEqual('#' + ''.join(f'{channel:02X}' for channel in pixel),
                                         sample['hex'].upper())

    def test_both_prompt_routes_use_line_library_without_changing_native_output_or_eyes(self):
        for workflow in ('fast', 'review'):
            result, prompt = self.prepare(workflow, workflow=workflow)
            line = result['line_plan']
            self.assertEqual(result['color_plan']['roles']['outline'], line['primary_hex'])
            self.assertEqual(result['review_spec']['style_lock']['lines'], line)
            self.assertEqual(result['master_encoding'], 'semantic-props-v3')
            self.assertEqual(result['variant_plans'][0]['roles']['outline'], line['primary_hex'])
            self.assertIn(line['family_instructions'], prompt)
            for color in ENCODING.values():
                self.assertIn(color, prompt)
            self.assertIn('统一眼睛：', prompt)
            self.assertIn('背景满幅单一白色', prompt)
            self.assertIn('纯色', result['background_plan']['instructions'])
            self.assertEqual(result['argv'][result['argv'].index('--size') + 1], '1024x1024')

    def test_selected_source_keeps_its_whole_palette_and_measured_ink(self):
        result,_=self.prepare(source_colorway_id='TS-047-colorway')
        record=next(item for item in self.library['portraits'] if item['id']==47)
        self.assertEqual(result['line_plan']['source_reference_id'],47)
        self.assertEqual(result['color_plan']['roles']['outline'],record['primary_hex'].upper())
        self.assertEqual(result['color_plan']['source_selection']['background']['source_hd_id'],47)

    def test_new_auto_requests_change_colorway_but_explicit_sources_keep_measured_ink(self):
        first, _ = self.prepare('one')
        second, _ = self.prepare('two')
        self.assertNotEqual(first['color_plan']['id'], second['color_plan']['id'])
        frozen, _ = self.prepare('frozen', source_colorway_id=first['color_plan']['id'])
        self.assertEqual(first['line_plan'], frozen['line_plan'])
        self.assertEqual(first['color_plan']['roles']['outline'], frozen['color_plan']['roles']['outline'])

    def test_all_prompt_routes_read_current_hair_rules_after_legacy_detail_cues(self):
        updated = json.loads(json.dumps(self.library))
        expected = {
            workflow: {role: f'本次维护库的{workflow}/{role}规则' for role in CORE_ROLES}
            for workflow in ('fast', 'review')
        }
        for role in CORE_ROLES:
            updated['role_rules'][role]['short_instructions'] = expected['fast'][role]
            updated['role_rules'][role]['instructions'] = expected['review'][role]
        hair = updated['role_rules']['hair']
        hair['policy_id'] = 'new-maintained-hair-policy'
        hair['precedence'] = '本轮发型优先级来自维护库'
        original_read = Path.read_text
        def with_updated_library(path, *args, **kwargs):
            if path == SKILL / 'references/line-library.json':
                return json.dumps(updated, ensure_ascii=False)
            return original_read(path, *args, **kwargs)
        import source_colorways
        with mock.patch.object(Path, 'read_text', with_updated_library), mock.patch.object(source_colorways, 'line_library', return_value=updated):
            for workflow in ('fast', 'review'):
                for stage in ('preview', 'final'):
                    for source in ('photo', 'observations'):
                        with self.subTest(workflow=workflow, stage=stage, source=source):
                            changes = {
                                'workflow': workflow, 'stage': stage, 'identity_source': source,
                                'stylization': '旧brief中的复杂发丝处理',
                                'user_notes': '旧brief补充说明',
                                'line_plan': {'role_instructions': {'hair': '过期的发型规则'}},
                            }
                            if stage == 'final':
                                changes['approved_preview'] = str(self.photo)
                            result, prompt = self.prepare(f'{workflow}-{stage}-{source}', **changes)
                            for role, text in expected[workflow].items():
                                self.assertEqual(prompt.count(text), 1)
                                field = 'role_short_instructions' if workflow == 'fast' else 'role_instructions'
                                self.assertEqual(result['line_plan'][field][role], text)
                            self.assertNotIn('过期的发型规则', prompt)
                            self.assertEqual(result['line_plan']['hair_policy_id'], hair['policy_id'])
                            self.assertEqual(result['line_plan']['hair_precedence'], hair['precedence'])
                            self.assertEqual(result['review_spec']['style_lock']['lines'], result['line_plan'])
                            self.assertGreater(prompt.index(hair['precedence']), prompt.index(changes['user_notes']))
                            self.assertGreater(prompt.index(hair['precedence']), prompt.index(changes['stylization']))
                            if stage == 'final':
                                self.assertGreater(prompt.index(hair['precedence']), prompt.index('图3是用户认可的单个头像预览'))
                            self.assertEqual(result['argv'][result['argv'].index('--size') + 1], result['render_size'])
                            self.assertFalse(result['executed'])

    def test_preview_saves_line_source_and_hd_reuses_it_with_one_request(self):
        def gateway(argv, **kwargs):
            out = Path(argv[argv.index('--out-dir') + 1])
            out.mkdir()
            image = out / 'image-01.png'
            encoded_fixture(image, size=(1200, 1400), garments=True)
            (out / 'result.json').write_text(json.dumps({'status': 'completed',
                                                       'files': [{'original': str(image)}]}))
            return subprocess.CompletedProcess(argv, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            preview = run_avatar.run(dict(self.brief, art_palette='TS-055'), self.root / 'preview',
                                      gateway_runner=gateway)
        self.assertEqual(preview['status'], 'completed')
        saved = json.loads((self.root / 'preview/brief.json').read_text())
        request = json.loads((self.root / 'preview/request/generation-request.json').read_text())
        self.assertEqual(saved['line_reference_id'], request['line_plan']['source_reference_id'])
        self.assertEqual(saved['line_family'], request['line_plan']['family_id'])
        final_brief = {key: value for key, value in saved.items()
                       if key not in ('photo', 'identity_features', 'expression', 'pose')}
        final_brief.update(stage='final', approved_preview=preview['delivery'])
        final, _ = self.prepare('final', **final_brief)
        self.assertEqual(final['line_plan']['source_reference_id'], request['line_plan']['source_reference_id'])
        self.assertEqual(final['line_plan']['primary_hex'], request['line_plan']['primary_hex'])
        self.assertEqual(final['line_plan']['family_id'], request['line_plan']['family_id'])
        self.assertEqual(final['argv'][final['argv'].index('--size') + 1], '1024x1024')


if __name__ == '__main__':
    unittest.main()
