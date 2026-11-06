"""Offline runner checks: no credentials, network, or image model calls."""
import contextlib
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import run_avatar


class FastRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-fast-runner-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)
        self.photo = self.root / 'photo.png'
        Image.new('RGB', (240, 320), '#ba8968').save(self.photo)
        self.brief = {
            'photo': str(self.photo),
            'identity_features': ['较宽的圆下颌', '短发轮廓', '细长眼与闭口微笑'],
            'expression': '闭口微笑，目视镜头', 'pose': '近正面略歪头',
        }
        self.originals = {}

    def gateway(self, status='completed', image_size=(512, 512), returncode=0,
                write_result=True, files=True):
        def fake(argv, **kwargs):
            render = Path(argv[argv.index('--out-dir') + 1])
            render.mkdir(parents=True)
            original = render / 'image-01.png'
            payload = {'status': status, 'api_seconds': 3.5,
                       'headers_seconds': 1.0, 'body_seconds': 2.5,
                       'request_id': 'offline-fixture', 'model': 'offline-model',
                       'started_at': '2026-11-07T00:00:00+00:00'}
            if status == 'completed' and files:
                Image.new('RGB', image_size, '#a1e5d2').save(original)
                self.originals[str(original)] = original.read_bytes()
                payload['files'] = [{'original': str(original), 'format': 'png',
                                     'bytes': original.stat().st_size}]
            if write_result:
                (render / 'result.json').write_text(json.dumps(payload), encoding='utf-8')
            return subprocess.CompletedProcess(argv, returncode)
        return mock.Mock(side_effect=fake)

    def invoke(self, gateway=None, name='run', brief=None):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = run_avatar.run(brief or self.brief, self.root / name,
                                    gateway_runner=gateway or self.gateway())
        return result, stream.getvalue()

    def test_completed_uses_one_process_and_preserves_original(self):
        gateway = self.gateway()
        result, log = self.invoke(gateway)
        gateway.assert_called_once()
        argv = gateway.call_args[0][0]
        options = gateway.call_args[1]
        self.assertEqual(options, {'cwd': str(Path.cwd().resolve()), 'check': False})
        self.assertEqual(argv[-2:], ['--out-dir', str(self.root / 'run' / 'render')])
        self.assertNotIn('--model', argv)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['upstream_status'], 'completed')
        self.assertEqual(result['visual_review'], 'not_performed')
        with Image.open(result['delivery']) as image:
            self.assertEqual((image.format, image.size), ('PNG', (512, 512)))
        self.assertEqual(result['stage'], 'preview')
        self.assertTrue(result['awaiting_hd_confirmation'])
        self.assertTrue(result['render_size_honored'])
        self.assertEqual(argv[argv.index('--size')+1], '512x512')
        self.assertEqual(argv[argv.index('--quality')+1], 'low')
        original = Path(result['original'])
        self.assertEqual(original.read_bytes(), self.originals[str(original)])
        with Image.open(original) as image:
            self.assertEqual(image.size, (512, 512))
        self.assertTrue((self.root / 'run' / 'brief.json').is_file())
        self.assertTrue((self.root / 'run' / 'request' / 'generation-request.json').is_file())
        self.assertFalse((self.root / 'run' / 'review').exists())
        self.assertEqual(len(log.splitlines()), 1)
        self.assertEqual(json.loads(log)['status'], 'completed')

    def test_monotonic_timings_and_short_log_do_not_echo_brief_or_body(self):
        clock = [0, 1, 2, 3, 8, 9, 10, 11]
        brief = dict(self.brief, user_notes='private-input-not-for-log')
        with mock.patch.object(run_avatar, 'monotonic', side_effect=clock):
            result, log = self.invoke(self.gateway(), brief=brief)
        self.assertEqual(result['timings'], {
            'preparation_seconds': 1.0, 'gateway_process_seconds': 5.0,
            'delivery_seconds': 1.0, 'total_seconds': 11.0,
            'upstream_api_seconds': 3.5, 'gateway_overhead_seconds': 1.5,
        })
        self.assertLess(len(log), 1200)
        self.assertNotIn('private-input-not-for-log', log)
        self.assertNotIn('headers_seconds', log)
        self.assertNotIn('body_seconds', log)
        self.assertNotIn('argv', log)
        stored = json.loads(Path(result['result_file']).read_text())
        self.assertEqual(stored['timings'], result['timings'])
        self.assertIn('excludes prelaunch tool and approval waits', log)

    def test_utc_timestamps_and_upstream_request_identity_are_saved(self):
        result, _ = self.invoke()
        started = datetime.fromisoformat(result['started_at'])
        finished = datetime.fromisoformat(result['finished_at'])
        self.assertEqual(started.utcoffset(), timedelta(0))
        self.assertEqual(finished.utcoffset(), timedelta(0))
        self.assertLessEqual(started, finished)
        self.assertEqual(result['model'], 'offline-model')
        self.assertEqual(result['request_id'], 'offline-fixture')
        self.assertEqual(result['upstream_started_at'], '2026-11-07T00:00:00+00:00')
        self.assertNotEqual(result['started_at'], result['upstream_started_at'])

    def test_default_subprocess_runner_streams_without_capture(self):
        gateway = self.gateway()
        with mock.patch.object(run_avatar.subprocess, 'run', gateway):
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_avatar.run(self.brief, self.root / 'default-runner')
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('capture_output', gateway.call_args[1])
        self.assertNotIn('stdout', gateway.call_args[1])
        self.assertNotIn('stderr', gateway.call_args[1])

    def test_failed_and_pending_requests_never_retry_or_finalize(self):
        for status in ('failed', 'pending', 'timeout', 'unknown'):
            with self.subTest(status=status):
                gateway = self.gateway(status=status)
                with mock.patch.object(run_avatar.finalize_avatar, 'finalize') as finalize:
                    result, _ = self.invoke(gateway, name=status)
                gateway.assert_called_once()
                finalize.assert_not_called()
                self.assertEqual((result['status'], result['upstream_status']), ('failed', status))
                self.assertEqual(result['error_code'], 'upstream_not_completed')
                self.assertFalse((self.root / status / 'avatar.png').exists())
                stored = json.loads(Path(result['result_file']).read_text())
                self.assertEqual(stored['upstream_status'], status)

    def test_missing_result_is_unknown_and_is_not_retried(self):
        gateway = self.gateway(write_result=False)
        result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['upstream_status'], 'unknown')
        self.assertEqual(result['error_code'], 'upstream_result_missing')
        self.assertNotIn('delivery', result)

    def test_invalid_result_is_unknown_and_is_not_retried(self):
        def fake(argv, **kwargs):
            render = Path(argv[-1])
            render.mkdir()
            (render / 'result.json').write_text('invalid-json', encoding='utf-8')
            return subprocess.CompletedProcess(argv, 0)
        gateway = mock.Mock(side_effect=fake)
        result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['upstream_status'], 'unknown')
        self.assertEqual(result['error_code'], 'upstream_result_invalid')

    def test_process_error_keeps_saved_upstream_state_and_never_retries(self):
        def fake(argv, **kwargs):
            render = Path(argv[-1])
            render.mkdir()
            (render / 'result.json').write_text('{"status":"pending"}', encoding='utf-8')
            raise subprocess.TimeoutExpired(argv, 1)
        gateway = mock.Mock(side_effect=fake)
        result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['upstream_status'], 'pending')
        self.assertEqual(result['error_code'], 'gateway_process_failed')

    def test_nonzero_exit_does_not_finalize_completed_result(self):
        gateway = self.gateway(returncode=1)
        with mock.patch.object(run_avatar.finalize_avatar, 'finalize') as finalize:
            result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        finalize.assert_not_called()
        self.assertEqual(result['upstream_status'], 'completed')
        self.assertEqual(result['error_code'], 'gateway_process_failed')

    def test_completed_without_file_does_not_finalize(self):
        gateway = self.gateway(files=False)
        result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['error_code'], 'upstream_image_missing')

    def test_small_image_failure_does_not_generate_again(self):
        gateway = self.gateway(image_size=(256, 256))
        result, _ = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['upstream_status'], 'completed')
        self.assertEqual(result['error_code'], 'delivery_failed')
        self.assertIn('不能把放大图宣称为高清成品', result['error'])
        self.assertTrue(Path(result['original']).is_file())
        self.assertFalse((self.root / 'run' / 'avatar.png').exists())

    def test_existing_output_is_preserved_without_gateway_call(self):
        directory = self.root / 'existing'
        directory.mkdir()
        sentinel = directory / 'result.json'
        sentinel.write_text('existing-result', encoding='utf-8')
        before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
        gateway = self.gateway()
        with self.assertRaises(ValueError):
            run_avatar.run(self.brief, directory, gateway_runner=gateway)
        gateway.assert_not_called()
        self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(), before)

    def test_output_in_skill_is_rejected_before_writing(self):
        gateway = self.gateway()
        with self.assertRaises(ValueError):
            run_avatar.run(self.brief, SKILL / 'outputs' / 'must-not-exist', gateway_runner=gateway)
        gateway.assert_not_called()
        self.assertFalse((SKILL / 'outputs' / 'must-not-exist').exists())

    def test_preparation_failure_does_not_call_gateway(self):
        gateway = self.gateway()
        result, _ = self.invoke(gateway, brief=dict(self.brief, identity_features=['one']))
        gateway.assert_not_called()
        self.assertEqual(result['upstream_status'], 'not_started')
        self.assertEqual(result['error_code'], 'preparation_failed')
        self.assertIn('identity_features', result['error'])

    def test_cli_short_brief_uses_defaults_and_passes_model_unchanged(self):
        args = ['--photo', str(self.photo), '--expression', '微笑', '--pose', '正面',
                '--model', 'gpt-image-2', '--out-dir', str(self.root / 'cli')]
        for feature in self.brief['identity_features']:
            args.extend(['--feature', feature])
        with mock.patch.object(run_avatar, 'run', return_value={'status': 'completed'}) as runner:
            self.assertEqual(run_avatar.main(args), 0)
        brief, out_dir = runner.call_args[0]
        self.assertEqual(brief['hd_reference_id'], 25)
        self.assertEqual((brief['mode'], brief['color_mode'], brief['stage']), ('flat', 'expressive', 'preview'))
        self.assertNotIn('quality', brief)
        # Model exclusion belongs to global gen-img; no local alternative is selected.
        self.assertEqual(brief['model'], 'gpt-image-2')
        self.assertEqual(out_dir, self.root / 'cli')

    def test_cli_existing_brief_resolves_photo_and_preserves_explicit_style(self):
        brief_path = self.root / 'input.json'
        brief_path.write_text(json.dumps(dict(self.brief, photo='photo.png', hd_reference_id=8,
                                             mode='gradient', quality='high')), encoding='utf-8')
        with mock.patch.object(run_avatar, 'run', return_value={'status': 'completed'}) as runner:
            self.assertEqual(run_avatar.main(['--brief', str(brief_path)]), 0)
        brief, out_dir = runner.call_args[0]
        self.assertEqual(brief['photo'], str(self.photo))
        self.assertEqual((brief['hd_reference_id'], brief['mode'], brief['quality']), (8, 'gradient', 'high'))
        self.assertNotIn('model', brief)
        self.assertEqual(out_dir.parent, Path.cwd() / 'outputs' / 'avatars')

    def test_cli_existing_brief_without_mode_uses_reference_technique(self):
        brief_path = self.root / 'auto-input.json'
        brief_path.write_text(json.dumps(dict(self.brief, hd_reference_id=8)), encoding='utf-8')
        gateway = self.gateway()
        out_dir = self.root / 'auto-mode'
        with mock.patch.object(run_avatar.subprocess, 'run', gateway):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_avatar.main([
                    '--brief', str(brief_path), '--out-dir', str(out_dir)]), 0)
        gateway.assert_called_once()
        request = json.loads((out_dir / 'request' / 'generation-request.json').read_text())
        self.assertEqual(request['mode'], 'gradient')

    def test_cli_validation_error_displays_actionable_reason(self):
        brief_path = self.root / 'input.json'
        brief_path.write_text(json.dumps(self.brief), encoding='utf-8')
        reason = '输出目录已有文件，请选择新目录以保留此前结果'
        stream = io.StringIO()
        with mock.patch.object(run_avatar, 'run', side_effect=ValueError(reason)):
            with contextlib.redirect_stderr(stream):
                with self.assertRaises(SystemExit) as failure:
                    run_avatar.main(['--brief', str(brief_path)])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn(reason, stream.getvalue())
        self.assertNotIn('identity_features', stream.getvalue())

    def test_oversized_preview_is_disclosed_without_claiming_resource_savings(self):
        gateway = self.gateway(image_size=(1024, 1024))
        result, log = self.invoke(gateway)
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['render_size_honored'])
        self.assertIn('不能据此声称已节省', result['size_notice'])
        self.assertIn('size_notice', json.loads(log))
        self.assertEqual(result['delivery_size'], [512, 512])

    def test_confirmed_preview_can_be_used_for_separate_hd_request(self):
        first, _ = self.invoke(name='preview')
        gateway = self.gateway(image_size=(1024, 1024))
        with mock.patch.object(run_avatar.subprocess, 'run', gateway):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_avatar.main([
                    '--brief', str(self.root/'preview'/'brief.json'), '--stage', 'final',
                    '--approved-preview', first['delivery'], '--out-dir', str(self.root/'hd')]), 0)
        gateway.assert_called_once()
        argv = gateway.call_args[0][0]
        self.assertEqual(argv[argv.index('--size')+1], '1024x1024')
        self.assertEqual(argv[argv.index('--quality')+1], 'high')
        images = [argv[i+1] for i, value in enumerate(argv) if value == '--image']
        self.assertEqual(images[0], str(self.photo))
        self.assertEqual(images[2], first['delivery'])
        result = json.loads((self.root/'hd'/'result.json').read_text())
        self.assertEqual(result['stage'], 'final')
        self.assertFalse(result['awaiting_hd_confirmation'])
        self.assertEqual(result['delivery_size'], [1000, 1000])
        self.assertTrue(Path(first['delivery']).is_file())
        preview_request = json.loads((self.root/'preview'/'request'/'generation-request.json').read_text())
        final_request = json.loads((self.root/'hd'/'request'/'generation-request.json').read_text())
        self.assertEqual(final_request['color_plan'], preview_request['color_plan'])
        self.assertEqual(final_request['color_mode'], 'expressive')


if __name__ == '__main__':
    unittest.main()
