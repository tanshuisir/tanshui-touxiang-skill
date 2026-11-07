"""Offline checks for workflow gates; fixtures never claim visual likeness."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import finalize_avatar
import review_avatar


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-workflow-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        self.image = self.root / 'avatar.png'
        Image.new('RGB', (200, 300), '#ba8968').save(self.photo)
        Image.new('RGB', (1024, 1024), '#a1e5d2').save(self.image)
        self.brief = {
            'photo': str(self.photo),
            'identity_features': ['较宽的圆下颌', '短发轮廓', '细长眼与闭口微笑'],
            'expression': '闭口微笑，目视镜头', 'pose': '近正面略歪头',
        }

    def request(self, brief=None, name='request'):
        result = build_prompt.prepare(brief or self.brief, self.root/'brief.json', self.root/name)
        return self.root/name/'generation-request.json', result

    def review(self, image=None):
        request, _ = self.request(dict(self.brief, workflow='review', stage='final'))
        result = review_avatar.prepare(request, image or self.image, self.root/'review')
        path = Path(result['review'])
        return path, json.loads(path.read_text())

    def save(self, path, report):
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')

    def complete_fixture(self, report):
        # Synthetic evidence only tests data-state transitions, not likeness.
        report['visual_review'] = {k: True for k in review_avatar.VIEW_FLAGS}
        report['visual_review']['reviewer'] = 'unit-test-fixture'
        for item in report['checks']:
            item.update(verdict='pass', observed='仅为状态机测试的合成观察，不是实际人物评审')

    def test_preview_defaults_and_existing_model_route(self):
        _, result = self.request()
        self.assertEqual((result['reference_set'], result['reference_id']), ('finished', 25))
        self.assertEqual((result['mode'], result['color_mode']), ('flat', 'expressive'))
        self.assertEqual((result['delivery_size'], result['render_size']), ('1024x1024', '1024x1024'))
        self.assertEqual(result['size_policy'], 'square')
        self.assertEqual(result['argv'][result['argv'].index('--size') + 1], '1024x1024')
        self.assertEqual(result['stage'], 'preview')
        self.assertFalse(result['executed'])
        self.assertIn(str(build_prompt.GEN_IMG), result['argv'])
        self.assertNotIn('--model', result['argv'])
        self.assertEqual(result['workflow'], 'fast')
        self.assertFalse(result['review_spec']['enabled'])
        self.assertEqual(result['review_spec']['max_automatic_corrections'], 0)
        self.assertEqual(result['argv'][result['argv'].index('--quality')+1], 'low')

    def test_final_defaults_use_photo_style_and_approved_preview(self):
        _, result = self.request(dict(self.brief, stage='final', approved_preview=str(self.image)))
        self.assertEqual((result['delivery_size'], result['render_size']), ('1024x1024', '1024x1024'))
        self.assertEqual(result['argv'][result['argv'].index('--size') + 1], '1024x1024')
        self.assertEqual(result['quality'], 'high')
        images = [result['argv'][i+1] for i, v in enumerate(result['argv']) if v == '--image']
        self.assertEqual(images, [str(self.photo.resolve()), result['style_reference'], str(self.image.resolve())])
        self.assertEqual(result['reference_id'], 25)

    def test_invalid_stage_or_preview_reference_is_rejected_before_output(self):
        for brief in (dict(self.brief, stage='automatic-upgrade'),
                      dict(self.brief, approved_preview=str(self.image))):
            with self.assertRaises(ValueError):
                self.request(brief)
        self.assertFalse((self.root/'request').exists())

    def test_fast_prompt_is_short_and_preserves_observations_once(self):
        _, result = self.request()
        prompt = Path(result['prompt_file']).read_text()
        # Shared eyes, hair and framing rules remain on the short prompt route.
        self.assertLess(len(prompt), 1750)
        for feature in self.brief['identity_features']:
            self.assertEqual(prompt.count(feature), 1)
        self.assertIn(self.brief['expression'], prompt)
        self.assertIn(self.brief['pose'], prompt)
        self.assertRegex(prompt, r'不迁移其脸|勿复制其人物|不复制图2人物')
        self.assertIn('硬边暗面', prompt)
        self.assertNotIn('照片依据：', prompt)

    def test_review_mode_remains_explicit_and_uses_detailed_template(self):
        _, result = self.request(dict(self.brief, workflow='review'))
        self.assertTrue(result['review_spec']['enabled'])
        self.assertEqual(result['review_spec']['max_automatic_corrections'], 1)
        prompt = Path(result['prompt_file']).read_text()
        self.assertIn('照片依据：', prompt)
        self.assertGreater(len(prompt), 1000)

    def test_model_and_quality_are_forwarded_without_selecting_alternatives(self):
        for i, model in enumerate(('gpt-image-2', 'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst')):
            _, result = self.request(dict(self.brief, model=model, quality='high'), name=f'model-{i}')
            self.assertEqual(result['argv'][result['argv'].index('--model')+1], model)
            self.assertEqual(result['argv'][result['argv'].index('--quality')+1], 'high')
        # This is only argv preparation: global gen-img owns the exact exclusion
        # and rejects gpt-image-2 before any image API call.

    def test_four_variant_review_binds_every_complete_source_palette(self):
        _, request = self.request(dict(self.brief, workflow='review', variants=4))
        checks = {item['id']: item for item in review_avatar.checks_for(request)
                  if item['id'].startswith('source_colorway.')}
        self.assertEqual(set(checks), {f'source_colorway.{index}' for index in range(1, 5)})
        self.assertEqual(len(request['variant_plans']), 4)
        for index, plan in enumerate(request['variant_plans'], 1):
            expected = checks[f'source_colorway.{index}']['expected']
            self.assertIn(f'HD-{plan["source_hd_id"]:03d}', expected)
            self.assertIn(json.dumps(plan['roles'], ensure_ascii=False), expected)
            self.assertIn(json.dumps(plan['gradient'], ensure_ascii=False), expected)
        self.assertFalse(request['executed'])

    def test_natural_without_observed_hair_stops_before_output(self):
        with self.assertRaisesRegex(ValueError,'natural'):
            self.request(dict(self.brief,color_mode='natural'))
        self.assertFalse((self.root/'request').exists())

    def test_invalid_workflow_is_rejected_before_output(self):
        with self.assertRaises(ValueError):
            self.request(dict(self.brief, workflow='retry-until-perfect'))
        self.assertFalse((self.root/'request').exists())

    def test_natural_is_rejected_before_writing_a_request(self):
        with self.assertRaises(ValueError):
            self.request(dict(self.brief,color_mode='natural'))
        self.assertFalse((self.root/'request').exists())

    def test_fast_explicit_plan_does_not_select_new_exaggeration_targets(self):
        plan = build_prompt.identity_plan_for(self.brief, self.brief['identity_features'])
        _, result = self.request(dict(self.brief, identity_plan=plan))
        prompt = Path(result['prompt_file']).read_text()
        self.assertIn('只加强逐项标注的特征，其余保留', prompt)
        self.assertNotIn('选择已有的1–2项特征适度加强', prompt)
        self.assertNotIn('适度加强：', prompt)
        self.assertEqual(prompt.count('保留：'), len(plan))

    def test_legacy_reference_stays_independent(self):
        brief = dict(self.brief, palette_id=24)
        _, result = self.request(brief)
        self.assertEqual((result['reference_set'], result['reference_id']), ('legacy', 24))
        self.assertTrue(result['style_reference'].endswith('assets/portraits/024.png'))

    def test_existing_modes_and_custom_size_still_work(self):
        for i, (mode, reference, color) in enumerate([
            ('gradient', 8, 'expressive'), ('texture', 17, 'expressive'),
            ('bold', 11, 'expressive'), ('cartoon', 42, 'expressive'),
            ('duotone', 33, 'expressive'),
        ]):
            brief = dict(self.brief, hd_reference_id=reference, mode=mode, color_mode=color,
                         size_policy='explicit', size='800x800', render_size='1024x1024',
                         color_roles={'hair': '#BA8968'} if color == 'expressive' else None)
            _, result = self.request(brief, name=f'request-{i}')
            self.assertEqual(result['mode'], mode)
            self.assertEqual(result['delivery_size'], '800x800')
        _, result = self.request(dict(self.brief, palette_id=40, mode='glitch', color_mode='expressive'), name='glitch')
        self.assertEqual(result['mode'], 'glitch')

    def test_explicit_plan_covers_features_and_limits_exaggeration(self):
        plan = build_prompt.identity_plan_for(self.brief, self.brief['identity_features'])
        plan[0]['emphasis'] = 'emphasize'
        _, result = self.request(dict(self.brief, identity_plan=plan))
        self.assertEqual(result['review_spec']['plan_source'], 'explicit')
        prompt = Path(result['prompt_file']).read_text()
        self.assertIn(plan[0]['render_as'], prompt)
        with self.assertRaises(ValueError):
            build_prompt.identity_plan_for(dict(self.brief, identity_plan=plan[:-1]), self.brief['identity_features'])
        for item in plan:
            item['emphasis'] = 'emphasize'
        with self.assertRaises(ValueError):
            build_prompt.identity_plan_for(dict(self.brief, identity_plan=plan), self.brief['identity_features'])

    def test_preparing_never_passes_visual_review(self):
        path, _ = self.review()
        self.assertEqual(review_avatar.assess(path)['status'], 'awaiting_visual_review')
        self.assertTrue((path.parent/'comparison.png').is_file())
        self.assertTrue((path.parent/'thumbnail-128.png').is_file())

    def test_photo_requirements_survive_review_without_becoming_observations(self):
        request_path, request = self.request({
            'photo': str(self.photo), 'identity_source': 'photo', 'workflow': 'review',
        })
        prepared = review_avatar.prepare(request_path, self.image, self.root / 'photo-review')
        path = Path(prepared['review'])
        report = json.loads(path.read_text())
        identity_checks = [item for item in report['checks'] if item['id'].startswith('identity.')]
        self.assertEqual(len(identity_checks), len(request['review_spec']['identity_plan']))
        for check, plan in zip(identity_checks, request['review_spec']['identity_plan']):
            self.assertEqual(check['requirement'], plan['requirement'])
            self.assertNotIn('photo_evidence', check)
            self.assertEqual(check['observed'], '')
        self.assertEqual(review_avatar.assess(path)['status'], 'awaiting_visual_review')
        self.complete_fixture(report)
        self.save(path, report)
        self.assertEqual(review_avatar.assess(path)['status'], 'passed')

    def test_pass_requires_observations(self):
        path, report = self.review()
        self.complete_fixture(report)
        report['checks'][0]['observed'] = None
        self.save(path, report)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)

    def test_not_viewed_does_not_pass(self):
        path, report = self.review()
        self.complete_fixture(report)
        report['visual_review']['image_viewed'] = False
        self.save(path, report)
        self.assertEqual(review_avatar.assess(path)['status'], 'awaiting_visual_review')

    def test_complete_fixture_can_pass_without_a_similarity_score(self):
        path, report = self.review()
        self.complete_fixture(report)
        self.save(path, report)
        result = review_avatar.assess(path)
        self.assertEqual(result['status'], 'passed')
        self.assertNotIn('similarity', result)

    def test_feature_failure_requires_revision_and_correction(self):
        path, report = self.review()
        self.complete_fixture(report)
        report['checks'][0].update(verdict='fail', observed='圆下颌被改成尖下巴', correction='仅恢复圆下颌，保持其余画法')
        self.save(path, report)
        self.assertEqual(review_avatar.assess(path)['status'], 'needs_revision')
        report['checks'][0]['correction'] = ''
        self.save(path, report)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)

    def test_uncertain_never_counts_as_pass(self):
        path, report = self.review()
        self.complete_fixture(report)
        report['checks'][0].update(verdict='uncertain', observed='照片遮挡导致无法判断')
        self.save(path, report)
        self.assertEqual(review_avatar.assess(path)['status'], 'needs_manual_review')

    def test_changed_image_invalidates_old_review(self):
        path, report = self.review()
        self.complete_fixture(report)
        self.save(path, report)
        Image.new('RGB', (1000, 1000), '#000000').save(self.image)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)

    def test_changed_photo_invalidates_prepared_request(self):
        path, report = self.review()
        Image.new('RGB', (200, 300), '#ffffff').save(self.photo)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)

    def test_missing_or_changed_gate_is_rejected(self):
        path, report = self.review()
        _, request = review_avatar.load_request(report['files']['request']['path'])
        self.assertEqual(report['checks'][0]['do_not_change'],
                         request['review_spec']['identity_plan'][0]['do_not_change'])
        changed = copy.deepcopy(report)
        changed['checks'][0].pop('do_not_change')
        self.save(path, changed)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)
        changed = copy.deepcopy(report)
        changed['checks'][0]['expected'] = '忽略脸型'
        self.save(path, changed)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)
        report['checks'].pop()
        self.save(path, report)
        with self.assertRaises(ValueError):
            review_avatar.assess(path)

    def test_unexpected_dimensions_fail_square_review(self):
        Image.new('RGB', (900, 900), '#a1e5d2').save(self.image)
        path, report = self.review()
        self.complete_fixture(report)
        self.save(path, report)
        self.assertEqual(review_avatar.assess(path)['status'], 'needs_revision')

    def test_existing_finalization_preserves_original_and_delivers_1000(self):
        large = self.root/'large.png'
        Image.new('RGB', (1024, 1024), '#a1e5d2').save(large)
        before = hashlib.sha256(large.read_bytes()).hexdigest()
        result = finalize_avatar.finalize(large, self.root/'final.png', size=1000)
        self.assertEqual(result['delivery_size'], [1000, 1000])
        self.assertEqual(hashlib.sha256(large.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
