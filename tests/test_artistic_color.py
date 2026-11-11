"""Complete source palettes across single/four, preview/final, fast/review."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import build_prompt
from source_colorways import catalog, colorway, validate_plan

class ArtisticColorTests(unittest.TestCase):
    def setUp(self):
        from avatar_test_fixture import isolate_colorway_history
        isolate_colorway_history(self)
        temp=tempfile.TemporaryDirectory(prefix='avatar-complete-colors-')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.photo=self.root/'photo.png'
        Image.new('RGB',(240,320),'#BC8866').save(self.photo)
        self.brief={'photo':str(self.photo),'identity_source':'photo'}
        self.counter=0

    def prepare(self,**kw):
        self.counter+=1
        result=build_prompt.prepare(dict(self.brief,**kw),self.root/'brief.json',self.root/str(self.counter))
        plan=dict(result['color_plan'],background_plan=result['background_plan'],line_plan=result['line_plan'])
        validate_plan(plan)
        expected=colorway(plan['source_hd_id'])
        self.assertEqual(plan['roles'],expected['roles'])
        self.assertEqual(plan['gradient'],expected['gradient'])
        self.assertEqual(result['review_spec']['style_lock']['source_colorway'],plan['source_colorway'])
        return result,plan

    def test_all_complete_catalog_palettes_work_in_both_stages_and_routes(self):
        from source_colorways import eligible_colorways
        for item in eligible_colorways():
            for workflow in ('fast','review'):
                for stage in ('preview','final'):
                    with self.subTest(reference=item['source_hd_id'],workflow=workflow,stage=stage):
                        r,p=self.prepare(source_colorway_id=item['id'],workflow=workflow,stage=stage)
                        self.assertEqual(p['source_hd_id'],item['source_hd_id'])
                        text=Path(r['prompt_file']).read_text()
                        self.assertEqual(r['master_encoding'], 'semantic-props-v3')
                        self.assertEqual(r['variant_plans'][0]['roles'],p['roles'])
                        self.assertIn('背景#FFFFFF',text)
                        self.assertEqual(p['source_selection']['skin']['source_hd_id'],p['source_hd_id'])
                        self.assertEqual(p['source_selection']['background']['source_hd_id'],p['source_hd_id'])

    def test_same_source_has_identical_roles_in_single_and_four(self):
        quad,_=self.prepare(variants=4)
        for original in quad['variant_plans']:
            _,single=self.prepare(source_colorway_id=original['id'])
            self.assertEqual(single['roles'],original['roles'])
            self.assertEqual(single['gradient'],original['gradient'])
            self.assertEqual(single['source_colorway'],original['source_colorway'])

    def test_every_drawing_mode_keeps_complete_source_colors(self):
        for mode in build_prompt.MODES:
            for source in ('photo','observations'):
                kw={'mode':mode,'identity_source':source,'source_colorway_id':'TS-055-colorway'}
                if source=='observations':
                    kw.update(identity_features=['圆下颌','侧分发型','长眼'],expression='平视',pose='侧转')
                _,p=self.prepare(**kw)
                self.assertEqual(p['source_hd_id'],55)

    def test_partial_legacy_overrides_are_replaced_as_one_palette_with_migration(self):
        _,p=self.prepare(color_roles={'skin_base':'#010203','background':'#00DDD6','clothing':'原照衣色'},
                         skin_template_id='TS-048-skin',background_template_id='TS-049-bg-1',
                         gradient={'region':'background','from':'#112233','to':'#445566'})
        self.assertIn(p['source_hd_id'], {item['source_hd_id'] for item in catalog()['colorways']})
        self.assertEqual(p['migration']['from'],'legacy-independent-role-selection')
        self.assertEqual(p['migration']['previous']['skin_template_id'],'TS-048-skin')
        self.assertEqual(p['gradient'],colorway(p['source_hd_id'])['gradient'])

    def test_even_malformed_old_gradients_cannot_disable_source_gradient(self):
        for gradient in (None,False,{}, {'region':'face','from':'#123456','to':'#123456'}):
            _,p=self.prepare(gradient=gradient,source_colorway_id='TS-055-colorway')
            self.assertEqual(p['gradient'],colorway(p['source_hd_id'])['gradient'])
            self.assertIn('migration',p)

    def test_saved_complete_scheme_overrides_stale_legacy_selectors(self):
        _,p=self.prepare(source_colorway_id='TS-055-colorway',art_palette='mint-apricot',
                         line_reference_id=25,skin_template_id='TS-066-skin')
        self.assertEqual(p['source_hd_id'],55)
        self.assertEqual(p['line_plan']['source_reference_id'],55)

    def test_new_explicit_source_can_replace_a_frozen_choice(self):
        _,p=self.prepare(source_colorway_id='TS-055-colorway',colorway_reference_id=47)
        self.assertEqual(p['source_hd_id'],47)

    def test_unavailable_explicit_source_never_silently_falls_back(self):
        for field,value in (('source_colorway_id','invented'),('colorway_reference_id',71),
                            ('requested_palette','missing-palette')):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.prepare(**{field:value})

    def test_style_reference_does_not_pin_the_random_complete_palette(self):
        _,p=self.prepare(hd_reference_id=26)
        self.assertIn(p['source_hd_id'], {item['source_hd_id'] for item in catalog()['colorways']})

    def test_natural_cannot_bypass_complete_palette_in_any_variant_mode(self):
        for variants in (1,4):
            with self.subTest(variants=variants),self.assertRaises(ValueError):
                self.prepare(color_mode='natural',variants=variants)

    def test_old_palette_alias_requires_current_template_identifier(self):
        for field in ('requested_palette', 'art_palette', 'source_colorway_id'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(**{field:'pink-plum'})
        _, plan = self.prepare(requested_palette='TS-055')
        self.assertEqual(plan['source_hd_id'],55)

    def test_tampered_plan_is_rejected_for_each_role_and_gradient(self):
        _,p=self.prepare(source_colorway_id='TS-055-colorway')
        for role in p['roles']:
            changed=deepcopy(p);changed['roles'][role]='#010203'
            with self.subTest(role=role),self.assertRaises(ValueError):validate_plan(changed)
        changed=deepcopy(p);changed['gradient']={'region':'hair','from':'#010203','to':'#040506'}
        with self.assertRaises(ValueError):validate_plan(changed)
