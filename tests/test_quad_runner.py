"""A single model master produces four locally colored copies; offline only."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import run_avatar


def encoded_fixture(path):
    image = Image.new('RGB', (180, 220), '#FFFFFF')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((25, 12, 154, 190), radius=40, fill='#FFFF00', outline='#000000', width=4)
    draw.ellipse((48, 40, 130, 155), fill='#FF0000', outline='#000000', width=4)
    draw.rectangle((112, 75, 123, 130), fill='#00FF00')
    draw.polygon(((15, 220), (40, 165), (135, 165), (170, 220)), fill='#00FFFF', outline='#000000', width=4)
    draw.polygon(((75,165),(110,165),(125,220),(62,220)),fill='#FF8000',outline='#000000',width=2)
    draw.ellipse((61, 90, 69, 100), fill='#000000')
    draw.ellipse((101, 90, 109, 100), fill='#000000')
    draw.ellipse((54, 109, 68, 122), fill='#FF00FF')
    draw.ellipse((105, 109, 119, 122), fill='#FF00FF')
    draw.rectangle((82, 133, 98, 139), fill='#0000FF', outline='#000000', width=1)
    image.resize((1200, 1400), Image.Resampling.NEAREST).save(path)


class QuadRunnerTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-quad-run-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root/'photo.png'
        Image.new('RGB', (120, 150), '#BA8968').save(self.photo)

    def gateway(self, malformed=False):
        def fake(argv, **kwargs):
            render = Path(argv[argv.index('--out-dir')+1])
            render.mkdir(parents=True)
            output = render/'image-01.png'
            if malformed:
                Image.new('RGB', (1200, 1400), '#A1E5D2').save(output)
            else:
                encoded_fixture(output)
            (render/'result.json').write_text(json.dumps({
                'status': 'completed', 'api_seconds': 0.1, 'model': 'offline-model',
                'files': [{'original': str(output), 'format': 'png'}]}))
            return subprocess.CompletedProcess(argv, 0)
        return mock.Mock(side_effect=fake)

    def test_cli_default_submits_one_master_and_delivers_four_square_tiles(self):
        gateway = self.gateway()
        output = self.root/'quad'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            code = run_avatar.main(['--photo', str(self.photo), '--out-dir', str(output)])
        self.assertEqual(code, 0)
        gateway.assert_called_once()
        result = json.loads((output/'result.json').read_text())
        brief = json.loads((output/'brief.json').read_text())
        request = json.loads((output/'request/generation-request.json').read_text())
        self.assertEqual(result['variants'], 4)
        self.assertEqual(result['delivery_size'], [2048, 2048])
        self.assertEqual(len(result['variant_files']), 4)
        self.assertEqual(len(brief['variant_plans']), 4)
        references = [p['source_hd_id'] for p in brief['variant_plans']]
        self.assertEqual(len(set(references)), 4)
        self.assertEqual([p['source_hd_id'] for p in result['colorway_sources']], references)
        self.assertEqual(brief['palette_selection']['source_hd_ids'], references)
        self.assertTrue(result['original_preserved'])
        self.assertGreaterEqual(result['timings']['local_recolor_seconds'], 0)
        self.assertEqual(result['review_assets']['output'], result['delivery'])
        self.assertEqual(request['master_encoding'], 'semantic-props-v3')
        argv = gateway.call_args[0][0]
        self.assertEqual(argv.count('--image'), 2)
        self.assertEqual(argv[argv.index('--size') + 1], '1024x1024')
        self.assertFalse(result['render_size_honored'])
        self.assertEqual(result['delivery_details']['original_size'], [1200, 1400])
        for path in result['variant_files']:
            with Image.open(path) as image:
                self.assertEqual(image.size, (1024, 1024))
        self.assertEqual(len({Path(p).read_bytes() for p in result['variant_files']}), 4)
        prompt = Path(request['prompt_file']).read_text()
        self.assertIn('中间编码底稿', prompt)
        self.assertIn('#FF0000', prompt)

    def test_invalid_master_keeps_upstream_file_and_never_retries(self):
        gateway = self.gateway(malformed=True)
        output = self.root/'bad'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            code = run_avatar.main(['--photo', str(self.photo), '--out-dir', str(output)])
        self.assertEqual(code, 1)
        gateway.assert_called_once()
        result = json.loads((output/'result.json').read_text())
        self.assertEqual(result['upstream_status'], 'completed')
        self.assertEqual(result['error_code'], 'delivery_failed')
        self.assertNotIn('delivery', result)
        self.assertTrue(Path(result['original']).is_file())

    def test_selected_plan_final_preserves_colors_with_one_new_single_request(self):
        gateway = self.gateway()
        preview = self.root/'preview'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_avatar.main(['--photo', str(self.photo), '--out-dir', str(preview)]), 0)
        saved = json.loads((preview/'brief.json').read_text())
        selected = saved['variant_plans'][1]
        gateway.reset_mock()
        final = self.root/'final'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_avatar.main([
                '--brief', str(preview/'brief.json'), '--select-variant', '2',
                '--stage', 'final', '--approved-preview', str(preview/'variants/variant-02.png'),
                '--out-dir', str(final)]), 0)
        gateway.assert_called_once()
        request = json.loads((final/'request/generation-request.json').read_text())
        self.assertEqual(request['variants'], 1)
        self.assertEqual(request['quality'], 'high')
        self.assertEqual(request['color_plan']['roles'], selected['roles'])
        self.assertEqual(request['color_plan']['gradient'], selected['gradient'])
        self.assertEqual(request['line_plan'], selected['line_plan'])
        self.assertEqual(gateway.call_args[0][0].count('--image'), 3)
        self.assertEqual(request['master_encoding'], 'semantic-props-v3')
        self.assertEqual(len(request['variant_plans']), 1)
        self.assertEqual(request['variant_plans'][0]['roles'], selected['roles'])
        self.assertEqual(request['variant_plans'][0]['source_colorway'], selected['source_colorway'])
        final_brief = json.loads((final/'brief.json').read_text())
        self.assertEqual(final_brief['source_colorway_id'], selected['id'])
        self.assertEqual(request['color_plan']['gradient_options'], selected['gradient_options'])
        self.assertEqual(len(json.loads((final/'result.json').read_text())['colorway_sources']), 1)
        self.assertTrue((final/'avatar.png').is_file())

    def test_cli_explicit_source_order_is_frozen_with_one_master_request(self):
        gateway = self.gateway()
        output = self.root/'chosen-sources'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            code = run_avatar.main(['--photo', str(self.photo),
                '--colorway-references', '6', '15', '49', '54', '--out-dir', str(output)])
        self.assertEqual(code, 0)
        gateway.assert_called_once()
        brief = json.loads((output/'brief.json').read_text())
        self.assertEqual([p['source_hd_id'] for p in brief['variant_plans']], [6, 15, 49, 54])
        self.assertNotIn('colorway_reference_ids', brief)

    def test_natural_four_colors_stops_before_model_instead_of_changing_hair(self):
        gateway=self.gateway()
        output=self.root/'natural'
        with mock.patch.object(run_avatar.subprocess,'run',gateway), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                run_avatar.main(['--photo',str(self.photo),'--color-mode','natural','--out-dir',str(output)])
        self.assertEqual(error.exception.code,2)
        gateway.assert_not_called()
        self.assertFalse(output.exists())

    def test_single_source_choice_survives_final_and_can_be_explicitly_replaced(self):
        gateway = self.gateway()
        preview, final, changed = (self.root/name for name in ('single', 'single-final', 'single-changed'))
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_avatar.main(['--photo', str(self.photo), '--variants', '1',
                '--colorway-reference', '55', '--out-dir', str(preview)]), 0)
            saved = json.loads((preview/'brief.json').read_text())
            from source_colorways import colorway
            self.assertEqual(saved['source_colorway_id'], colorway(55)['id'])
            self.assertNotIn('colorway_reference_id', saved)
            self.assertEqual(run_avatar.main(['--brief', str(preview/'brief.json'), '--stage', 'final',
                '--approved-preview', str(preview/'avatar.png'), '--out-dir', str(final)]), 0)
            self.assertEqual(run_avatar.main(['--brief', str(preview/'brief.json'),
                '--colorway-reference', '47', '--out-dir', str(changed)]), 0)
        self.assertEqual(gateway.call_count, 3)
        requests = [json.loads((folder/'request/generation-request.json').read_text())
                    for folder in (preview, final, changed)]
        for key in ('roles', 'gradient', 'source_colorway'):
            self.assertEqual(requests[0]['color_plan'][key], requests[1]['color_plan'][key])
        self.assertEqual(requests[2]['color_plan']['source_hd_id'], 47)
        self.assertEqual(requests[2]['color_plan']['roles']['skin_base'], colorway(47)['roles']['skin_base'])
        self.assertEqual(requests[2]['color_plan']['roles']['background'], colorway(47)['roles']['background'])
        result = json.loads((final/'result.json').read_text())
        self.assertEqual(result['colorway_sources'][0]['source_hd_id'], 55)
        self.assertEqual(requests[1]['quality'], 'high')

    def test_conflicting_single_source_selectors_stop_before_gateway(self):
        gateway = self.gateway()
        output = self.root/'conflicting'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                run_avatar.main(['--photo', str(self.photo), '--variants', '1',
                    '--colorway-reference', '55', '--line-reference', '25', '--out-dir', str(output)])
        self.assertEqual(error.exception.code, 2)
        gateway.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
