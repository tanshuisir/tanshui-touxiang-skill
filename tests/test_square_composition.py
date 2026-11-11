"""Square delivery and migration contracts, without image API calls."""
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
import finalize_avatar
import run_avatar
from composition import FRAMING_ID


class SquareCompositionTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-square-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root / 'photo.png'
        Image.new('RGB', (240, 320), '#ba8968').save(self.photo)
        self.brief = {'photo': str(self.photo), 'identity_source': 'photo'}

    def prepare(self, name, **changes):
        return build_prompt.prepare(dict(self.brief, **changes),
                                    self.root / 'brief.json', self.root / name)

    def test_all_stages_and_workflows_request_one_square_without_extra_inputs(self):
        for stage in ('preview', 'final'):
            for workflow in ('fast', 'review'):
                request = self.prepare(stage + workflow, stage=stage, workflow=workflow)
                self.assertEqual(request['size_policy'], 'square')
                self.assertEqual((request['render_size'], request['delivery_size']),
                                 ('1024x1024', '1024x1024'))
                argv = request['argv']
                self.assertEqual(argv.count('--size'), 1)
                self.assertEqual(argv[argv.index('--size') + 1], '1024x1024')
                self.assertEqual(argv.count('--image'), 2)
                self.assertEqual(request['quality'], 'low' if stage == 'preview' else 'high')
                self.assertEqual(request['framing_plan']['id'], FRAMING_ID)
                self.assertEqual(request['framing_plan']['crown_to_chin_height_ratio'], [0.40, 0.48])
                self.assertEqual(request['review_spec']['style_lock']['framing_plan'], request['framing_plan'])

    def test_old_native_size_and_tight_framing_are_migrated(self):
        request = self.prepare('old', size_policy='native', size='800x800',
                               render_size='1536x1024', framing='OLD_TIGHT_HEAD')
        self.assertEqual(request['size_policy'], 'square')
        prompt = Path(request['prompt_file']).read_text()
        self.assertNotIn('OLD_TIGHT_HEAD', prompt)
        self.assertNotIn('1536x1024', prompt)
        self.assertIn('1:1', prompt)
        self.assertIn('胸部中段', prompt)

    def test_cli_resets_old_explicit_size_and_preserves_style_and_quality(self):
        path = self.root / 'old.json'
        path.write_text(json.dumps(dict(self.brief, size_policy='explicit', size='800x800',
            render_size='2048x2048', framing='OLD_TIGHT_HEAD', quality='high', hd_reference_id=26)))
        with mock.patch.object(run_avatar, 'run', return_value={'status': 'completed'}) as runner:
            self.assertEqual(run_avatar.main(['--brief', str(path)]), 0)
        brief, _ = runner.call_args[0]
        self.assertEqual(brief['size_policy'], 'square')
        self.assertEqual(brief['quality'], 'high')
        self.assertEqual(brief['hd_reference_id'], 26)
        self.assertNotIn('size', brief)
        self.assertNotIn('framing', brief)

    def test_fresh_explicit_square_remains_available(self):
        request = self.prepare('explicit', size_policy='explicit', size='800x800', render_size='1024x1024')
        self.assertEqual(request['delivery_size'], '800x800')
        with self.assertRaises(ValueError):
            self.prepare('rectangle', size_policy='explicit', size='800x600')

    def test_non_square_fallback_keeps_both_edges_without_stretch_or_upscale(self):
        source = self.root / 'wide.png'
        original = Image.new('RGB', (80, 40), '#123456')
        original.putpixel((0, 0), (255, 0, 0))
        original.putpixel((79, 39), (0, 255, 0))
        original.save(source)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.root / 'square.png'
        result = finalize_avatar.finalize(source, output, size=80,
            background={'color': '#A1E5D2'}, fit_square=True)
        with Image.open(output) as delivered:
            self.assertEqual(delivered.size, (80, 80))
            self.assertEqual(delivered.mode, 'RGB')
            self.assertEqual(delivered.getpixel((0, 0)), (161, 229, 210))
            self.assertEqual(delivered.getpixel((0, 40)), (255, 0, 0))
            self.assertEqual(delivered.getpixel((79, 79)), (0, 255, 0))
        self.assertEqual(result['operations'][0]['operation'], 'fit_square_background')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_too_small_or_empty_results_do_not_become_fake_hd(self):
        for mode, color, name in [('RGB', '#123456', 'small'), ('RGBA', (0, 0, 0, 0), 'empty')]:
            source = self.root / (name + '.png')
            Image.new(mode, (40, 32), color).save(source)
            with self.assertRaises(ValueError):
                finalize_avatar.finalize(source, self.root / (name + '-out.png'),
                    size=80, background={'color': '#A1E5D2'}, fit_square=True)

    def test_runner_fits_upstream_rectangle_in_one_request_and_freezes_policy(self):
        def fake(argv, **kwargs):
            directory = Path(argv[argv.index('--out-dir') + 1])
            directory.mkdir()
            original = directory / 'image-01.png'
            from avatar_test_fixture import encoded_fixture
            encoded_fixture(original, (1200, 1400), garments=True)
            (directory / 'result.json').write_text(json.dumps({
                'status': 'completed', 'files': [{'original': str(original)}]}))
            return subprocess.CompletedProcess(argv, 0)
        gateway = mock.Mock(side_effect=fake)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_avatar.run(self.brief, self.root / 'run', gateway)
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['delivery_size'], [1024, 1024])
        self.assertFalse(result['render_size_honored'])
        self.assertIn('size_notice', result)
        brief = json.loads((self.root / 'run' / 'brief.json').read_text())
        self.assertEqual(brief['framing_policy'], FRAMING_ID)
        self.assertEqual((brief['size'], brief['render_size']), ('1024x1024', '1024x1024'))
        request = self.prepare('confirmed', **dict(brief, stage='final', approved_preview=result['delivery']))
        self.assertEqual(request['quality'], 'high')
        self.assertEqual(request['framing_plan']['id'], FRAMING_ID)
        self.assertEqual(request['delivery_size'], '1024x1024')


if __name__ == '__main__':
    unittest.main()
