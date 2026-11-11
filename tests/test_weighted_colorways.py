"""Durable palette cycles and adjacent-batch exclusions; no image requests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
from avatar_test_fixture import isolate_colorway_history
import colorway_selection as selection
import source_colorways


class WeightedColorwayTests(unittest.TestCase):
    def setUp(self):
        isolate_colorway_history(self)
        self.references = sorted(item['source_hd_id'] for item in source_colorways.eligible_colorways())

    def draw(self, count=4):
        return selection.draw_colorway_ids(self.references, count)

    def test_all_70_are_available_and_adjacent_quad_batches_have_no_shared_source(self):
        self.assertEqual(len(self.references),70)
        previous = set()
        by_round = {}
        for _ in range(350):
            ids, meta = self.draw()
            self.assertEqual(len(set(ids)),4)
            self.assertFalse(set(ids) & previous)
            self.assertEqual(set(meta['excluded_previous_source_hd_ids']),previous)
            self.assertEqual(meta['eligible_count'],70)
            self.assertTrue(meta['no_replacement'])
            for record in meta['cycle_draws']:
                used = by_round.setdefault(record['round'],set())
                self.assertNotIn(record['source_hd_id'],used)
                used.add(record['source_hd_id'])
            previous = set(ids)
        for number, used in by_round.items():
            if number != max(by_round):
                self.assertEqual(used,set(self.references))

    def test_70_tail_is_used_without_repeating_previous_or_current_batch_at_rollover(self):
        before = set()
        previous = set()
        for _ in range(17):
            ids,meta = self.draw()
            before.update(ids)
            previous = set(ids)
        self.assertEqual(len(before),68)
        ids,meta = self.draw()
        self.assertTrue(meta['cycle_reset'])
        self.assertFalse(set(ids)&previous)
        self.assertEqual({r['source_hd_id'] for r in meta['cycle_draws'] if r['round']==1},set(self.references)-before)
        self.assertEqual([r['round'] for r in meta['cycle_draws']],[1,1,2,2])
        self.assertEqual(len(set(ids)),4)

    def test_single_and_quad_share_a_cycle_and_immediate_exclusion(self):
        batches=[self.draw(count) for count in (4,1,4,1,4)]
        flat=[value for ids,_ in batches for value in ids]
        self.assertEqual(len(flat),len(set(flat)))
        for (first,_),(second,_) in zip(batches,batches[1:]):
            self.assertFalse(set(first)&set(second))

    def test_concurrent_reservations_consume_64_distinct_sources_before_rollover(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            batches=list(pool.map(lambda _:self.draw()[0],range(16)))
        flat=[value for batch in batches for value in batch]
        self.assertEqual(len(flat),64)
        self.assertEqual(len(set(flat)),64)

    def test_orange_green_weight_changes_order_without_removing_any_source(self):
        weights=selection._weights(self.references,{},[])
        self.assertEqual(set(weights),set(map(str,self.references)))
        for color in ('#A1E5D2','#FF8347','#DF8852','#FF7D61','#00DDD6'):
            self.assertEqual(selection.background_preference(color)['base_weight'],.35)
        self.assertTrue(all(x['effective_weight']>0 for x in weights.values()))
        self.assertEqual(selection.background_preference('#9FA5F0')['base_weight'],1)

    def test_v1_v2_history_preserves_last_batch_and_usage_on_upgrade(self):
        previous=[16,8,3,43]
        for version in (1,2):
            old={'schema_version':version,'usage':{'16':7},'batches':[[25],previous]}
            if version==2:old['cycles']={'4':{'round':2,'seen':[previous]}}
            upgraded=selection._upgrade_state(deepcopy(old))
            self.assertEqual(upgraded['schema_version'],3)
            self.assertEqual(upgraded['usage'],old['usage'])
            self.assertEqual(upgraded['batches'],old['batches'])
            ids,_,_,_,excluded=selection._choose(self.references,upgraded['usage'],upgraded['batches'],4,random.Random(1),upgraded['palette_cycle'])
            self.assertFalse(set(ids)&set(previous))
            self.assertEqual(set(excluded),set(previous))

    def test_persistent_v2_migration_is_atomic_and_cannot_forget_latest_four(self):
        path=selection.history_path()
        previous=[16,8,3,43]
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE selection_state (id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('INSERT INTO selection_state VALUES (1,?)',(json.dumps({'schema_version':2,'usage':{'16':4},'batches':[previous],'cycles':{'4':{'round':1,'seen':[previous]}}}),))
        ids,_=self.draw()
        self.assertFalse(set(ids)&set(previous))
        with sqlite3.connect(path) as db:
            state=json.loads(db.execute('SELECT data FROM selection_state').fetchone()[0])
        self.assertEqual(state['schema_version'],3)
        self.assertEqual(state['usage']['16'],4)
        self.assertEqual(set(state['palette_cycle']['used']),set(previous+ids))

    def test_default_history_is_durable_and_does_not_import_prior_library(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            old=base/'codex/state/tanshui-touxiang-skill/colorway-history.sqlite3'
            old.parent.mkdir(parents=True)
            previous=[16,8,3,43]
            with sqlite3.connect(old) as db:
                db.execute('CREATE TABLE selection_state(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
                db.execute('INSERT INTO selection_state VALUES(1,?)',(json.dumps({'schema_version':1,'usage':{},'batches':[previous]}),))
            with mock.patch.dict('os.environ',{'CODEX_HOME':str(base/'codex')}):
                prior=os.environ.pop('TANSHUI_AVATAR_COLOR_HISTORY',None)
                try:
                    path=selection.history_path()
                    self.assertEqual(path,base/'codex/state/tanshui-touxiang-skill/template70-colorway-history.sqlite3')
                    with sqlite3.connect(path) as db:
                        db.execute('CREATE TABLE selection_state(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
                        state=selection._load_state(db,path)
                    self.assertEqual(state['batches'],[])
                    self.assertEqual(state['palette_cycle']['used'],[])
                finally:
                    if prior is not None:os.environ['TANSHUI_AVATAR_COLOR_HISTORY']=prior

    def test_cycle_ledger_survives_recent_64_batch_truncation(self):
        for _ in range(66):self.draw(1)
        with sqlite3.connect(selection.history_path()) as db:
            state=json.loads(db.execute('SELECT data FROM selection_state').fetchone()[0])
        self.assertEqual(len(state['batches']),64)
        self.assertEqual(len(state['palette_cycle']['used']),66)
        tail=[self.draw(1)[0][0] for _ in range(4)]
        self.assertEqual(len(set(tail)),4)
        self.assertEqual(self.draw(1)[1]['cycle_round'],2)

    def test_insufficient_disjoint_sources_stop_without_consuming_history(self):
        first,_=selection.draw_colorway_ids(self.references[:4],4)
        before=selection.history_path().read_bytes()
        with self.assertRaisesRegex(ValueError,'无法与上次不同'):
            selection.draw_colorway_ids(self.references[:4],4)
        self.assertEqual(selection.history_path().read_bytes(),before)

    def test_random_history_cannot_change_source_roles(self):
        ids,meta=self.draw()
        self.assertEqual(meta['policy_id'],selection.SELECTION_POLICY_ID)
        for value in ids:
            plan=source_colorways.plan_for(value)
            self.assertEqual(plan['roles'],source_colorways.colorway(value)['roles'])
            source_colorways.validate_plan(plan)

if __name__=='__main__':unittest.main()
