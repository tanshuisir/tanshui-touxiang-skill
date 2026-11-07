"""Local color variants share source geometry; no gateway calls or extra libs."""
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import recolor_avatar
import source_colorways


class RecolorAvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-four-color-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.master = self.root / 'master.png'
        self.make_master(self.master)
        self.plans = [source_colorways.plan_for(reference) for reference in (25, 55, 16, 47)]
        self.backgrounds = [plan['roles']['background'] for plan in self.plans]

    def make_master(self, destination, scale=3, hair=True, clothing=True):
        size = (128, 160)
        image = Image.new('RGB', tuple(value * scale for value in size), '#FFFFFF')
        draw = ImageDraw.Draw(image)
        box = lambda values: tuple(value * scale for value in values)
        if hair:
            draw.ellipse(box((12, 4, 116, 142)), fill='#FFFF00', outline='#000000', width=4 * scale)
        draw.ellipse(box((28, 30, 100, 115)), fill='#FF0000', outline='#000000', width=4 * scale)
        draw.polygon(box((83, 43, 94, 70, 82, 103, 67, 107)), fill='#00FF00')
        if clothing:
            draw.rectangle(box((28, 116, 104, 160)), fill='#00FFFF', outline='#000000', width=4 * scale)
        draw.ellipse(box((38, 73, 50, 85)), fill='#FF00FF')
        draw.ellipse(box((77, 73, 89, 85)), fill='#FF00FF')
        draw.ellipse(box((44, 55, 53, 64)), fill='#000000')
        draw.ellipse(box((76, 55, 85, 64)), fill='#000000')
        draw.ellipse(box((55, 89, 73, 97)), fill='#0000FF', outline='#000000', width=2 * scale)
        if scale > 1:
            image = image.resize(size, Image.Resampling.LANCZOS)
        image.save(destination)

    def render(self, plans=None, out_name='four'):
        return recolor_avatar.render_variants(self.master, plans or self.plans, self.root / out_name)

    def test_four_variants_keep_identical_line_geometry_and_native_pixel_dimensions(self):
        result = self.render()
        self.assertEqual(result['master_size'], [128, 160])
        self.assertEqual(result['delivery_size'], [256, 320])
        self.assertTrue(result['geometry_lock']['same_pixel_geometry'])
        manifest = json.loads(Path(result['mask_manifest']).read_text())
        with Image.open(manifest['line_alpha_file']) as lines:
            alpha = lines.copy()
        self.assertEqual(hashlib.sha256(alpha.tobytes()).hexdigest(), manifest['line_alpha_sha256'])
        line_core = alpha.point([255 if value == 255 else 0 for value in range(256)])
        self.assertTrue(line_core.getbbox())
        signatures = set()
        for plan, path, detail in zip(self.plans, result['variants'], result['variant_details']):
            with Image.open(path) as image:
                self.assertEqual(image.size, (128, 160))
                self.assertEqual(image.mode, 'RGB')
                signatures.add(hashlib.sha256(image.tobytes()).hexdigest())
                self.assertEqual(image.getcolors(maxcolors=100000) is not None, True)
                self.assertEqual(image.getpixel((0, 0)), tuple(bytes.fromhex(self.backgrounds[detail['index'] - 1][1:])))
                self.assertEqual(image.histogram(mask=line_core),
                                 Image.new('RGB', image.size, plan['roles']['outline']).histogram(mask=line_core))
            self.assertEqual(detail['role_map_sha256'], manifest['role_map_sha256'])
            self.assertEqual(detail['line_alpha_sha256'], manifest['line_alpha_sha256'])
            self.assertEqual(detail['source_colorway'], plan['source_colorway'])
        self.assertEqual(len(signatures), 4)

    def test_background_is_solid_and_hair_has_true_continuous_gradient(self):
        result = self.render()
        role_map = Image.open(self.root / 'four/role-ids.png')
        line_alpha = Image.open(self.root / 'four/line-alpha.png')
        for index, path in enumerate(result['variants']):
            with Image.open(path) as image:
                background, hair = set(), set()
                for xy in ((x, y) for y in range(image.height) for x in range(image.width)):
                    if line_alpha.getpixel(xy) == 0:
                        role = role_map.getpixel(xy)
                        if role == 7:
                            background.add(image.getpixel(xy))
                        if role == 6:
                            hair.add(image.getpixel(xy))
                self.assertEqual(background, {tuple(bytes.fromhex(self.backgrounds[index][1:]))})
                self.assertGreater(len(hair), 16)
        role_map.close()
        line_alpha.close()

    def test_actual_source_endpoint_colors_and_transition_have_visible_area(self):
        result = self.render()
        for detail in result['variant_details']:
            applied = detail['applied_gradients']
            self.assertTrue(any(item['visibility']['qualifies_as_required'] for item in applied))
            for item in applied:
                metrics = item['visibility']
                self.assertTrue(metrics['visible'])
                self.assertGreaterEqual(metrics['visible_area_fractions']['from'], 0.05)
                self.assertGreaterEqual(metrics['visible_area_fractions']['to'], 0.05)
                self.assertGreaterEqual(metrics['visible_area_fractions']['transition'], 0.20)
                self.assertGreaterEqual(metrics['delivered_rgb_distance'], metrics['source_rgb_distance'] * 0.69)
                self.assertEqual(item['coordinate_domain']['method'], 'visible-fill-area-quantiles-v1')

    def test_invisible_hair_role_labels_under_bottom_ink_do_not_dilute_short_hair_gradient(self):
        image = Image.new('RGB', (128, 160), '#FFFFFF')
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 10, 108, 60), fill='#FFFF00', outline='#000000', width=4)
        draw.rectangle((33, 55, 95, 109), fill='#FF0000', outline='#000000', width=4)
        draw.rectangle((20, 112, 108, 140), fill='#00FFFF', outline='#000000', width=4)
        # Tiny nonzero RGB channels below the black-ink cutoff can retain a
        # yellow role label, but they are invisible in the delivered drawing.
        draw.rectangle((5, 145, 122, 155), fill='#010100')
        image.save(self.master)
        result = self.render()
        role_map = Image.open(self.root / 'four/role-ids.png')
        raw_hair = role_map.point([255 if value == 6 else 0 for value in range(256)])
        self.assertGreater(raw_hair.getbbox()[3], 145)
        for detail in result['variant_details']:
            hair = next(item for item in detail['applied_gradients'] if item['gradient']['region'] == 'hair')
            self.assertLess(hair['coordinate_domain']['end'], 61)
            self.assertTrue(hair['visibility']['qualifies_as_required'])
        role_map.close()

    def test_varying_weight_map_cannot_pass_when_final_rgb_is_flat(self):
        original = recolor_avatar._gradient_image
        def flat_render(size, bounds, gradient):
            _, weights = original(size, bounds, gradient)
            return Image.new('RGB', size, gradient['from']), weights
        with patch.object(recolor_avatar, '_gradient_image', side_effect=flat_render):
            with self.assertRaisesRegex(ValueError, '最终RGB可见性'):
                self.render()
        self.assertFalse((self.root / 'four/avatar-four-colors.png').exists())
        self.assertFalse((self.root / 'four/variant-01.png').exists())

    def test_two_endpoint_blocks_are_not_a_continuous_gradient(self):
        image = Image.new('RGB', (100, 100), '#FF0000')
        ImageDraw.Draw(image).rectangle((50, 0, 99, 99), fill='#FFFF00')
        metrics = recolor_avatar._gradient_metrics(image, Image.new('L', image.size, 255),
                                                   {'from': '#FF0000', 'to': '#FFFF00'})
        self.assertFalse(metrics['qualifies_as_required'])
        self.assertFalse(metrics['checks']['continuous_transition_area'])

    def test_subtle_variation_cannot_be_the_only_required_visible_gradient(self):
        gradient = {'from': '#101010', 'to': '#181818', 'direction': '从上到下'}
        fill = Image.new('L', (100, 100), 255)
        bounds, _ = recolor_avatar._gradient_domain(fill, gradient)
        image, _ = recolor_avatar._gradient_image(fill.size, bounds, gradient)
        metrics = recolor_avatar._gradient_metrics(image, fill, gradient)
        self.assertTrue(metrics['visible'])
        self.assertFalse(metrics['qualifies_as_required'])

    def test_tiny_scattered_gradient_patches_cannot_qualify_as_avatar_gradient(self):
        image = Image.new('RGB', (1024, 1024), '#FFFFFF')
        draw = ImageDraw.Draw(image)
        draw.ellipse((350, 350, 650, 700), fill='#FF0000', outline='#000000', width=6)
        for row in range(4):
            for column in range(5):
                x, y = 100 + column * 160, 60 + row * 50
                draw.rectangle((x, y, x + 11, y + 11), fill='#FFFF00')
        image.save(self.master)
        with self.assertRaisesRegex(ValueError, '最终RGB可见性'):
            self.render()
        self.assertFalse((self.root / 'four/avatar-four-colors.png').exists())

    def test_native_gradient_must_also_survive_avatar_thumbnail(self):
        size = (512, 512)
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)
        for x in range(0, size[0], 16):
            draw.rectangle((x, 0, x + 1, size[1] - 1), fill=255)
        gradient = {'from': '#FF0000', 'to': '#FFFF00', 'direction': '从上到下'}
        domain, _ = recolor_avatar._gradient_domain(mask, gradient)
        paint, _ = recolor_avatar._gradient_image(size, domain, gradient)
        image = Image.composite(paint, Image.new('RGB', size, '#0000FF'), mask)
        metrics = recolor_avatar._gradient_metrics(image, mask, gradient)
        self.assertTrue(metrics['checks']['minimum_visible_area'])
        self.assertTrue(metrics['checks']['both_source_colors_visible'])
        self.assertTrue(metrics['checks']['continuous_transition_area'])
        self.assertEqual(metrics['thumbnail']['evaluation_size'], [128, 128])
        self.assertFalse(metrics['checks']['thumbnail_visibility'])
        self.assertFalse(metrics['qualifies_as_required'])

    def test_same_reference_hair_and_clothing_gradients_are_both_preserved(self):
        plans = [source_colorways.plan_for(reference) for reference in (6, 55, 16, 47)]
        result = self.render(plans)
        for index in (0, 3):
            self.assertEqual({item['gradient']['region'] for item in result['variant_details'][index]['applied_gradients']},
                             {'hair', 'clothing'})
        clothing = next(item for item in result['variant_details'][0]['applied_gradients']
                        if item['gradient']['region'] == 'clothing')
        self.assertEqual(clothing['coordinate_domain']['projection_vector'], [1, 1])

    def test_all_diagonal_and_reversed_directions_follow_source_orientation(self):
        for direction, first, last in [
                ('从左上到右下', (0, 0), (99, 99)),
                ('从右下到左上', (99, 99), (0, 0)),
                ('从右上到左下', (99, 0), (0, 99)),
                ('从左下到右上', (0, 99), (99, 0)),
                ('从右到左', (99, 50), (0, 50)),
                ('从下到上', (50, 99), (50, 0))]:
            with self.subTest(direction=direction):
                gradient = {'from': '#FF0000', 'to': '#FFFF00', 'direction': direction}
                fill = Image.new('L', (100, 100), 255)
                domain, _ = recolor_avatar._gradient_domain(fill, gradient)
                image, _ = recolor_avatar._gradient_image(fill.size, domain, gradient)
                self.assertEqual(image.getpixel(first), (255, 0, 0))
                self.assertEqual(image.getpixel(last), (255, 255, 0))
                self.assertTrue(recolor_avatar._gradient_metrics(image, fill, gradient)['qualifies_as_required'])

    def test_grayscale_antialias_line_is_reused_instead_of_becoming_a_white_halo(self):
        result = self.render()
        alpha = Image.open(self.root / 'four/line-alpha.png')
        counts = alpha.histogram()
        self.assertGreater(sum(counts[9:255]), 0)
        source = Image.open(self.master)
        for path in result['variants']:
            with Image.open(path) as image:
                self.assertEqual(image.size, source.size)
        alpha.close()
        source.close()

    def test_skin_accent_and_detail_fills_follow_each_reference_palette(self):
        result = self.render()
        role_fields = {4: 'skin_base', 2: 'skin_shadow', 5: 'cheek', 1: 'detail'}
        with Image.open(self.root / 'four/role-ids.png') as role_map, \
                Image.open(self.root / 'four/line-alpha.png') as line_alpha:
            regions, alpha = list(role_map.getdata()), list(line_alpha.getdata())
        for plan, path in zip(self.plans, result['variants']):
            colors = {role: set() for role in role_fields}
            with Image.open(path) as image:
                for role, ink_alpha, pixel in zip(regions, alpha, image.getdata()):
                    if ink_alpha == 0 and role in colors:
                        colors[role].add(pixel)
            for role, field in role_fields.items():
                with self.subTest(reference=plan['source_hd_id'], role=field):
                    self.assertEqual(colors[role], {tuple(bytes.fromhex(plan['roles'][field][1:]))})

    def test_single_complete_colorway_keeps_exact_skin_and_native_dimensions(self):
        result = self.render(self.plans[:1], 'single')
        self.assertEqual(len(result['variants']), 1)
        self.assertEqual(result['delivery_size'], [128, 160])
        self.assertEqual(Path(result['delivery']).name, 'avatar.png')
        self.assertFalse((self.root / 'single/avatar-four-colors.png').exists())
        with Image.open(result['delivery']) as image:
            self.assertEqual(image.getpixel((0, 0)), tuple(bytes.fromhex(self.backgrounds[0][1:])))
            self.assertEqual(image.getpixel((60, 75)),
                             tuple(bytes.fromhex(self.plans[0]['roles']['skin_base'][1:])))

    def test_ordinary_single_plan_fills_exact_source_skin_without_complete_colorway(self):
        plan = deepcopy(self.plans[0])
        plan.pop('source_colorway')
        plan['roles']['hair'] = '#123456'
        result = self.render([plan], 'ordinary-single')
        self.assertEqual(len(result['variants']), 1)
        with Image.open(result['delivery']) as image:
            self.assertEqual(image.getpixel((60, 75)),
                             tuple(bytes.fromhex(plan['roles']['skin_base'][1:])))

    def test_single_complete_colorway_cannot_move_hair_endpoint_colors_to_clothing(self):
        self.make_master(self.master, hair=False)
        with self.assertRaisesRegex(ValueError, '没有同角色渐变'):
            self.render(self.plans[:1], 'single-no-hair')
        self.assertFalse((self.root / 'single-no-hair/avatar.png').exists())

    def test_single_complete_colorway_uses_its_recorded_clothing_gradient_when_hair_absent(self):
        self.make_master(self.master, hair=False)
        plan = source_colorways.plan_for(6)
        expected = next(item for item in plan['gradient_options'] if item['region'] == 'clothing')
        result = self.render([plan], 'single-clothing')
        gradient = result['variant_details'][0]['gradient']
        self.assertEqual(gradient, {key: expected[key] for key in ('region', 'from', 'to', 'direction')})
        self.assertTrue(result['variant_details'][0]['gradient_region_changed'])

    def test_ordinary_single_plan_retains_legacy_visible_region_fallback(self):
        self.make_master(self.master, hair=False)
        plan = deepcopy(self.plans[0])
        plan.pop('source_colorway')
        plan.pop('gradient_options', None)
        result = self.render([plan], 'ordinary-single-clothing')
        self.assertEqual(result['variant_details'][0]['gradient']['region'], 'clothing')
        self.assertTrue(result['variant_details'][0]['gradient_region_changed'])
        self.assertIsNone(result['variant_details'][0]['source_colorway'])

    def test_white_and_near_white_source_backgrounds_stop_before_delivery(self):
        for index, color in enumerate(('#FFFFFF', '#FAF7FA', '#FFE9F0', '#FFF1D7')):
            with self.subTest(color=color):
                plan = deepcopy(self.plans[0])
                plan.pop('source_colorway')
                plan['roles']['background'] = color
                output = self.root / f'forbidden-{index}'
                with self.assertRaisesRegex(ValueError, '背景'):
                    recolor_avatar.render_variants(self.master, [plan], output)
                self.assertFalse(output.exists())

    def test_detail_code_cannot_leave_white_background_corners(self):
        with Image.open(self.master) as source:
            corrupted = source.copy()
        draw = ImageDraw.Draw(corrupted)
        for x in (0, corrupted.width - 8):
            for y in (0, corrupted.height - 8):
                draw.rectangle((x, y, x + 7, y + 7), fill='#0000FF')
        corrupted.save(self.master)
        output = self.root / 'white-corners'
        with self.assertRaisesRegex(ValueError, '四角'):
            recolor_avatar.render_variants(self.master, self.plans[1:2], output)
        self.assertFalse(output.exists())

    def test_single_plan_conflicting_skin_provenance_stops_before_delivery(self):
        plan = deepcopy(self.plans[0])
        plan.pop('source_colorway')
        plan['source_selection']['skin'] = deepcopy(self.plans[1]['source_selection']['skin'])
        with self.assertRaisesRegex(ValueError, '肤色来源'):
            self.render([plan], 'wrong-provenance')

    def test_single_plan_cannot_add_a_skin_color_or_mix_template_shadows(self):
        for field, value in [('skin_base', '#123456'),
                             ('skin_shadow', self.plans[1]['roles']['skin_shadow'])]:
            plan = deepcopy(self.plans[0])
            plan.pop('source_colorway')
            plan['roles'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '肤色与肤影'):
                self.render([plan], f'invalid-single-{field}')

    def test_ordinary_colored_avatar_is_rejected_without_making_a_grid(self):
        ordinary = self.root / 'ordinary.png'
        Image.new('RGB', (128, 160), '#EFBAD2').save(ordinary)
        with self.assertRaisesRegex(ValueError, '编码不可靠'):
            recolor_avatar.render_variants(ordinary, self.plans, self.root / 'bad')
        self.assertFalse((self.root / 'bad/avatar-four-colors.png').exists())

    def test_small_global_encoding_drift_does_not_put_a_dark_veil_on_flat_fills(self):
        self.make_master(self.master, scale=1)
        with Image.open(self.master) as image:
            drifted = image.point([5 if value == 0 else 248 if value == 255 else value
                                   for value in range(256)] * 3)
            drifted.save(self.master)
        result = self.render()
        with Image.open(self.root / 'four/line-alpha.png') as lines:
            self.assertEqual(lines.getpixel((60, 75)), 0)
        for plan, path in zip(self.plans, result['variants']):
            with Image.open(path) as image:
                self.assertEqual(image.getpixel((60, 75)), tuple(bytes.fromhex(plan['roles']['skin_base'][1:])))

    def test_individually_valid_other_source_colors_cannot_be_mixed_into_one_colorway(self):
        for field in ('skin_base', 'skin_shadow', 'background', 'hair', 'clothing', 'outline', 'cheek'):
            other = next(plan for plan in self.plans[1:]
                         if plan['roles'][field] != self.plans[0]['roles'][field])
            with self.subTest(field=field, borrowed_from=other['source_hd_id']):
                plans = deepcopy(self.plans)
                plans[0]['roles'][field] = other['roles'][field]
                with self.assertRaisesRegex(ValueError, '拆换|来源不符'):
                    self.render(plans, field)
                self.assertFalse((self.root / field / 'avatar-four-colors.png').exists())

    def test_absent_hair_cannot_move_hair_colors_into_clothes_without_source_samples(self):
        self.make_master(self.master, hair=False)
        with self.assertRaisesRegex(ValueError, '没有同角色渐变'):
            self.render()
        self.assertFalse((self.root / 'four/avatar-four-colors.png').exists())

    def test_no_visible_hair_or_clothing_reports_gradient_limit(self):
        self.make_master(self.master, hair=False, clothing=False)
        with self.assertRaisesRegex(ValueError, '头发或衣服'):
            self.render()

    def test_existing_output_is_preserved_and_wrong_plan_count_stops(self):
        self.render()
        grid = self.root / 'four/avatar-four-colors.png'
        before = hashlib.sha256(grid.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, '非空'):
            self.render()
        self.assertEqual(hashlib.sha256(grid.read_bytes()).hexdigest(), before)
        with self.assertRaisesRegex(ValueError, '恰好一个或四个'):
            self.render(self.plans[:3], 'short')

    def test_local_request_cli_reads_variant_plans(self):
        request = self.root / 'request.json'
        request.write_text(json.dumps({'variant_plans': self.plans}))
        with redirect_stdout(io.StringIO()):
            recolor_avatar.main(['--master', str(self.master), '--request', str(request),
                                 '--out-dir', str(self.root / 'cli')])
        self.assertTrue((self.root / 'cli/avatar-four-colors.png').is_file())


if __name__ == '__main__':
    unittest.main()
