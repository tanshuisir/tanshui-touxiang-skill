"""Photo identity requirements stay distinct from authored observations offline."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
from eye_style import EYE_INSTRUCTIONS


class PhotoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-photo-identity-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        # A synthetic, featureless fixture verifies preparation, not likeness.
        Image.new('RGB', (240, 320), '#ba8968').save(self.photo)
        self.brief = {'photo': str(self.photo), 'identity_source': 'photo',
                      'art_palette': 'mint-apricot'}

    def prepare(self, name='request', **changes):
        brief = dict(self.brief, **changes)
        before = copy.deepcopy(brief)
        request = build_prompt.prepare(brief, self.root / 'brief.json', self.root / name)
        self.assertEqual(brief, before)
        return request, Path(request['prompt_file']).read_text(encoding='utf-8')

    def test_photo_alone_has_requirements_in_every_stage_and_workflow(self):
        for stage in ('preview', 'final'):
            for workflow in ('fast', 'review'):
                with self.subTest(stage=stage, workflow=workflow):
                    request, prompt = self.prepare(stage + '-' + workflow,
                                                   stage=stage, workflow=workflow)
                    spec = request['review_spec']
                    self.assertEqual(request['identity_source'], 'photo')
                    self.assertEqual(spec['identity_source'], 'photo')
                    self.assertEqual(spec['plan_source'], 'photo_requirements')
                    self.assertEqual(len(spec['identity_plan']), 5)
                    for item in spec['identity_plan']:
                        self.assertIn('直接查看图1', item['requirement'])
                        self.assertNotIn('photo_evidence', item)
                        self.assertNotIn('observed', item)
                    self.assertIn('由生图模型直接', spec['expression_pose'])
                    self.assertIn('读取要求', prompt)
                    self.assertIn('不是已完成', prompt)
                    self.assertNotIn('人物结构观察', prompt)
                    self.assertNotIn('照片依据：', prompt)
                    self.assertNotIn('照片表情：', prompt)
                    self.assertNotIn('照片头部与肩部姿势：', prompt)
                    for requirement in ('可见脸型', '五官', '发型', '表情', '视线',
                                        '眉眼', '头', '肩线', '衣领', '配饰'):
                        self.assertIn(requirement, prompt)
                    self.assertRegex(prompt, r'1[–-]2\s*项')
                    for boundary in ('年龄', '不对称', '遮挡', '不猜补'):
                        self.assertIn(boundary, prompt)
                    self.assertEqual(request['review_spec']['enabled'], workflow == 'review')
                    self.assertFalse(request['executed'])
                    self.assertIn(str(build_prompt.GEN_IMG), request['argv'])
                    self.assertEqual(request['quality'], 'low' if stage == 'preview' else 'high')
                    self.assertEqual(request['argv'][request['argv'].index('--size') + 1], '1024x1024')
                    self.assertEqual(request['argv'][request['argv'].index('--output-format') + 1], 'png')
                    self.assertIn(EYE_INSTRUCTIONS, prompt)
                    self.assertEqual(request['variant_plans'][0]['gradient'], request['color_plan']['gradient'])
                    self.assertEqual(request['variant_plans'][0]['background_plan'], request['background_plan'])
                    self.assertIn('中间底稿禁止渐变', prompt)
                    self.assertIn('背景满幅单一白色', prompt)
                    self.assertIn('程序会在最终头发或衣服中填入连续渐变', prompt)

    def test_explicit_expression_pose_and_clothing_remain_user_requirements(self):
        for workflow in ('fast', 'review'):
            request, prompt = self.prepare(
                workflow, workflow=workflow, expression='闭口笑，视线朝左',
                pose='向右轻微侧身', clothing='保留眼镜和圆领')
            self.assertIn('执行用户明确表情与视线要求：闭口笑，视线朝左', prompt)
            self.assertIn('执行用户明确头肩姿态要求：向右轻微侧身', prompt)
            self.assertIn('保留眼镜和圆领', prompt)
            self.assertEqual(request['review_spec']['plan_source'], 'photo_requirements')
            self.assertNotIn('photo_evidence', json.dumps(request['review_spec']))

    def test_optional_descriptions_are_requirements_to_check_against_photo(self):
        features = ['较宽圆下颌', '侧分短发', '细长眼']
        request, prompt = self.prepare(identity_features=features)
        plan = request['review_spec']['identity_plan']
        self.assertEqual(len(plan), 5 + len(features))
        for feature, item in zip(features, plan[5:]):
            self.assertEqual(item['requirement'], '按图1可见依据核对并保留补充描述：' + feature)
            self.assertIn(feature, prompt)
            self.assertNotIn('photo_evidence', item)

    def test_authored_requirements_preserve_treatments_and_boundaries(self):
        plan = build_prompt.photo_identity_plan_for(self.brief)
        plan[0].update(render_as='按图1可见脸型概括成清楚轮廓',
                       emphasis='emphasize', do_not_change='遮挡处保持遮挡')
        for workflow in ('fast', 'review'):
            request, prompt = self.prepare(workflow, workflow=workflow, identity_plan=plan)
            self.assertEqual(request['review_spec']['identity_plan'], plan)
            self.assertEqual(request['review_spec']['plan_source'], 'photo_requirements')
            self.assertIn(plan[0]['requirement'], prompt)
            self.assertIn(plan[0]['render_as'], prompt)
            self.assertIn(plan[0]['do_not_change'], prompt)
            self.assertIn('适度加强', prompt)
            self.assertNotIn('照片依据：', prompt)

    def test_requirement_plan_rejects_mislabelled_or_incomplete_evidence(self):
        original = build_prompt.photo_identity_plan_for(self.brief)
        cases = []
        plan = copy.deepcopy(original)
        plan[0]['photo_evidence'] = plan[0]['requirement']
        cases.append(plan)
        plan = copy.deepcopy(original)
        plan[0].pop('requirement')
        cases.append(plan)
        plan = copy.deepcopy(original)
        plan[1]['feature_index'] = 1
        cases.append(plan)
        plan = copy.deepcopy(original)
        for item in plan[:3]:
            item['emphasis'] = 'emphasize'
        cases.append(plan)
        cases.append(original[:2])
        for number, plan in enumerate(cases):
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.prepare('invalid-' + str(number), identity_plan=plan)
            self.assertFalse((self.root / ('invalid-' + str(number))).exists())

    def test_legacy_authored_observations_and_explicit_plan_keep_their_contract(self):
        brief = {'photo': str(self.photo), 'identity_features':
                 ['圆下颌', '短发剪影', '细长眼'], 'expression': '闭口微笑', 'pose': '近正面'}
        for source in (None, 'observations'):
            for explicit in (False, True):
                prepared = dict(brief)
                if source:
                    prepared['identity_source'] = source
                if explicit:
                    prepared['identity_plan'] = build_prompt.identity_plan_for(brief, brief['identity_features'])
                request = build_prompt.prepare(prepared, self.root / 'brief.json',
                                               self.root / f'legacy-{source}-{explicit}')
                spec = request['review_spec']
                self.assertEqual(request['identity_source'], 'observations')
                self.assertEqual(spec['plan_source'], 'explicit' if explicit else 'legacy_identity_features')
                self.assertEqual([item['photo_evidence'] for item in spec['identity_plan']],
                                 brief['identity_features'])
                self.assertTrue(all('requirement' not in item for item in spec['identity_plan']))
                if explicit:
                    self.assertEqual(spec['identity_plan'], prepared['identity_plan'])

    def test_invalid_source_or_partial_observations_do_not_silently_switch_routes(self):
        with self.assertRaisesRegex(ValueError, 'identity_source'):
            self.prepare(identity_source='guessed')
        with self.assertRaisesRegex(ValueError, 'identity_features'):
            build_prompt.prepare({'photo': str(self.photo)}, self.root / 'brief.json',
                                 self.root / 'missing-observations')
        with self.assertRaisesRegex(ValueError, 'expression'):
            self.prepare(expression='')


if __name__ == '__main__':
    unittest.main()
