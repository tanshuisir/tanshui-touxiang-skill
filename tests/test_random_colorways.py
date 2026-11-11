"""Real palette diversity, persistent history and frozen HD without API calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from avatar_test_fixture import isolate_colorway_history
import colorway_selection
import source_colorways
import variant_plans
import run_avatar


class RandomColorwayTests(unittest.TestCase):
    def setUp(self):
        isolate_colorway_history(self)
        self.references = [item['source_hd_id'] for item in source_colorways.eligible_colorways()]

    def draw(self, count):
        return colorway_selection.draw_colorway_ids(self.references, count)[0]

    def test_single_draws_cover_the_entire_eligible_library_without_duplicates(self):
        first = [self.draw(1)[0] for _ in self.references]
        self.assertEqual(set(first), set(self.references))
        self.assertEqual(len(first), len(set(first)))
        next_round = [self.draw(1)[0] for _ in self.references]
        self.assertNotEqual(first[-1], next_round[0])
        self.assertEqual(set(next_round), set(self.references))

    def test_twenty_quad_draws_use_library_palettes_and_do_not_repeat_recent_sets(self):
        batches = [self.draw(4) for _ in range(20)]
        # Weighted random groups need not cover every candidate in just 20 draws.
        self.assertTrue(set().union(*map(set, batches)).issubset(self.references))
        for index, batch in enumerate(batches):
            self.assertEqual(len(set(batch)), 4)
            self.assertTrue(set(batch).issubset(self.references))
            previous = {tuple(sorted(value)) for value in batches[max(0, index - 16):index]}
            self.assertNotIn(tuple(sorted(batch)), previous)
        self.assertGreater(len({tuple(sorted(batch)) for batch in batches}), 2)

    def test_history_survives_separate_python_processes(self):
        probe = ('import json,sys; sys.path.insert(0,sys.argv[1]); '
                 'from colorway_selection import draw_colorway_ids; '
                 'print(json.dumps(draw_colorway_ids(json.loads(sys.argv[2]),1)[0]))')
        draws = []
        for _ in self.references:
            result = subprocess.run([sys.executable, '-B', '-c', probe, str(SKILL/'scripts'),
                                     json.dumps(self.references)], check=True, capture_output=True, text=True)
            draws.extend(json.loads(result.stdout))
        self.assertEqual(set(draws), set(self.references))
        self.assertEqual(len(draws), len(set(draws)))

    def test_simultaneous_requests_reserve_distinct_unused_single_palettes(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            selections = list(pool.map(lambda _: self.draw(1)[0], self.references))
        self.assertEqual(len(set(selections)), len(self.references))

    def test_hd_and_explicit_colorways_never_consume_random_history(self):
        plans = variant_plans.make_variant_plans({}, None, {'id':25}, 'finished', 'expressive', None)
        before = colorway_selection.history_path().read_bytes()
        with mock.patch('variant_plans.draw_colorway_ids', side_effect=AssertionError('Frozen HD must not draw')), \
                mock.patch('source_colorways.draw_colorway_ids', side_effect=AssertionError('Explicit must not draw')):
            frozen = variant_plans.make_variant_plans({'variant_plans':plans}, None, {'id':25}, 'finished', 'expressive', None)
            self.assertEqual(frozen, plans)
            selected = variant_plans.select_variant_plan({'variant_plans':plans}, 3)
            single = source_colorways.single_plan_for(selected, 25)
            self.assertEqual(single['roles'], plans[2]['roles'])
            self.assertEqual(single['gradient'], plans[2]['gradient'])
            self.assertEqual(source_colorways.single_plan_for({'colorway_reference_id':55})['source_hd_id'],55)
        self.assertEqual(colorway_selection.history_path().read_bytes(), before)

    def test_style_reference_25_cannot_pin_new_single_palettes(self):
        plans = [source_colorways.single_plan_for({}, 25) for _ in self.references]
        self.assertEqual({plan['source_hd_id'] for plan in plans}, set(self.references))
        for plan in plans:
            source_colorways.validate_plan(plan)
            self.assertEqual(plan['roles'],source_colorways.colorway(plan['source_hd_id'])['roles'])

    def test_auto_is_random_but_reference_is_an_explicit_whole_source(self):
        draws = [source_colorways.requested_colorway('auto',25)['source_hd_id'] for _ in self.references]
        self.assertEqual(set(draws), set(self.references))
        self.assertEqual(source_colorways.requested_colorway('reference',25)['source_hd_id'],25)
        with self.assertRaises(ValueError):
            source_colorways.requested_colorway('reference',71)

    def test_a_shrinking_library_cannot_relax_previous_batch_exclusion(self):
        first = self.draw(4)
        remaining = first + [value for value in self.references if value not in first][:1]
        with self.assertRaisesRegex(ValueError, '无法与上次不同'):
            colorway_selection.draw_colorway_ids(remaining,4)

    def test_corrupt_history_stops_without_a_fixed_palette_fallback(self):
        self.draw(1)
        with sqlite3.connect(str(colorway_selection.history_path())) as connection:
            connection.execute('UPDATE selection_state SET data=? WHERE id=1', ('{}',))
        with self.assertRaisesRegex(ValueError,'历史格式'):
            self.draw(1)

    def test_a_single_available_batch_cannot_pretend_to_be_new_by_reordering(self):
        references = self.references[:4]
        colorway_selection.draw_colorway_ids(references,4)
        with self.assertRaisesRegex(ValueError,'无法与上次不同'):
            colorway_selection.draw_colorway_ids(references,4)

    def test_explicit_random_switch_clears_old_selection_but_keeps_person_and_style(self):
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / 'photo.png'
            photo.touch()
            plans = variant_plans.make_variant_plans({}, None, {'id':25}, 'finished', 'expressive', None)
            saved = {'photo':str(photo),'identity_source':'photo', 'variants':4,
                     'variant_plans':plans,'source_colorway_id':plans[0]['id'],
                     'art_palette':plans[0]['id'], 'line_reference_id':plans[0]['source_hd_id'],
                     'skin_template_id':plans[0]['source_selection']['skin']['template_id'],
                     'color_roles':plans[0]['roles'], 'gradient':plans[0]['gradient'],
                     'user_notes':'保留眼镜', 'hd_reference_id':25}
            brief_file = Path(directory) / 'brief.json'
            brief_file.write_text(json.dumps(saved))
            with mock.patch.object(run_avatar, 'run', return_value={'status':'completed'}) as runner:
                self.assertEqual(run_avatar.main(['--brief',str(brief_file),'--random-colors']),0)
            received = runner.call_args[0][0]
            for field in ('variant_plans','source_colorway_id','art_palette','line_reference_id','color_roles','gradient'):
                self.assertNotIn(field,received)
            self.assertEqual(received['photo'],str(photo.resolve()))
            self.assertEqual(received['user_notes'],'保留眼镜')
            self.assertEqual(received['hd_reference_id'],25)


if __name__ == '__main__':
    unittest.main()
