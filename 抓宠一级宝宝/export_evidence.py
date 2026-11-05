"""从本机实验目录导出仅含战斗研究字段的冻结证据；不会导出原始网络流。"""
import argparse
import gzip
import json
from pathlib import Path

ROLES = ('伏地魔1', '伏地魔2', '伏地魔3', '伏地魔4', '伏地魔', '欧皇')
ALLOWED = {'event', 'time', 'epoch', 'battle', 'battle_no', 'role', 'target', 'candidates', 'enemies', 'fighters',
           'attempt', 'attempts', 'item_id', 'item_slot', 'slot', 'quantity_before', 'before', 'after', 'after_quantity',
           'consumed', 'bait', 'bait_items', 'pet_items', 'sp', 'before_quantity', 'result', 'native_return',
           'elapsed', 'elapsed_seconds', 'duration', 'defences', 'escape_sent', 'held_60', 'count', 'number',
           'reason', 'map_id', 'x', 'y', 'points', 'policy', 'tries', 'battle_start', 'battle_end'}
FIGHTER = {'slot', 'type', 'name', 'level', 'hp', 'hp_max', 'dead'}
EVENTS = {'started', 'monitor_start', 'battle_start', 'roster', 'roster_change', 'battle_end', 'target_locked',
          'bait_use', 'target_missing', 'target_gone_continue', 'target_battle_finished', 'bait_exhausted',
          'escape_sent', 'escape_retry', 'escape_wait', 'defend', 'defend_sent', 'sp_change', 'state',
          'simulated_target', 'simulated_capture_sent', 'single_capture_request_sent', 'native_item_call',
          'capture_request_sent', 'capture_request_observed', 'battle_ended', 'battle_ended_after_escape',
          'guard_stop', 'fatal', 'stopped', 'complete', 'attempt_limit_pause', 'target_missing_timeout'}


def clean_event(event):
    if event.get('event') not in EVENTS:
        return None
    out = {k: v for k, v in event.items() if k in ALLOWED}
    for key in ('fighters', 'enemies', 'candidates'):
        if key in out:
            out[key] = [{k: v for k, v in x.items() if k in FIGHTER} for x in out[key]]
    if isinstance(out.get('target'), dict):
        out['target'] = {k: v for k, v in out['target'].items() if k in FIGHTER}
    return out


def export(source, dest):
    count = 0
    with source.open('rb') as f, gzip.open(dest, 'wt', encoding='utf-8', newline='\n') as out:
        limit = source.stat().st_size
        while f.tell() < limit:
            raw = f.readline()
            if not raw or not raw.endswith(b'\n') or f.tell() > limit:
                break
            try:
                row = clean_event(json.loads(raw))
            except (ValueError, UnicodeDecodeError):
                continue
            if row is not None:
                out.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                count += 1
    print(f'{source.name} -> {dest.name}: {count} 条')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='tiger_item_probe_20261104 目录')
    parser.add_argument('--history', type=Path, required=True, help='vold2_encounter_3min_20261103 目录')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for prefix in ('six_tiger_', 'six_wise_'):
        for role in ROLES:
            name = prefix + role + '.jsonl'
            export(args.source / name, args.out / (name + '.gz'))
    for name in ('manual_defend_watch.jsonl', 'patrol_defend_60.jsonl', 'patrol_defend_7.jsonl',
                 'patrol_escape_10.jsonl', 'patrol_contract_10.jsonl', 'patrol_bait_five.jsonl',
                 'single_capture_once.log', 'patrol_capture.log', 'tiger_伏地魔1.jsonl', 'tiger_伏地魔3.jsonl',
                 'live_baby_30min.jsonl', 'live_baby_until_empty.jsonl'):
        source = args.source / name
        if source.exists():
            export(source, args.out / (name + '.gz'))
    export(args.history / 'long_events.jsonl', args.out / 'historical_long_events.jsonl.gz')


if __name__ == '__main__':
    main()
