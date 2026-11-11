"""Offline regression: clean prop materials, colored tongues, frozen palettes."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import build_prompt
import object_plan
import recolor_avatar
import semantic_encoding
import source_colorways
import run_avatar
from variant_plans import select_variant_plan
from avatar_test_fixture import encoded_fixture


class ObjectDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_all_70_palettes_supply_distinct_non_ink_object_fills(self):
        for hd in set(range(1, 71)):
            original = source_colorways.plan_for(hd)
            plan = object_plan.upgrade(original)
            object_plan.validate(plan['object_plan'], plan)
            self.assertEqual(plan['roles'], original['roles'])
            self.assertEqual(plan['garment_plan'], original['garment_plan'])
            self.assertLessEqual(set(plan['object_plan']['roles'].values()), set(object_plan.palette_colors(original)))

    def test_17_codes_and_legacy_14_decode_without_role_collisions(self):
        for encoding, codes, role_ids in (
                (semantic_encoding.PROP_ENCODING_ID, semantic_encoding.PROP_ENCODING, semantic_encoding.PROP_IDS),
                (semantic_encoding.ENCODING_ID, semantic_encoding.ENCODING, semantic_encoding.IDS)):
            image = Image.new('RGB', (len(codes) * 20, 40), 'white')
            draw = ImageDraw.Draw(image)
            for index, color in enumerate(codes.values()):
                draw.rectangle((index * 20, 0, index * 20 + 19, 39), fill=color)
            path = self.root / (encoding + '.png')
            image.save(path)
            _, ids, alpha, manifest = semantic_encoding.decode(path, encoding=encoding)
            for index, role in enumerate(codes):
                self.assertEqual(ids.getpixel((index * 20 + 10, 20)), role_ids[role])
                self.assertEqual(alpha.getpixel((index * 20 + 10, 20)), 255 if role == 'line' else 0)
            self.assertEqual(manifest['encoding_id'], encoding)

    def master(self):
        path = self.root / 'master.png'
        encoded_fixture(path, size=(256, 256), garments=True)
        image = Image.open(path)
        draw = ImageDraw.Draw(image)
        for box, role in (((12, 145, 42, 177), 'object_primary'),
                          ((16, 184, 36, 226), 'object_secondary'),
                          ((120, 155, 138, 171), 'tongue')):
            draw.rectangle(box, fill=semantic_encoding.PROP_ENCODING[role], outline='black', width=2)
        image.save(path)
        return path

    def test_four_rendered_palettes_keep_exact_distinct_clean_materials_and_tongue(self):
        plans = [object_plan.upgrade(source_colorways.plan_for(hd)) for hd in (39, 46, 2, 59)]
        with patch('subprocess.run', side_effect=AssertionError('No model calls')), \
                patch('colorway_selection.draw_colorway_ids', side_effect=AssertionError('No random draw')):
            result = recolor_avatar.render_variants(self.master(), plans, self.root / 'render',
                                                    encoding=semantic_encoding.PROP_ENCODING_ID)
        for path, plan in zip(result['variants'], plans):
            image = Image.open(path)
            colors = plan['object_plan']['roles']
            for xy, role in (((25, 160), 'object_primary'), ((25, 200), 'object_secondary'), ((128, 163), 'tongue')):
                self.assertEqual(image.getpixel(xy), tuple(bytes.fromhex(colors[role][1:])))
            self.assertNotEqual(image.getpixel((25, 160)), image.getpixel((25, 200)))
            self.assertNotEqual(image.getpixel((128, 163)), tuple(bytes.fromhex(plan['roles']['outline'][1:])))
            self.assertEqual(image.getpixel((0, 0)), tuple(bytes.fromhex(plan['roles']['background'][1:])))
            self.assertEqual(image.getpixel((115, 85)), tuple(bytes.fromhex(plan['roles']['skin_base'][1:])))
        self.assertEqual(len({x['role_map_sha256'] for x in result['variant_details']}), 1)
        self.assertEqual(len({x['line_alpha_sha256'] for x in result['variant_details']}), 1)

    def test_black_foreign_and_indistinguishable_object_colors_are_rejected(self):
        plan = object_plan.upgrade(source_colorways.plan_for(59))
        for key, color in (('tongue', '#000000'), ('object_primary', '#123456'),
                           ('object_secondary', plan['object_plan']['roles']['object_primary'])):
            bad = deepcopy(plan['object_plan'])
            bad['roles'][key] = color
            with self.subTest(key=key, color=color), self.assertRaises(ValueError):
                object_plan.validate(bad, plan)

    def test_foreign_specks_and_isolated_ink_are_rejected_without_erasing_lines(self):
        ids = Image.new('L', (64, 64), 7)
        ImageDraw.Draw(ids).rectangle((10, 10, 45, 45), fill=14)
        alpha = Image.new('L', ids.size, 0)
        object_plan.validate_clean_regions(ids, alpha, semantic_encoding.PROP_IDS)
        for kind in ('fill', 'ink'):
            bad, ink = ids.copy(), alpha.copy()
            if kind == 'fill':
                bad.putpixel((25, 25), 11)
            else:
                ink.putpixel((25, 25), 255)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, '孤立颗粒'):
                object_plan.validate_clean_regions(bad, ink, semantic_encoding.PROP_IDS)
        ImageDraw.Draw(alpha).line((5, 25, 35, 25), fill=255, width=1)
        object_plan.validate_clean_regions(ids, alpha, semantic_encoding.PROP_IDS)
        tiny = Image.new('L', ids.size, 7)
        tiny.putpixel((25, 25), 14)
        with self.assertRaisesRegex(ValueError, '孤立编码点'):
            object_plan.validate_clean_regions(tiny, Image.new('L', ids.size, 0), semantic_encoding.PROP_IDS)

    def test_selected_palette_and_approved_object_mapping_remain_frozen(self):
        plans = [object_plan.upgrade(source_colorways.plan_for(hd)) for hd in (39, 46, 2, 59)]
        approved = plans[0]['object_plan']
        for index, plan in enumerate(plans, 1):
            plan['variant_index'] = index
        approved['roles'] = {'object_primary': '#FFD8C5', 'object_secondary': '#FFBE46', 'tongue': '#FFC093'}
        selected = select_variant_plan({'variants': 4, 'variant_plans': plans}, 1)
        self.assertEqual(selected['object_plan'], approved)
        selected['object_plan']['roles']['tongue'] = '#FFC5A1'
        self.assertEqual(approved['roles']['tongue'], '#FFC093')

    def test_preview_and_final_single_and_quad_prepare_and_freeze_object_plans(self):
        photo = self.root / 'photo.png'
        Image.new('RGB', (80, 100), '#BA8968').save(photo)
        for stage in ('preview', 'final'):
            for count in (1, 4):
                brief = {'photo': str(photo), 'identity_source': 'photo', 'stage': stage, 'variants': count}
                if count == 4:
                    brief['colorway_reference_ids'] = [39, 46, 2, 59]
                else:
                    brief['source_colorway_id'] = source_colorways.plan_for(39)['id']
                request = build_prompt.prepare(brief, self.root / 'brief.json', self.root / f'{stage}-{count}')
                self.assertEqual(request['master_encoding'], semantic_encoding.PROP_ENCODING_ID)
                for plan in request['variant_plans']:
                    object_plan.validate(plan['object_plan'], plan)
                self.assertEqual(request['color_plan']['object_plan'], request['variant_plans'][0]['object_plan'])

    def test_explicit_palette_change_replaces_old_object_mapping(self):
        import json
        photo = self.root / 'photo.png'
        Image.new('RGB', (80, 100), '#BA8968').save(photo)
        old = object_plan.upgrade(source_colorways.plan_for(39))
        brief = {'photo': str(photo), 'identity_source': 'photo', 'variants': 1,
                 'source_colorway_id': old['id'], 'object_plan': old['object_plan']}
        path = self.root / 'brief.json'
        path.write_text(json.dumps(brief))
        for options in (['--colorway-reference', '46'], ['--random-colors']):
            with self.subTest(options=options), patch.object(run_avatar, 'run', return_value={'status': 'completed'}) as runner:
                self.assertEqual(run_avatar.main(['--brief', str(path), *options]), 0)
                self.assertNotIn('object_plan', runner.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
