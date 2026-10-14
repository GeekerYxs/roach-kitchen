"""Logging: one file per run under logs/, plus console. Each line is tagged with the account."""
import atexit
import logging
import logging.handlers
import queue as _queue
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
    # The console is written by its own thread: a paused console (text selected in the black window) must not stop
    # the threads that log. 2026-10-14 runner: the supervisor wrote nothing for 35 min and every batch timed out.
    queue = logging.handlers.QueueHandler(_queue.SimpleQueue())
    queue.setLevel(logging.INFO)
    queue.addFilter(_Default())
    listener = logging.handlers.QueueListener(queue.queue, console, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)                  # flush the last console lines on exit
    root.addHandler(file)
    root.addHandler(queue)
    _no_quick_edit()
    return path


def _no_quick_edit():
    """Turn off QuickEdit for this console: a click in the window then no longer pauses the program."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)                         # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if h and k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)   # -ENABLE_QUICK_EDIT_MODE +ENABLE_EXTENDED_FLAGS
    except Exception:       # noqa: BLE001 - no console (tests, redirected): nothing to do
        pass


def for_account(account):
    return logging.LoggerAdapter(logging.getLogger('prov'), {'account': account})
