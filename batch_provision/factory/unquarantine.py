"""Release alts quarantined by a program fault, not by their own state (一键解除隔离.cmd).

2026-10-22: the first 2.100 update (fb0825d) still read the 飞鞋 record at the 2.99 offset, so every new alt read
(0, 0, 0), failed record_shoe 3 times and was quarantined (311 on the runner). The automatic release
(schedule.retry_quarantined) gives each alt ONE second chance and parks it for good after the next quarantine; a
release here uses db.release_quarantine (phase 'unknown', re-derived on the next observation) but logs the event as
'release_fix', so it does not use up that chance.

Entry: python -m factory.unquarantine [text in last_error] [--yes]
Default text = the shoe fault. Lists the matches, asks to type YES (not with --yes). Stop the supervisor first is not
required (it re-reads the db), but the released alts are only pulled by a running supervisor.
Pure part: select (tests/test_factory_unquarantine.py).
"""
import sys
import time
from collections import Counter

from provisioner import log

from . import db
from .config import ROOT, load_settings

SHOE_FAULT = '记录点没变成当前位置（读到 (0, 0, 0)）'
CONFIRM_WORD = 'YES'
EVENT = 'release_fix'


def select(rows, text):
    """rows: quarantined alts (dicts with char_id, name, last_error). -> those whose last_error contains text."""
    return [r for r in rows if text and text in (r['last_error'] or '')]


def main():
    args = [a for a in sys.argv[1:] if a != '--yes']
    text = args[0] if args else SHOE_FAULT
    log_path = log.setup(ROOT / 'logs', prefix='unquarantine')
    lg = log.for_account('main')
    lg.info('日志文件: %s', log_path)
    conn = db.connect(load_settings(ROOT / 'factory.toml').db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            'SELECT char_id, name, phase, last_error FROM alts WHERE quarantined=1 ORDER BY name')]
        lg.info('被隔离的小号共 %d 个，按原因：', len(rows))
        for reason, n in Counter(r['last_error'] or '（无）' for r in rows).most_common():
            lg.info('  %4d  %s', n, reason)
        chosen = select(rows, text)
        lg.info('原因里含「%s」的：%d 个 %s', text, len(chosen),
                ', '.join(r['name'] for r in chosen[:20]) + (' ...' if len(chosen) > 20 else ''))
        if not chosen:
            return 0
        if '--yes' not in sys.argv:
            answer = input(f'解除这 {len(chosen)} 个小号的隔离？输入 {CONFIRM_WORD} 确认：').strip()
            if answer != CONFIRM_WORD:
                lg.info('没有输入 %s，什么都没改', CONFIRM_WORD)
                return 1
        now = time.time()
        for r in chosen:
            db.release_quarantine(conn, r['char_id'], now, event=EVENT)
        lg.info('已解除 %d 个；阶段设为 unknown，总大脑下次看到时重新判断（不占用它们自动解除隔离的那一次机会）', len(chosen))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
