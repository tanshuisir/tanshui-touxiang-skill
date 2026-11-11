"""Offline behavioral tests: clothing layers, provenance, motifs and decoding."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import garment_plan
import recolor_avatar as renderer
import semantic_encoding as encoding
import source_colorways
from avatar_test_fixture import encoded_fixture

class GarmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def master(self,*,pattern=True,inner=True):
        path=self.root/'master.png';im=Image.new('RGB',(256,256),'white');d=ImageDraw.Draw(im)
        d.ellipse((65,20,192,145),fill='#FFFF00',outline='black',width=3)
        d.ellipse((80,52,175,148),fill='#FF0000',outline='black',width=3)
        d.polygon(((155,91),(168,98),(160,139),(144,143)),fill='#00FF00')
        d.ellipse((91,110,107,124),fill='#FF00FF')
        d.ellipse((141,110,155,124),fill='#FF00FF')
        d.ellipse((100,85,106,92),fill='black');d.ellipse((146,85,152,92),fill='black')
        d.polygon(((20,256),(50,167),(200,167),(235,256)),fill='#00FFFF',outline='black',width=3)
        if inner:d.rectangle((100,168,154,255),fill='#FF8000')
        if pattern:
            for y in (185,210,235):d.rectangle((110,y,144,y+6),fill='#FF0080')
        im.save(path);return path

    def test_70_garment_records_use_exact_source_pixels_and_digest(self):
        records=garment_plan.catalog()
        self.assertEqual(set(records),set(range(1,71)))
        for hd,e in records.items():
            path=SKILL/e['source_image']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),e['source_sha256'])
            with Image.open(path) as im:
                im=im.convert('RGB')
                for name,sample in e['samples'].items():
                    self.assertEqual('#'+bytes(im.getpixel(tuple(sample['xy']))).hex().upper(),sample['hex'],(hd,name))
            for role,source_role in e['role_mapping'].items():
                self.assertEqual(e['render_roles'][role],e['samples'][source_role]['hex'])

    def test_every_current_template_keeps_explicit_layer_facts_and_role_mapping(self):
        for number, item in garment_plan.catalog().items():
            with self.subTest(template=number):
                self.assertIsInstance(item['observed_inner'],bool)
                self.assertIsInstance(item['structure'],str)
                self.assertEqual(item['source_image'],f'assets/templates/{number:03d}.png')
                self.assertTrue(set(garment_plan.GARMENT_ROLES).issubset(item['render_roles']))
                self.assertGreaterEqual(len(set(item['render_roles'].values())),2)

    def test_motifs_are_explicit_observations_with_same_template_samples(self):
        for number,item in garment_plan.catalog().items():
            self.assertIsInstance(item['motifs'],list)
            for motif in item['motifs']:
                kind=motif if isinstance(motif,str) else motif['type']
                self.assertIsInstance(kind,str)
                self.assertTrue(kind)
            self.assertIn('clothing_pattern',item['samples'])

    def test_all_14_codes_decode_separately_and_black_alpha_is_preserved(self):
        path=self.root/'codes.png';im=Image.new('RGB',(280,80),'white');d=ImageDraw.Draw(im)
        for n,(role,col) in enumerate(encoding.ENCODING.items()):d.rectangle((n*20,0,n*20+19,79),fill=col)
        im.save(path);_,ids,alpha,_=encoding.decode(path)
        for n,role in enumerate(encoding.ENCODING):
            xy=(n*20+10,40);self.assertEqual(ids.getpixel(xy),encoding.IDS[role])
            self.assertEqual(alpha.getpixel(xy),255 if role=='line' else 0)

    def test_coat_shirt_and_stripes_have_exact_independent_source_colors(self):
        p=source_colorways.plan_for(1)
        result=renderer.render_variants(self.master(),[p],self.root/'render',encoding=encoding.ENCODING_ID)
        with Image.open(result['delivery']) as im:
            colors=p['garment_plan']['render_roles']
            for xy,role in (((55,230),'clothing'),((120,200),'clothing_inner'),((120,187),'clothing_pattern')):
                self.assertEqual(im.getpixel(xy),tuple(bytes.fromhex(colors[role][1:])))
            self.assertNotEqual(im.getpixel((55,230)),im.getpixel((120,200)))
        self.assertTrue(result['geometry_lock']['same_pixel_geometry'])

    def test_clothing_gradient_does_not_paint_over_inner_shirt_or_pattern(self):
        selected=next(x for x in source_colorways.eligible_colorways() if garment_plan.plan_for(x['source_hd_id'])['gradients'])
        p=source_colorways.plan_for(selected['id'])
        result=renderer.render_variants(self.master(),[p],self.root/'gradient',encoding=encoding.ENCODING_ID)
        with Image.open(result['delivery']) as im:
            for xy,role in (((120,200),'clothing_inner'),((120,187),'clothing_pattern')):
                self.assertEqual(im.getpixel(xy),tuple(bytes.fromhex(p['garment_plan']['render_roles'][role][1:])))
        self.assertIn('clothing',{x['gradient']['region'] for x in result['variant_details'][0]['applied_gradients']})

    def test_single_garment_accepts_flat_fill_with_fine_structure_lines(self):
        path=self.master(pattern=False,inner=False)
        selected=next(x for x in source_colorways.eligible_colorways() if not garment_plan.plan_for(x['source_hd_id'])['gradients'])
        result=renderer.render_variants(path,[source_colorways.plan_for(selected['id'])],self.root/'flat',encoding=encoding.ENCODING_ID)
        self.assertTrue(Path(result['delivery']).is_file())
        self.assertEqual(result['variant_details'][0]['applied_gradients'],
                         [] if selected['gradient'] is None else result['variant_details'][0]['applied_gradients'])

    def test_single_garment_with_source_clothing_gradient_is_valid(self):
        selected=next(x for x in source_colorways.eligible_colorways() if garment_plan.plan_for(x['source_hd_id'])['gradients'])
        result=renderer.render_variants(self.master(pattern=False,inner=False),[source_colorways.plan_for(selected['id'])],self.root/'single-gradient',encoding=encoding.ENCODING_ID)
        self.assertTrue(result['variant_details'][0]['gradient_visibility']['qualifies_as_required'])

    def test_foreign_garment_palette_tampering_is_rejected(self):
        p=source_colorways.plan_for(1);p['garment_plan']=garment_plan.plan_for(69)
        with self.assertRaisesRegex(ValueError,'服饰配色或来源'):
            renderer.render_variants(self.master(),[p],self.root/'bad',encoding=encoding.ENCODING_ID)

    def test_legacy_plan_enrichment_keeps_source_and_original_roles(self):
        p=source_colorways.plan_for(25);old=deepcopy(p);old.pop('garment_plan')
        new=source_colorways.upgrade_gradient_plan(old)
        self.assertEqual(new['source_hd_id'],25);self.assertEqual(new['roles'],p['roles'])
        self.assertEqual(new['garment_plan'],p['garment_plan'])

    def test_bottom_corners_accept_only_connected_garments_and_top_stays_strict(self):
        path=self.master();im=Image.open(path);d=ImageDraw.Draw(im)
        d.rectangle((0,220,255,255),fill='#00FFFF');d.rectangle((100,220,154,255),fill='#FF8000');im.save(path)
        result=renderer.render_variants(path,[source_colorways.plan_for(1)],self.root/'flush',encoding=encoding.ENCODING_ID)
        self.assertEqual(result['geometry_lock']['bottom_alignment']['bottom_gap_pixels'],0)
        for xy in ((0,0),(0,255)):
            bad=im.copy();bad.putpixel(xy,(0,0,255));bad.save(path)
            with self.assertRaises(ValueError):renderer._decode_garments(path)

    def test_no_extra_api_or_history_draws_in_local_rendering(self):
        from unittest.mock import patch
        with patch('subprocess.run',side_effect=AssertionError('No subprocess or gateway')), \
             patch('colorway_selection.draw_colorway_ids',side_effect=AssertionError('No palette draw')):
            renderer.render_variants(self.master(),[source_colorways.plan_for(1)],self.root/'local',encoding=encoding.ENCODING_ID)

    def test_outline_only_corner_must_connect_to_a_real_bottom_garment(self):
        path=self.master();original=Image.open(path).copy()
        good=original.copy();ImageDraw.Draw(good).line((0,254,30,254),fill='black',width=2);good.save(path)
        renderer._decode_garments(path)
        bad=original.copy();ImageDraw.Draw(bad).line((0,254,2,254),fill='black',width=2);bad.save(path)
        with self.assertRaisesRegex(ValueError,'底角并非连续衣片'):
            renderer._decode_garments(path)

    def test_cli_request_uses_its_garment_encoding(self):
        from contextlib import redirect_stdout
        from io import StringIO
        p=source_colorways.plan_for(1)
        path=self.root/'request.json'
        path.write_text(json.dumps({'variant_plans':[p],'master_encoding':encoding.ENCODING_ID}))
        output=StringIO()
        with redirect_stdout(output):
            renderer.main(['--master',str(self.master()),'--request',str(path),'--out-dir',str(self.root/'cli')])
        result=json.loads(output.getvalue())
        self.assertEqual(result['variant_details'][0]['garment_encoding'],encoding.ENCODING_ID)
        self.assertEqual(result['variant_details'][0]['garment_plan'],p['garment_plan'])

    def test_selected_hd_variant_freezes_same_garment_plan_without_redraw(self):
        from unittest.mock import patch
        from variant_plans import select_variant_plan
        plans=[source_colorways.plan_for(hd) for hd in (1,9,14,29)]
        for index,plan in enumerate(plans,1):plan['variant_index']=index
        with patch('colorway_selection.draw_colorway_ids',side_effect=AssertionError('No new palette draw')):
            selected=select_variant_plan({'variants':4,'variant_plans':plans},3)
            self.assertEqual(selected['garment_plan'],plans[2]['garment_plan'])
            self.assertEqual(selected['source_colorway_id'],plans[2]['id'])
            selected['garment_plan']['notes']='changed copy'
            self.assertNotEqual(selected['garment_plan'],plans[2]['garment_plan'])

if __name__=='__main__':unittest.main()
