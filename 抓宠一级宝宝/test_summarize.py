import gzip
import json
import tempfile
import unittest
from pathlib import Path

from summarize import summarize


class SummaryTests(unittest.TestCase):
    def test_dedup_respects_restart_and_capture_evidence(self):
        tiger = {'slot': 2, 'type': 1, 'name': '魔力布老虎', 'level': 1, 'hp': 20, 'hp_max': 20}
        normal = {'slot': 1, 'type': 1, 'name': '熊', 'level': 62, 'hp': 100, 'hp_max': 100}
        data = [
            {'event': 'started', 'time': 'a'},
            {'event': 'battle_start', 'time': 'b', 'battle': 1},
            {'event': 'roster', 'time': 'c', 'battle': 1, 'enemies': [normal, tiger]},
            {'event': 'roster', 'time': 'd', 'battle': 1, 'enemies': [normal, tiger]},
            {'event': 'bait_use', 'time': 'e', 'battle': 1, 'target': tiger,
             'item_id': 8713, 'slot': 4, 'quantity_before': 5},
            {'event': 'target_missing', 'time': 'f', 'battle': 1, 'target': tiger},
            {'event': 'battle_end', 'time': 'g', 'battle': 1, 'bait': [[8713, 4, 4]], 'pet_items': [[8, 1]]},
            {'event': 'started', 'time': 'h'},
            {'event': 'battle_start', 'time': 'i', 'battle': 1},
            {'event': 'roster', 'time': 'j', 'battle': 1, 'enemies': [normal]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl.gz'
            with gzip.open(path, 'wt', encoding='utf-8') as f:
                for row in data:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            result = summarize(path, '魔力布老虎')
        self.assertEqual((result['battles'], result['enemy_count'], result['target_count']), (2, 3, 1))
        self.assertEqual(len(result['possible_captures']), 1)
        self.assertEqual(result['possible_captures'][0]['pet_items'], [[8, 1]])

    def test_no_disappearance_or_no_observed_decrease_is_not_capture(self):
        tiger = {'slot': 2, 'type': 1, 'name': '魔力布老虎', 'level': 1}
        data = [
            {'event': 'started', 'time': 'a'},
            {'event': 'battle_start', 'battle': 1, 'time': 'b'},
            {'event': 'roster', 'battle': 1, 'time': 'c', 'enemies': [tiger]},
            {'event': 'bait_use', 'battle': 1, 'time': 'd', 'target': tiger,
             'item_id': 8713, 'slot': 4, 'quantity_before': 5},
            {'event': 'battle_end', 'battle': 1, 'time': 'e', 'bait': [[8713, 4, 5]]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in data), encoding='utf-8')
            result = summarize(path, '魔力布老虎')
        self.assertEqual(result['possible_captures'], [])


if __name__ == '__main__':
    unittest.main()
