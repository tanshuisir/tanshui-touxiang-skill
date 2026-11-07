"""Offline coverage of the eye policy across generation and review routes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import review_avatar
from eye_style import EYE_STYLE_ID, EYE_INSTRUCTIONS, EYE_PRECEDENCE


class EyeStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-eye-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        self.preview = self.root / 'preview.png'
        Image.new('RGB', (200, 300), '#ba8968').save(self.photo)
        Image.new('RGB', (512, 512), '#a1e5d2').save(self.preview)
        self.brief = {
            'photo': str(self.photo), 'art_palette': 'turquoise-violet',
            'identity_features': ['较宽圆下颌', '短发剪影', '上挑眼尾，双眼间距较宽'],
            'expression': '侧目微笑', 'pose': '四分之三侧面',
        }

    def request(self, name='request', **overrides):
        result = build_prompt.prepare(dict(self.brief, **overrides),
                                      self.root/'brief.json', self.root/name)
        return result, Path(result['prompt_file']).read_text(encoding='utf-8')

    def test_all_modes_workflows_and_stages_share_policy_without_extra_inputs(self):
        for mode in build_prompt.MODES:
            for workflow in ('fast', 'review'):
                for stage in ('preview', 'final'):
                    with self.subTest(mode=mode, workflow=workflow, stage=stage):
                        result, prompt = self.request(f'{mode}-{workflow}-{stage}', mode=mode,
                                                      workflow=workflow, stage=stage)
                        self.assertEqual(result['review_spec']['style_lock']['eye_style'],
                                         {'id': EYE_STYLE_ID, 'instructions': EYE_INSTRUCTIONS})
                        self.assertTrue(prompt.endswith(EYE_INSTRUCTIONS + '\n'))
                        self.assertEqual(prompt.count(EYE_INSTRUCTIONS), 1)
                        self.assertEqual(result['argv'].count('--image'), 2)
                        self.assertFalse(result['executed'])
                        self.assertEqual(result['review_spec']['max_automatic_corrections'],
                                         0 if workflow == 'fast' else 1)

    def test_old_explicit_plan_notes_and_approved_preview_cannot_bypass_policy(self):
        plan = build_prompt.identity_plan_for(self.brief, self.brief['identity_features'])
        plan[2].update(render_as='保留眼白、独立瞳孔和高光', do_not_change='不简化眼部细节')
        for workflow in ('fast', 'review'):
            result, prompt = self.request(workflow, workflow=workflow, stage='final',
                                          identity_plan=plan, hd_reference_id=26,
                                          approved_preview=str(self.preview),
                                          user_notes='保持批准预览的眼白和高光')
            # Keep the old observation for provenance, but give the shared
            # rendering grammar final explicit precedence in the model input.
            self.assertGreater(prompt.index(EYE_PRECEDENCE), prompt.index('图3是用户认可的单个头像预览'))
            self.assertGreater(prompt.index(EYE_PRECEDENCE), prompt.index('保持批准预览的眼白和高光'))
            self.assertEqual(result['argv'].count('--image'), 3)
            self.assertEqual(result['review_spec']['identity_plan'][2], plan[2])
            self.assertIn(self.brief['expression'], prompt)

    def test_legacy_reference_also_gets_the_current_eye_grammar(self):
        result, prompt = self.request(palette_id=24)
        self.assertEqual(result['reference_set'], 'legacy')
        self.assertTrue(prompt.endswith(EYE_INSTRUCTIONS + '\n'))

    def test_detailed_review_records_an_eye_failure_as_revision(self):
        result, _ = self.request(workflow='review')
        setup = review_avatar.prepare(self.root/'request/generation-request.json', self.preview,
                                      self.root/'review')
        path = Path(setup['review'])
        report = json.loads(path.read_text())
        report['visual_review'] = {key: True for key in review_avatar.VIEW_FLAGS}
        report['visual_review']['reviewer'] = 'synthetic-state-test'
        for item in report['checks']:
            item.update(verdict='pass', observed='仅测试状态变化，不代表实际视觉通过')
        eye = next(item for item in report['checks'] if item['id'] == 'eye_style')
        self.assertEqual(eye['expected'], result['review_spec']['style_lock']['eye_style']['instructions'])
        eye.update(verdict='fail', observed='合成失败案例：眼睛仍有反光点',
                   correction='保留眼距与视线，将内部细节合并为单色实心眼形')
        path.write_text(json.dumps(report, ensure_ascii=False))
        assessed = review_avatar.assess(path)
        self.assertEqual(assessed['status'], 'needs_revision')
        self.assertEqual(assessed['failed_checks'], ['eye_style'])
        report['checks'].remove(eye)
        path.write_text(json.dumps(report, ensure_ascii=False))
        with self.assertRaises(ValueError):
            review_avatar.assess(path)


if __name__ == '__main__':
    unittest.main()
