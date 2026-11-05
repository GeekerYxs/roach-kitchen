"""汇总脱敏 JSONL 或 JSONL.gz：以运行批次、战斗号、敌方位置去重。"""
import argparse
import collections
import gzip
import json
from pathlib import Path


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def summarize(path, target):
    run = -1
    starts = {}
    units = {}
    target_units = {}
    attempts = collections.defaultdict(list)
    missing = set()
    ends = {}
    last = None
    for event in rows(path):
        last = event
        kind = event.get('event')
        if kind in ('started', 'monitor_start'):
            run += 1
        battle = event.get('battle', event.get('battle_no'))
        if battle is None:
            continue
        battle_key = (run, battle)
        if kind == 'battle_start':
            starts[battle_key] = event.get('time')
        if kind in ('roster', 'roster_change'):
            for fighter in event.get('enemies', event.get('fighters', [])):
                if fighter.get('type') != 1:
                    continue
                key = (run, battle, fighter.get('slot'))
                units.setdefault(key, fighter)
                if fighter.get('name') == target and fighter.get('level') == 1:
                    target_units.setdefault(key, {'time': event.get('time'), **fighter})
        if kind == 'bait_use' and isinstance(event.get('target'), dict):
            attempts[(run, battle, event['target'].get('slot'))].append(event)
        if kind in ('target_missing', 'target_gone_continue') and isinstance(event.get('target'), dict):
            missing.add((run, battle, event['target'].get('slot')))
        if kind == 'battle_end':
            ends[battle_key] = event
    candidates = []
    for key, uses in attempts.items():
        end = ends.get(key[:2])
        if not end or key not in missing:
            continue
        first = uses[0]
        # 多个堆叠时不能把一格的数量和全背包数量混在一起；格子变化时只报待核对。
        slot, before, item = first.get('slot'), first.get('quantity_before'), first.get('item_id')
        stack = next((x[2] for x in end.get('bait', []) if len(x) == 3 and x[0] == item and x[1] == slot), None)
        decreased = before is not None and stack is not None and stack < before
        if decreased:
            candidates.append({'run': key[0], 'battle': key[1], 'slot': key[2],
                               'attempts': len(uses), 'before': before, 'after': stack,
                               'pet_items': end.get('pet_items', []), 'time': first.get('time')})
    species = collections.Counter((f.get('name'), f.get('level'), f.get('hp_max'), f.get('type'))
                                  for f in units.values())
    return {'file': path.name, 'battles': len(starts), 'enemy_count': len(units),
            'target_count': len(target_units), 'targets': list(target_units.values()),
            'possible_captures': candidates,
            'species': [{'name': k[0], 'level': k[1], 'hp_max': k[2], 'type': k[3], 'count': v}
                        for k, v in species.most_common()],
            'last_event': last}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    print(json.dumps([summarize(p, args.target) for p in args.files], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
