"""Offline upload preparation checks; no credentials, network, or image API."""
import contextlib
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import prepare_inputs
import run_avatar


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_paths(argv):
    return [Path(argv[index + 1]) for index, option in enumerate(argv) if option == '--image']


class PreviewInputTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        temporary = tempfile.TemporaryDirectory(prefix='avatar-preview-input-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.photo = self.root/'photo.png'
        self.style = self.root/'style.png'
        self.quadrants(self.photo, (1800, 1200))
        self.quadrants(self.style, (1600, 1600))

    def quadrants(self, path, size):
        image = Image.new('RGB', size)
        draw = ImageDraw.Draw(image)
        width, height = size
        for box, color in (((0, 0, width//2, height//2), '#D02020'),
                           ((width//2, 0, width, height//2), '#20C040'),
                           ((0, height//2, width//2, height), '#2030D0'),
                           ((width//2, height//2, width, height), '#E0C020')):
            draw.rectangle(box, fill=color)
        image.save(path)

    def request(self, stage='preview'):
        argv = ['python3', '/global/gen-img/run.py', 'edit', '--image', str(self.photo),
                '--image', str(self.style), '--size', '512x512', '--quality', 'low']
        return {'stage':stage, 'workflow':'fast', 'photo':str(self.photo),
                'style_reference':str(self.style), 'argv':argv, 'shell_command':shlex.join(argv),
                'review_spec':{'input_sha256':{'photo':sha256(self.photo), 'style_reference':sha256(self.style)}}}

    def prepare(self, request=None, directory='inputs'):
        request = request if request is not None else self.request()
        prepare_inputs.prepare_inputs(request, self.root/directory)
        return request

    def test_large_inputs_are_downscaled_without_cropping_or_source_changes(self):
        request = self.request()
        originals = deepcopy({key:request[key] for key in ('photo', 'style_reference', 'review_spec')})
        before = {path:sha256(path) for path in (self.photo, self.style)}
        self.prepare(request)
        uploads = image_paths(request['argv'])
        self.assertEqual(len(uploads), 2)
        with Image.open(uploads[0]) as photo:
            self.assertEqual(photo.size, (1024, 683))
            self.assertEqual(photo.format, 'JPEG')
            for location, expected in (((0, 0), (208, 32, 32)), ((photo.width-1, 0), (32, 192, 64)),
                                       ((0, photo.height-1), (32, 48, 208)),
                                       ((photo.width-1, photo.height-1), (224, 192, 32))):
                self.assertLess(max(abs(a-b) for a,b in zip(photo.getpixel(location), expected)), 10)
        with Image.open(uploads[1]) as style:
            self.assertEqual((style.size, style.format), ((512, 512), 'PNG'))
        for key, value in originals.items():
            self.assertEqual(request[key], value)
        self.assertEqual({path:sha256(path) for path in before}, before)
        self.assertEqual(shlex.split(request['shell_command']), request['argv'])

    def test_upload_mapping_matches_actual_source_and_upload_files(self):
        request = self.prepare()
        uploads = image_paths(request['argv'])
        records = request['upload_inputs']
        self.assertEqual(len(records), 2)
        for record, source, upload in zip(records, (self.photo, self.style), uploads):
            self.assertEqual(Path(record['source']), source)
            self.assertEqual(Path(record['upload']), upload)
            self.assertEqual(record['source_sha256'], sha256(source))
            self.assertEqual(record['upload_sha256'], sha256(upload))
            self.assertEqual(record['source_bytes'], source.stat().st_size)
            self.assertEqual(record['upload_bytes'], upload.stat().st_size)
            with Image.open(source) as image:
                self.assertEqual(record['source_size'], list(image.size))
            with Image.open(upload) as image:
                self.assertEqual(record['upload_size'], list(image.size))

    def test_small_inputs_are_never_upscaled(self):
        self.quadrants(self.photo, (80, 120))
        self.quadrants(self.style, (64, 64))
        request = self.prepare()
        for path, expected in zip(image_paths(request['argv']), ((80, 120), (64, 64))):
            with Image.open(path) as image:
                self.assertEqual(image.size, expected)

    def test_exif_rotation_is_applied_before_resizing_and_original_is_preserved(self):
        self.photo = self.root/'rotated.jpg'
        image = Image.new('RGB', (1200, 600), '#D02020')
        image.paste('#2030D0', (600, 0, 1200, 600))
        exif = Image.Exif()
        exif[274] = 6
        image.save(self.photo, quality=95, exif=exif)
        original_hash = sha256(self.photo)
        request = self.prepare()
        upload = image_paths(request['argv'])[0]
        with Image.open(upload) as oriented:
            self.assertEqual(oriented.size, (512, 1024))
            self.assertIn(oriented.getexif().get(274), (None, 1))
            self.assertGreater(oriented.getpixel((256, 30))[0], 150)
            self.assertGreater(oriented.getpixel((256, 990))[2], 150)
        self.assertEqual(sha256(self.photo), original_hash)

    def test_transparent_rgba_and_palette_inputs_keep_alpha_in_png(self):
        for mode in ('RGBA', 'P'):
            with self.subTest(mode=mode):
                self.photo = self.root/f'transparent-{mode}.png'
                if mode == 'RGBA':
                    image = Image.new('RGBA', (1800, 1200), (0, 0, 0, 0))
                    image.paste((90, 40, 160, 255), (400, 300, 1400, 900))
                    image.save(self.photo)
                else:
                    image = Image.new('P', (1800, 1200), 0)
                    image.putpalette([0, 0, 0, 90, 40, 160] + [0]*(768-6))
                    image.paste(1, (400, 300, 1400, 900))
                    image.save(self.photo, transparency=0)
                original_hash = sha256(self.photo)
                request = self.prepare(directory=mode)
                with Image.open(image_paths(request['argv'])[0]) as upload:
                    self.assertEqual(upload.format, 'PNG')
                    self.assertLessEqual(max(upload.size), 1024)
                    self.assertEqual(upload.convert('RGBA').getchannel('A').getextrema(), (0, 255))
                self.assertEqual(sha256(self.photo), original_hash)

    def test_final_keeps_all_three_original_paths_and_does_not_prepare_uploads(self):
        preview = self.root/'approved.png'
        Image.new('RGB', (512, 512), '#9BC8B1').save(preview)
        request = self.request('final')
        request['argv'].extend(['--image', str(preview)])
        request['shell_command'] = shlex.join(request['argv'])
        request['approved_preview'] = str(preview)
        before = deepcopy(request)
        self.prepare(request)
        self.assertEqual(request, before)
        self.assertEqual(image_paths(request['argv']), [self.photo, self.style, preview])
        self.assertFalse((self.root/'inputs').exists())

    def test_existing_upload_file_is_not_overwritten(self):
        first = self.prepare()
        uploads = image_paths(first['argv'])
        before = {path:sha256(path) for path in uploads}
        # Either safely reuse existing identical files or reject the directory;
        # never replace a previously prepared upload silently.
        try:
            self.prepare(self.request())
        except (ValueError, FileExistsError):
            pass
        self.assertEqual({path:sha256(path) for path in before}, before)

    def test_runner_uploads_prepared_inputs_in_one_gateway_request(self):
        brief = {'photo':str(self.photo), 'identity_features':['圆下颌', '侧分短发', '细长眼'],
                 'expression':'闭口微笑', 'pose':'正面'}
        original_hash = sha256(self.photo)
        seen = []
        def fake_gateway(argv, **kwargs):
            seen.extend(image_paths(argv))
            directory = Path(argv[argv.index('--out-dir')+1])
            directory.mkdir()
            original = directory/'image-01.png'
            from avatar_test_fixture import encoded_fixture
            encoded_fixture(original, garments=True)
            (directory/'result.json').write_text(json.dumps({'status':'completed',
                'files':[{'original':str(original), 'format':'png'}]}), encoding='utf-8')
            return subprocess.CompletedProcess(argv, 0)
        gateway = mock.Mock(side_effect=fake_gateway)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_avatar.run(brief, self.root/'run', gateway_runner=gateway)
        gateway.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(seen), 2)
        for path, limit in zip(seen, (1024, 512)):
            with Image.open(path) as image:
                self.assertLessEqual(max(image.size), limit)
        saved = json.loads((self.root/'run'/'brief.json').read_text())
        request = json.loads((self.root/'run'/'request'/'generation-request.json').read_text())
        self.assertEqual(saved['photo'], str(self.photo))
        self.assertEqual(request['photo'], str(self.photo))
        self.assertEqual(request['review_spec']['input_sha256']['photo'], original_hash)
        self.assertEqual(sha256(self.photo), original_hash)
        self.assertEqual(image_paths(request['argv']), seen)


if __name__ == '__main__':
    unittest.main()
