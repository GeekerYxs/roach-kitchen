"""从本机 tap 选取已记录的实验请求，只导出操作码和已识别字段。"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('tap', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()

with args.tap.open(encoding='utf-8') as src, args.output.open('w', encoding='utf-8', newline='\n') as out:
    for line in src:
        event = json.loads(line)
        if event.get('kind') != 'request':
            continue
        tick, op = event.get('tick'), event.get('opcode')
        group = None
        if op == 0x1003 and 261763218 <= tick <= 261772984:
            group = 'manual_item'
        elif op == 0x1003 and tick == 262508453:
            group = 'direct_replay_no_consumption'
        elif op == 0x1003 and tick == 263155296:
            group = 'native_function_item_consumed'
        elif op == 0x1004 and 265605734 <= tick <= 265631156:
            group = 'manual_defend'
        if group is None:
            continue
        body = bytes.fromhex(event['hex'])
        row = {'group': group, 'tick_ms': tick, 'opcode': f'0x{op:04x}'}
        if op == 0x1003 and len(body) == 8:
            row.update(target_server_pos=body[5], bag_slot=body[7])
        if op == 0x1004 and len(body) == 12:
            row.update(target_server_pos=body[5], action=body[6] >> 1, is_pet=body[6] & 1)
        out.write(json.dumps(row, ensure_ascii=False) + '\n')
