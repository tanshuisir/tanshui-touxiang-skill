"""Bottom edge regressions using common semantic geometry, without model calls."""
from pathlib import Path
import sys,tempfile,unittest
from PIL import Image,ImageDraw
SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import recolor_avatar as renderer
import source_colorways
from avatar_test_fixture import encoded_fixture,isolate_colorway_history

class BottomAnchorTests(unittest.TestCase):
    def setUp(self):
        isolate_colorway_history(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def gapped_master(self,gap=20):
        source=self.root/'source.png';encoded_fixture(source,(256,256))
        with Image.open(source) as image:
            canvas=Image.new('RGB',(256,256),'#FFFFFF')
            canvas.paste(image.crop((0,gap,256,256)),(0,0))
        result=self.root/'gapped.png';canvas.save(result)
        return result

    def test_gap_moves_whole_subject_without_scale_or_role_edits(self):
        _,ids,alpha,_=renderer._decode(self.gapped_master())
        moved,ink,record=renderer._align_subject_to_bottom(ids,alpha)
        self.assertEqual(record['offset_xy'],[0,20])
        self.assertEqual(record['bottom_gap_pixels'],0)
        self.assertEqual(record['scale'],1)
        self.assertEqual(moved.crop((0,20,256,256)).tobytes(),ids.crop((0,0,256,236)).tobytes())
        self.assertEqual(ink.crop((0,20,256,256)).tobytes(),alpha.crop((0,0,256,236)).tobytes())
        self.assertEqual(moved.crop((0,0,256,20)).getextrema(),(7,7))

    def test_four_tiles_each_touch_their_own_bottom_and_share_geometry(self):
        master=self.gapped_master();before=master.read_bytes()
        plans=[source_colorways.plan_for(n) for n in (1,4,34,63)]
        result=renderer.render_variants(master,plans,self.root/'four')
        self.assertEqual(master.read_bytes(),before)
        self.assertEqual(result['geometry_lock']['bottom_alignment']['offset_xy'],[0,20])
        with Image.open(self.root/'four/role-ids.png') as roles:
            self.assertGreater(sum(roles.crop((0,255,256,256)).histogram()[:7]),26)
        for i,(plan,path) in enumerate(zip(plans,result['variants'])):
            with Image.open(path) as single,Image.open(result['delivery']) as grid:
                self.assertEqual(single.mode,'RGB')
                self.assertEqual(single.getpixel((128,255)),tuple(bytes.fromhex(plan['roles']['outline'][1:])))
                tile=grid.crop(((i%2)*256,(i//2)*256,(i%2+1)*256,(i//2+1)*256))
                self.assertEqual(tile.tobytes(),single.tobytes())
        self.assertEqual(len({(d['role_map_sha256'],d['line_alpha_sha256']) for d in result['variant_details']}),1)

    def test_already_anchored_artwork_is_unchanged_and_idempotent(self):
        path=self.root/'touching.png';encoded_fixture(path,(256,256))
        _,ids,alpha,_=renderer._decode(path)
        moved,ink,record=renderer._align_subject_to_bottom(ids,alpha)
        self.assertEqual(record['offset_xy'],[0,0])
        self.assertEqual(ids.tobytes(),moved.tobytes());self.assertEqual(alpha.tobytes(),ink.tobytes())
        again,_,record2=renderer._align_subject_to_bottom(moved,ink)
        self.assertEqual(record2['offset_xy'],[0,0]);self.assertEqual(again.tobytes(),moved.tobytes())

    def test_only_faint_trailing_ink_fringe_can_leave_canvas(self):
        ids=Image.new('L',(100,100),7);ink=Image.new('L',(100,100),0)
        ImageDraw.Draw(ids).rectangle((20,20,79,89),fill=3);ink.putpixel((50,92),20)
        result,alpha,record=renderer._align_subject_to_bottom(ids,ink)
        self.assertEqual(record['offset_xy'],[0,10]);self.assertEqual(result.getpixel((50,99)),3)
        self.assertEqual(alpha.getextrema(),(0,0))

    def test_excessive_gap_stops_without_guessing_extension(self):
        with self.assertRaisesRegex(ValueError,'12%'):
            renderer.render_variants(self.gapped_master(50),[source_colorways.plan_for(1)],self.root/'bad')
        self.assertFalse((self.root/'bad/avatar.png').exists())

    def test_hair_tip_or_tiny_marker_does_not_count_as_torso(self):
        for role in (6,3):
            ids=Image.new('L',(100,100),7);alpha=Image.new('L',(100,100),0)
            ImageDraw.Draw(ids).rectangle((20,40,79,89),fill=3);ids.putpixel((50,99),role)
            with self.assertRaisesRegex(ValueError,'连续衣服或身体'):
                renderer._align_subject_to_bottom(ids,alpha)

if __name__=='__main__':unittest.main()
