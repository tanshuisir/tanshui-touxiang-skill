"""Whole-source palettes sampled without replacement, with durable batch exclusions."""
from colorsys import rgb_to_hsv
from contextlib import closing
from functools import lru_cache
import json
import os
from pathlib import Path
import random
import sqlite3
from uuid import uuid4


SELECTION_POLICY_ID = 'whole-library-no-replacement-v3'
RECENT_BATCHES = 3
RECENT_MULTIPLIER = 0.6


def history_path():
    override = os.environ.get('TANSHUI_AVATAR_COLOR_HISTORY')
    if override:
        return Path(override).expanduser().resolve()
    codex = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    return codex / 'state/tanshui-touxiang-skill/template70-colorway-history.sqlite3'


@lru_cache(maxsize=1)
def _backgrounds():
    catalog = Path(__file__).resolve().parents[1] / 'references/source-colorways.json'
    entries = json.loads(catalog.read_text(encoding='utf-8'))['colorways']
    return {item['source_hd_id']: item['roles']['background'] for item in entries}


def background_preference(color):
    """Classify existing backgrounds for selection only; never change a swatch."""
    rgb = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    hue, saturation, _ = rgb_to_hsv(*rgb)
    hue *= 360
    if saturation >= 0.12 and 5 <= hue < 50:
        return {'family': 'orange-coral', 'base_weight': 0.35}
    if saturation >= 0.12 and 65 <= hue <= 190:
        return {'family': 'green-teal', 'base_weight': 0.35}
    return {'family': 'other', 'base_weight': 1.0}


def _weights(references, usage, batches):
    recent = batches[-RECENT_BATCHES:]
    backgrounds = _backgrounds()
    details = {}
    for value in references:
        color = backgrounds.get(value)
        preference = background_preference(color) if color else {'family': 'other', 'base_weight': 1.0}
        hits = sum(value in batch for batch in recent)
        weight = preference['base_weight'] * RECENT_MULTIPLIER ** hits
        # A mild usage preference must never force equal frequency across hues.
        weight /= 1 + usage.get(str(value), 0) * 0.02
        details[str(value)] = dict(preference, background=color, recent_hits=hits,
                                   effective_weight=weight)
    return details


def _upgrade_state(state):
    if (not isinstance(state, dict) or state.get('schema_version') not in (1, 2, 3) or
            not isinstance(state.get('usage'), dict) or not isinstance(state.get('batches'), list) or
            any(type(value) is not int or value < 0 for value in state['usage'].values()) or
            any(not isinstance(batch, list) or len(batch) not in (1, 4) or
                any(type(value) is not int for value in batch) or len(set(batch)) != len(batch)
                for batch in state['batches'])):
        raise ValueError('随机配色历史格式无效；停止，不能静默恢复固定配色')
    if state['schema_version'] in (1, 2):
        # The old ledger tracked combinations, which cannot be interpreted as
        # a per-palette cycle. Start the new cycle with the last batch consumed;
        # preserve all usage totals and recent batches, including the latest.
        state = dict(state, schema_version=3, palette_cycle={
            'round': 1, 'used': list(state['batches'][-1]) if state['batches'] else [],
            'migrated_from': state['schema_version']})
        state.pop('cycles', None)
    cycle = state.get('palette_cycle')
    if (not isinstance(cycle, dict) or type(cycle.get('round')) is not int or cycle['round'] < 1 or
            not isinstance(cycle.get('used'), list) or
            any(type(value) is not int for value in cycle['used']) or
            len(set(cycle['used'])) != len(cycle['used'])):
        raise ValueError('随机配色历史格式无效：色板轮次损坏')
    return state


def _choose(references, usage, batches, count, rng, cycle):
    """Consume each source once per shared cycle; forbid the entire last batch.

    Single and quad draws share one ledger. A quad may cross a cycle boundary
    (70 is not divisible by 4); earlier picks in that same quad and every source
    in the previous batch remain excluded even after the cycle resets.
    """
    previous = set(batches[-1]) if batches else set()
    if len(set(references) - previous) < count:
        raise ValueError('候选色板不足，无法与上次不同且完全不重叠；停止，不放宽排除规则')
    weights = _weights(references, usage, batches)
    used = set(cycle['used']) & set(references)
    selected, segments = [], []
    reset = False
    for _ in range(count):
        if len(used) == len(references):
            used.clear()
            cycle['round'] += 1
            reset = True
        options = [value for value in references
                   if value not in used and value not in previous and value not in selected]
        if not options:
            raise ValueError('未用色板与上一版排除规则冲突；停止，不提前重复色板')
        value = rng.choices(options, weights=[weights[str(v)]['effective_weight'] for v in options], k=1)[0]
        selected.append(value)
        used.add(value)
        segments.append({'source_hd_id': value, 'round': cycle['round']})
    cycle['used'] = sorted(used)
    # Shuffle display positions only after recording the cycle in draw order.
    rng.shuffle(selected)
    return selected, reset, weights, segments, sorted(previous)


def _load_state(connection, path):
    row = connection.execute('SELECT data FROM selection_state WHERE id=1').fetchone()
    if row:
        return _upgrade_state(json.loads(row[0]))
    # This ledger belongs exclusively to TS-001..TS-070.
    # Do not import numeric reservations from any prior artwork library.
    return _upgrade_state({'schema_version': 1, 'usage': {}, 'batches': []})


def draw_colorway_ids(references, count):
    """Reserve once before submission; frozen briefs and HD do not call this."""
    references = sorted(references)
    if (type(count) is not int or count not in (1, 4) or any(type(value) is not int for value in references) or
            len(set(references)) != len(references) or len(references) < count):
        raise ValueError('完整模板配色目录不足四套或单套合规方案，不能跨图混色补足')
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(str(path), timeout=5)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS selection_state (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
            state = _load_state(connection, path)
            cycle = state['palette_cycle']
            selected, reset, weights, segments, excluded = _choose(
                references, state['usage'], state['batches'], count, random.SystemRandom(), cycle)
            for value in selected:
                state['usage'][str(value)] = state['usage'].get(str(value), 0) + 1
            state['batches'] = (state['batches'] + [selected])[-64:]
            connection.execute('INSERT OR REPLACE INTO selection_state (id,data) VALUES (1,?)',
                               (json.dumps(state, separators=(',', ':')),))
            connection.commit()
    except sqlite3.Error as error:
        raise ValueError('无法读写随机配色历史；停止，不回退固定色板：' + str(error)) from error
    return selected, {'policy_id': SELECTION_POLICY_ID, 'mode': 'random',
                      'draw_id': uuid4().hex, 'eligible_count': len(references),
                      'source_hd_ids': selected, 'history_file': str(path),
                      'cycle_round': cycle['round'], 'cycle_reset': reset,
                      'cycle_draws': segments, 'excluded_previous_source_hd_ids': excluded,
                      'no_replacement': True, 'cycle_used_count': len(cycle['used']),
                      'background_weights': weights, 'recent_batch_window': RECENT_BATCHES,
                      'recent_multiplier': RECENT_MULTIPLIER}
