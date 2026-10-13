"""Logging: one file per run under logs/, plus console. Each line is tagged with the account."""
import logging
import sys
import time
from pathlib import Path

FORMAT = '%(asctime)s.%(msecs)03d %(levelname)-5s [%(account)-6s] %(message)s'


class _Default(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'account'):
            record.account = 'main'
        return True


def setup(log_dir, prefix='run'):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / time.strftime(f'{prefix}_%Y%m%d_%H%M%S.log')
    root = logging.getLogger('prov')
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter(FORMAT, '%H:%M:%S')
    file = logging.FileHandler(path, encoding='utf-8')
    file.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    for h in (file, console):
        h.setFormatter(fmt)
        h.addFilter(_Default())
        root.addHandler(h)
    return path


def for_account(account):
    return logging.LoggerAdapter(logging.getLogger('prov'), {'account': account})
