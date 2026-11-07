"""Offline opacity and background integration checks; never calls an image API."""
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
from avatar_test_fixture import encoded_fixture

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import finalize_avatar
import review_avatar
import run_avatar


class OpaqueBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-opaque-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.photo = self.root / 'photo.png'
        Image.new('RGB', (240, 320), '#ba8968').save(self.photo)
        self.brief = {
            'photo': str(self.photo),
            'identity_features': ['圆下颌', '短发剪影', '细长眼与闭口微笑'],
            'expression': '闭口微笑', 'pose': '近正面',
        }
        self.background = {'color': '#FFDC70'}

    def save_cutout(self, name='cutout.png', size=32):
        source = self.root / name
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        # The synthetic solid square is only a compositing fixture, not an avatar.
        image.paste((80, 20, 130, 255), (size//4, size//4, 3*size//4, 3*size//4))
        image.save(source)
        return source

    def test_transparent_cutout_gets_opaque_background_and_preserves_original(self):
        source = self.save_cutout()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.root / 'opaque.png'
        result = finalize_avatar.finalize(source, output, 32, self.background)
        with Image.open(output) as image:
            self.assertEqual((image.mode, image.format, image.size), ('RGB', 'PNG', (32, 32)))
            self.assertEqual(image.getpixel((0, 0)), (255, 220, 112))
            self.assertEqual(image.getpixel((16, 16)), (80, 20, 130))
            self.assertEqual(image.convert('RGBA').getchannel('A').getextrema(), (255, 255))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertTrue(result['opaque'])
        self.assertTrue(result['background_composited'])
        self.assertIn('composite_opaque_background', [op['operation'] for op in result['operations']])

    def test_partial_alpha_edges_are_blended_instead_of_dropped(self):
        source = self.root / 'edge.png'
        image = Image.new('RGBA', (8, 8), (200, 100, 50, 0))
        image.putpixel((4, 4), (200, 100, 50, 128))
        image.save(source)
        output = self.root / 'edge-opaque.png'
        background = {'color': '#14283C'}
        finalize_avatar.finalize(source, output, 8, background)
        with Image.open(output) as delivered:
            self.assertEqual(delivered.getpixel((4, 4)), (110, 70, 55))
            self.assertEqual(delivered.getpixel((0, 0)), (20, 40, 60))

    def test_palette_png_transparency_uses_background(self):
        source = self.root / 'palette.png'
        image = Image.new('P', (8, 8), 0)
        image.putpalette([0, 0, 0, 80, 20, 130] + [0] * (768-6))
        image.putpixel((4, 4), 1)
        image.save(source, transparency=0)
        output = self.root / 'palette-opaque.png'
        finalize_avatar.finalize(source, output, 8, self.background)
        with Image.open(output) as delivered:
            self.assertEqual(delivered.mode, 'RGB')
            self.assertEqual(delivered.getpixel((0, 0)), (255, 220, 112))
            self.assertEqual(delivered.getpixel((4, 4)), (80, 20, 130))

    def test_fully_transparent_input_cannot_be_delivered_as_blank_background(self):
        source = self.root / 'empty.png'
        Image.new('RGBA', (8, 8), (80, 20, 130, 0)).save(source)
        output = self.root / 'empty-result.png'
        with self.assertRaises(ValueError):
            finalize_avatar.finalize(source, output, 8, self.background)
        self.assertFalse(output.exists())

    def test_transparent_input_without_background_plan_fails(self):
        source = self.save_cutout(size=8)
        output = self.root / 'unplanned.png'
        with self.assertRaises(ValueError):
            finalize_avatar.finalize(source, output, 8)
        self.assertFalse(output.exists())

    def test_opaque_rgb_and_rgba_preserve_visible_pixels_without_compositing(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode):
                source = self.root / f'opaque-{mode}.png'
                original = Image.new(mode, (8, 8), '#A122B3')
                original.putpixel((3, 4), (20, 120, 90) if mode == 'RGB' else (20, 120, 90, 255))
                original.save(source)
                output = self.root / f'delivered-{mode}.png'
                result = finalize_avatar.finalize(source, output, 8, self.background)
                with Image.open(output) as image:
                    self.assertEqual(image.mode, 'RGB')
                    self.assertEqual(image.tobytes(), original.convert('RGB').tobytes())
                self.assertFalse(result['background_composited'])

    def test_legacy_background_gradient_always_renders_one_solid_color(self):
        directions = ('从上到下', '从下到上', '从左到右', '从右到左',
                      '从左上到右下', '从右下到左上', '从右上到左下', '从左下到右上')
        for direction in directions:
            with self.subTest(direction=direction):
                plan = {'color': '#FFDC70', 'gradient': {'region': 'background',
                        'from': '#FFDC70', 'to': '#90D6F0', 'direction': direction}}
                image = finalize_avatar.background_image((17, 17), plan)
                self.assertEqual(set(image.getdata()), {(255, 220, 112, 255)})
                self.assertEqual(image.getchannel('A').getextrema(), (255, 255))

    def test_transparent_corners_and_all_exposed_pixels_are_solid_despite_old_gradient(self):
        source = self.save_cutout(size=32)
        output = self.root/'gradient-opaque.png'
        plan = {'color': '#FFDC70', 'gradient': {'region': 'background',
                'from': '#FFDC70', 'to': '#90D6F0', 'direction': '从上到下'}}
        result = finalize_avatar.finalize(source, output, 32, plan)
        self.assertTrue(result['background_composited'])
        with Image.open(output) as image:
            self.assertEqual(image.mode, 'RGB')
            for point in ((0, 0), (0, 31), (31, 0), (31, 31)):
                self.assertEqual(image.getpixel(point), (255, 220, 112))
            with Image.open(source) as original:
                alpha = original.getchannel('A')
                exposed = {image.getpixel((x, y)) for x in range(32) for y in range(32)
                           if alpha.getpixel((x, y)) == 0}
                self.assertEqual(exposed, {(255, 220, 112)})
            self.assertEqual(image.getpixel((16, 16)), (80, 20, 130))

    def test_background_gradient_does_not_replace_subject_gradient(self):
        plan = {'color': '#FFDC70', 'gradient': {'region': 'hair',
                'from': '#A122B3', 'to': '#601090', 'direction': '从上到下'}}
        image = finalize_avatar.background_image((17, 17), plan)
        self.assertEqual(image.getpixel((0, 0)), (255, 220, 112, 255))
        self.assertEqual(image.getpixel((16, 16)), (255, 220, 112, 255))

    def test_opaque_gateway_option_is_present_in_all_stage_and_workflow_combinations(self):
        for stage in ('preview', 'final'):
            for workflow in ('fast', 'review'):
                with self.subTest(stage=stage, workflow=workflow):
                    brief = dict(self.brief, stage=stage, workflow=workflow)
                    request = build_prompt.prepare(brief, self.root/'brief.json', self.root/f'{stage}-{workflow}')
                    argv = request['argv']
                    self.assertEqual(argv[argv.index('--background') + 1], 'opaque')
                    self.assertEqual(request['background_plan']['color'], request['color_plan']['roles']['background'])

    def run_with_cutout_gateway(self, brief=None):
        originals = {}
        def fake_gateway(argv, **kwargs):
            directory = Path(argv[argv.index('--out-dir')+1])
            directory.mkdir()
            destination = directory/'image-01.png'
            encoded_fixture(destination, transparent_background=True)
            originals['bytes'] = destination.read_bytes()
            payload = {'status': 'completed', 'files': [{'original': str(destination), 'format': 'png'}]}
            (directory/'result.json').write_text(json.dumps(payload), encoding='utf-8')
            return subprocess.CompletedProcess(argv, 0)
        gateway = mock.Mock(side_effect=fake_gateway)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = run_avatar.run(brief or self.brief, self.root/'run', gateway_runner=gateway)
        return result, json.loads(stream.getvalue()), gateway, originals

    def test_runner_composites_transparency_locally_without_second_request(self):
        result, _, gateway, originals = self.run_with_cutout_gateway()
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['delivery_details']['background_composited'])
        self.assertEqual(Path(result['original']).read_bytes(), originals['bytes'])
        request = json.loads((self.root/'run'/'request'/'generation-request.json').read_text())
        with Image.open(result['delivery']) as image:
            self.assertEqual(image.mode, 'RGB')
            expected = tuple(bytes.fromhex(request['background_plan']['color'][1:]))
            self.assertEqual(image.getpixel((0, 0)), expected)
        self.assertTrue(result['awaiting_hd_confirmation'])

    def test_natural_stops_before_gateway_instead_of_unknown_hair_fallback(self):
        result,summary,gateway,_=self.run_with_cutout_gateway(dict(self.brief,color_mode='natural'))
        gateway.assert_not_called()
        self.assertEqual(result['error_code'],'preparation_failed')
        self.assertNotIn('delivery',summary)

    def test_natural_observed_hair_cannot_break_complete_source_scheme(self):
        result,summary,gateway,_=self.run_with_cutout_gateway(dict(self.brief,color_mode='natural',color_roles={'hair':'#302820'}))
        gateway.assert_not_called()
        self.assertEqual(result['error_code'],'preparation_failed')
        self.assertNotIn('delivery',summary)

    def test_independent_background_planner_cannot_replace_complete_source_background(self):
        brief=dict(self.brief,color_roles={'background':'#A19872','skin_base':'#A61433'})
        with mock.patch('background_plan._score',return_value=0.25) as score:
            result,summary,gateway,_=self.run_with_cutout_gateway(brief)
        gateway.assert_called_once()
        score.assert_not_called()
        self.assertEqual(result['status'],'completed')
        request=json.loads((self.root/'run/request/generation-request.json').read_text())
        plan=request['color_plan']
        self.assertEqual(plan['source_selection']['skin']['source_hd_id'],plan['source_selection']['background']['source_hd_id'])
        self.assertEqual(request['background_plan']['color'],plan['roles']['background'])

    def test_visual_observations_cannot_override_detected_transparency(self):
        prepared = self.root/'request'
        build_prompt.prepare(dict(self.brief, workflow='review'), self.root/'brief.json', prepared)
        image = self.save_cutout(size=512)
        result = review_avatar.prepare(prepared/'generation-request.json', image, self.root/'review')
        report_path = Path(result['review'])
        report = json.loads(report_path.read_text())
        report['visual_review'] = dict.fromkeys(review_avatar.VIEW_FLAGS, True)
        report['visual_review']['reviewer'] = 'synthetic-state-transition-fixture'
        for check in report['checks']:
            check.update(verdict='pass', observed='合成测试依据，仅验证工作流门槛')
        report_path.write_text(json.dumps(report), encoding='utf-8')
        assessed = review_avatar.assess(report_path)
        self.assertEqual(assessed['status'], 'needs_revision')
        opacity = next(check for check in assessed['automatic_checks'] if check['id'] == 'opaque_pixels')
        self.assertFalse(opacity['passed'])


if __name__ == '__main__':
    unittest.main()
