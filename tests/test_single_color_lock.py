"""Single previews and HD use exact local plans, never direct model coloring."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import build_prompt
import source_colorways


class SingleColorLockTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        self.temp = tempfile.TemporaryDirectory(prefix='avatar-single-colors-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.photo = self.root/'photo.png'
        Image.new('RGB', (80, 100), '#BA8968').save(self.photo)
        self.brief = {'photo': str(self.photo), 'identity_source': 'photo', 'variants': 1}

    def prepare(self, name='single', **changes):
        brief = dict(self.brief, **changes)
        before = deepcopy(brief)
        request = build_prompt.prepare(brief, self.root/'brief.json', self.root/name)
        self.assertEqual(brief, before)
        return request

    def test_single_preview_and_hd_both_prepare_one_semantic_master(self):
        for stage in ('preview', 'final'):
            request = self.prepare(stage, stage=stage)
            self.assertEqual(request['variants'], 1)
            self.assertEqual(request['master_encoding'], 'semantic-props-v3')
            self.assertEqual(len(request['variant_plans']), 1)
            plan = request['variant_plans'][0]
            self.assertEqual(plan['roles'], request['color_plan']['roles'])
            self.assertEqual(plan['line_plan'], request['line_plan'])
            self.assertEqual(plan['source_selection'], request['color_plan']['source_selection'])
            self.assertIn('中间编码底稿', Path(request['prompt_file']).read_text())
            self.assertEqual(request['quality'], 'low' if stage == 'preview' else 'high')

    def test_complete_source_single_keeps_its_own_cheek_detail_and_gradient_options(self):
        selected = source_colorways.eligible_colorways()[0]
        request = self.prepare(source_colorway_id=selected['id'])
        plan = request['variant_plans'][0]
        self.assertEqual(plan['roles'], selected['roles'])
        self.assertEqual(plan['gradient_options'], selected.get('gradient_options', []))
        self.assertEqual(source_colorways.validate_plan(plan)['id'], selected['id'])

    def test_natural_rejected_even_with_an_observed_hair_hex(self):
        for roles in (None, {'hair':'自然黑发'}, {'hair':'#302820'}):
            changes={} if roles is None else {'color_roles':roles}
            with self.subTest(roles=roles),self.assertRaisesRegex(ValueError,'natural'):
                self.prepare('natural',color_mode='natural',**changes)

    def test_explicit_shadow_placement_reaches_both_semantic_prompt_routes(self):
        placement = '只在左侧下颌下方保留一小块硬边暗面'
        for workflow in ('fast', 'review'):
            request = self.prepare(workflow, workflow=workflow, shadow_plan=placement)
            prompt = Path(request['prompt_file']).read_text()
            self.assertEqual(prompt.count(placement), 1)
            self.assertIn('皮肤暗面仍只用#00FF00区域编码', prompt)
            self.assertEqual(request['review_spec']['style_lock']['shadow_plan'], placement)


if __name__ == '__main__':
    unittest.main()
