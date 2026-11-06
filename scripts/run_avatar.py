#!/usr/bin/env python3
"""Prepare one avatar edit, run gen-img once, and deliver a square PNG."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from uuid import uuid4

import build_prompt
import finalize_avatar


SKILL = Path(__file__).resolve().parents[1]
INSTALLED_SKILL = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser() / 'skills/tanshui-touxiang-skill'


def _inside(path, directory):
    return path == directory or directory in path.parents


def _write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def _seconds(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and value >= 0:
            return float(value)
    return None


def _finish(result, out_dir, started):
    result['timings']['total_seconds'] = monotonic() - started
    result['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    result['timings'] = {
        key: round(value, 6) if value is not None else None
        for key, value in result['timings'].items()
    }
    result['result_file'] = str(out_dir / 'result.json')
    _write_json(out_dir / 'result.json', result)
    summary = {key: result[key] for key in
               ('status', 'upstream_status', 'result_file', 'timing_scope', 'timings')}
    for key in ('stage', 'delivery', 'delivery_size', 'awaiting_hd_confirmation', 'size_notice', 'error_code', 'error'):
        if key in result:
            summary[key] = result[key]
    # The gateway streams its own progress. Do not repeat its argv, prompt,
    # response body, or environment in this runner's concise summary.
    print(json.dumps(summary, ensure_ascii=False, separators=(',', ':')), flush=True)
    return result


def run(brief, out_dir, gateway_runner=None):
    """Run at most one gateway process; a failed/unknown request is never retried.

    gateway_runner is an injectable subprocess.run-compatible callable for
    offline tests. Upstream result.json remains the source of API state.
    Timings start inside this script; prelaunch tool/approval waits are excluded.
    """
    started = monotonic()
    cwd = Path.cwd().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    for directory in (SKILL, INSTALLED_SKILL.resolve()):
        if _inside(cwd, directory) or _inside(out_dir, directory):
            raise ValueError('请从项目工作区运行，并将输出保存在 Skill 安装目录之外')
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ValueError('输出目录已有文件，请选择新目录以保留此前结果')
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        'status': 'failed', 'upstream_status': 'not_started',
        'started_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'upstream_result': str(out_dir / 'render' / 'result.json'),
        'visual_review': 'not_performed',
        'timing_scope': 'script execution only; excludes prelaunch tool and approval waits',
        'timings': {
            'preparation_seconds': 0.0, 'gateway_process_seconds': 0.0,
            'delivery_seconds': 0.0, 'total_seconds': 0.0,
            'upstream_api_seconds': None, 'gateway_overhead_seconds': None,
        },
    }
    preparation_started = monotonic()
    try:
        if not isinstance(brief, dict):
            raise ValueError('brief 必须为 JSON 对象')
        prepared_brief = dict(brief)
        photo = Path(prepared_brief['photo']).expanduser()
        prepared_brief['photo'] = str(photo.resolve())
        if prepared_brief.get('approved_preview') is not None:
            preview = Path(prepared_brief['approved_preview']).expanduser()
            prepared_brief['approved_preview'] = str(preview.resolve())
        prepared_brief.setdefault('workflow', 'fast')
        prepared_brief.setdefault('stage', 'preview')
        brief_path = out_dir / 'brief.json'
        request = build_prompt.prepare(prepared_brief, brief_path, out_dir / 'request')
        # Freeze the locally chosen palette before saving a reusable brief.
        # A later confirmed HD request must not choose a new random palette.
        prepared_brief['art_palette'] = request['color_plan']['id']
        prepared_brief['color_roles'] = dict(request['color_plan']['roles'])
        prepared_brief['gradient'] = dict(request['color_plan']['gradient'])
        _write_json(brief_path, prepared_brief)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(error_code='preparation_failed', error=str(error))
        request = None
    result['timings']['preparation_seconds'] = monotonic() - preparation_started
    if request is None:
        return _finish(result, out_dir, started)
    result.update(stage=request['stage'], requested_render_size=request['render_size'],
                  requested_quality=request['quality'])

    argv = list(request['argv']) + ['--out-dir', str(out_dir / 'render')]
    gateway_started = monotonic()
    process_error = False
    try:
        # Inherit stdout/stderr so gateway progress is visible immediately.
        process = (gateway_runner or subprocess.run)(argv, cwd=str(cwd), check=False)
        result['gateway_returncode'] = process.returncode
    except (OSError, subprocess.SubprocessError):
        process_error = True
        result['gateway_returncode'] = None
    result['timings']['gateway_process_seconds'] = monotonic() - gateway_started

    upstream_path = out_dir / 'render' / 'result.json'
    try:
        upstream = json.loads(upstream_path.read_text(encoding='utf-8'))
        if not isinstance(upstream, dict):
            raise ValueError('invalid upstream result')
    except FileNotFoundError:
        result.update(upstream_status='unknown', error_code='upstream_result_missing')
        return _finish(result, out_dir, started)
    except (OSError, ValueError):
        result.update(upstream_status='unknown', error_code='upstream_result_invalid')
        return _finish(result, out_dir, started)

    status = upstream.get('status')
    result['upstream_status'] = status if isinstance(status, str) else 'unknown'
    for source_key, destination_key in (
        ('model', 'model'), ('request_id', 'request_id'), ('started_at', 'upstream_started_at'),
    ):
        if source_key in upstream:
            result[destination_key] = upstream[source_key]
    api_seconds = _seconds(upstream.get('api_seconds'))
    result['timings']['upstream_api_seconds'] = api_seconds
    if api_seconds is not None:
        result['timings']['gateway_overhead_seconds'] = max(
            0.0, result['timings']['gateway_process_seconds'] - api_seconds)
    # api_seconds is the upstream client's API interval. Its headers/body
    # intervals must not be presented as isolated image-download time.
    if process_error or result['gateway_returncode'] != 0:
        result['error_code'] = 'gateway_process_failed'
        return _finish(result, out_dir, started)
    if status != 'completed':
        result['error_code'] = 'upstream_not_completed'
        return _finish(result, out_dir, started)

    files = upstream.get('files')
    if not isinstance(files, list) or not files or not isinstance(files[0], dict):
        result['error_code'] = 'upstream_image_missing'
        return _finish(result, out_dir, started)
    original = files[0].get('original')
    if not isinstance(original, str) or not original:
        result['error_code'] = 'upstream_image_missing'
        return _finish(result, out_dir, started)
    source = Path(original).expanduser()
    if not source.is_absolute():
        source = upstream_path.parent / source
    result['original'] = str(source.resolve())
    delivery_started = monotonic()
    try:
        size = int(request['delivery_size'].split('x')[0])
        delivered = finalize_avatar.finalize(source, out_dir / 'avatar.png', size=size)
        result.update(status='completed', delivery=delivered['delivery'],
                      delivery_size=delivered['delivery_size'],
                      original_preserved=delivered['original_preserved'],
                      delivery_details=delivered)
        expected_size = [int(v) for v in request['render_size'].split('x')]
        result['render_size_honored'] = delivered['original_size'] == expected_size
        result['awaiting_hd_confirmation'] = request['stage'] == 'preview'
        if request['stage'] == 'preview' and not result['render_size_honored']:
            result['size_notice'] = ('上游返回尺寸未匹配小尺寸请求；已整理为预览，'
                                     '不能据此声称已节省生图资源。')
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(error_code='delivery_failed', error=str(error))
    result['timings']['delivery_seconds'] = monotonic() - delivery_started
    return _finish(result, out_dir, started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--brief', type=Path, help='Existing brief JSON; relative photo paths use its directory')
    source.add_argument('--photo', type=Path)
    parser.add_argument('--feature', action='append', help='Visible identity feature; repeat at least three times')
    parser.add_argument('--expression')
    parser.add_argument('--pose')
    parser.add_argument('--clothing')
    parser.add_argument('--stylization')
    parser.add_argument('--notes')
    parser.add_argument('--reference', type=int, help='HD reference; default 25')
    parser.add_argument('--mode', choices=['auto'] + list(build_prompt.MODES),
                        help='Default flat with --photo; auto for an existing brief without mode')
    parser.add_argument('--color-mode', choices=['natural', 'expressive'], help='Default expressive; natural only when explicitly requested')
    parser.add_argument('--palette', help='Art palette id, auto (default), or reference')
    parser.add_argument('--model', help='Optional; passed to global gen-img for model filtering')
    parser.add_argument('--stage', choices=['preview', 'final'],
                        help='Default preview; final only after user confirmation or an explicit HD request')
    parser.add_argument('--approved-preview', type=Path, help='Approved preview as the third image for final rendering')
    parser.add_argument('--quality', help='Default low for preview, high for final; explicit values are preserved')
    parser.add_argument('--out-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.brief:
            brief_path = args.brief.expanduser().resolve()
            brief = json.loads(brief_path.read_text(encoding='utf-8'))
            if not isinstance(brief, dict):
                raise ValueError('brief 必须为 JSON 对象')
            photo = Path(brief['photo']).expanduser()
            if not photo.is_absolute():
                photo = brief_path.parent / photo
            brief['photo'] = str(photo.resolve())
            if brief.get('approved_preview') is not None:
                preview = Path(brief['approved_preview']).expanduser()
                if not preview.is_absolute():
                    preview = brief_path.parent / preview
                brief['approved_preview'] = str(preview.resolve())
        else:
            if not args.feature or len(args.feature) < 3 or not args.expression or not args.pose:
                parser.error('--photo 需要至少三个 --feature，以及 --expression 和 --pose')
            brief = {'photo': str(args.photo.expanduser().resolve()),
                     'identity_features': args.feature,
                     'expression': args.expression, 'pose': args.pose}
        for name, key in (
            ('feature', 'identity_features'), ('expression', 'expression'), ('pose', 'pose'),
            ('clothing', 'clothing'), ('stylization', 'stylization'), ('notes', 'user_notes'),
            ('reference', 'hd_reference_id'), ('mode', 'mode'), ('color_mode', 'color_mode'),
            ('palette', 'art_palette'),
            ('model', 'model'), ('quality', 'quality'),
            ('stage', 'stage'),
        ):
            value = getattr(args, name)
            if value is not None:
                brief[key] = value
        if args.approved_preview is not None:
            brief['approved_preview'] = str(args.approved_preview.expanduser().resolve())
        if 'palette_id' not in brief:
            brief.setdefault('hd_reference_id', 25)
        brief.setdefault('mode', 'auto' if args.brief else 'flat')
        brief.setdefault('color_mode', 'expressive')
        brief.setdefault('stage', 'preview')
        out_dir = args.out_dir or (
            Path.cwd() / 'outputs' / 'avatars' /
            (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]))
        result = run(brief, out_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Local validation errors are useful; do not echo the brief or environment.
        parser.exit(2, 'Error: ' + str(error) + '\n')
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
