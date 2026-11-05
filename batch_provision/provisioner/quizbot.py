"""启动答题器 for every product line: check it runs, start it when it does not (user 2026-11-05).

    python -X utf8 -m provisioner.quizbot          (from batch_provision/) check, start if missing, print the result

The 答题器 stays in its own folder (repo root / 大冒险2_自动答题器_原生无感关窗版). One per computer serves every game
window, whatever line opened it (料理 / 师徒 / 70 级 / 抓宠): it finds and injects each new WAATClient.exe by itself,
answers the battle quiz (0x46F4) and the boss quiz (0x46F5), and unlocks the client's own 辅助工具 pages (战斗辅助,
自动采集, 自动任务). So a second line starting later finds it running and leaves it alone.

Never start a second one: each start kills the running 答题器 first (main.cpp kill_stale_controllers), which drops
every window's pipe for a moment. The check + start runs under a lock file, so two lines starting at the same time
do not both launch it. It needs the same administrator rights as our own DLL injection (the lines already run so).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent                     # batch_provision
DIR = ROOT.parent / '大冒险2_自动答题器_原生无感关窗版'
EXE = '启动答题器.exe'
NAMES = ('启动答题器.exe', 'quizbot.exe')
LOCK = ROOT / 'runtime' / 'quizbot.lock'
LOCK_STALE, START_WAIT = 60, 20


def names():
    """Lowercased exe names of every running process (provisioner.procs, Toolhelp)."""
    from .procs import process_rows
    return {exe for _, _, exe in process_rows()}


def running(tries=3, list_names=None, sleep=time.sleep):
    """True when a 答题器 process is up. 2026-10-28: one process read came back without it while it ran the whole
    time, so only `tries` misses in a row count."""
    list_names = list_names or names
    for i in range(tries):
        got = list_names()
        if any(n.lower() in got for n in NAMES):
            return True
        if i + 1 < tries:
            sleep(2)
    return False


class _Lock:
    """O_EXCL lock file, a lock older than LOCK_STALE s is a dead starter's."""
    def __init__(self, path=LOCK):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        end = time.monotonic() + LOCK_STALE
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() > end:
                    raise TimeoutError(f'等答题器启动锁超时: {self.path}')
                time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def start(exe_dir=DIR):
    """Launch it in its own console window, detached from the caller (it keeps running when the line stops)."""
    exe = Path(exe_dir) / EXE
    if not exe.is_file():
        raise FileNotFoundError(f'找不到答题器: {exe}')
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NEW_CONSOLE | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    subprocess.Popen([str(exe)], cwd=str(exe_dir), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure(say=print, list_names=None, launch=start, sleep=time.sleep, wait=START_WAIT, lock=None):
    """-> 'running' (was up), 'started' (launched and seen) or 'failed' (said why). Safe to call from every line,
    any number of times."""
    if running(list_names=list_names, sleep=sleep):
        return 'running'
    with (lock or _Lock()):
        if running(tries=1, list_names=list_names, sleep=sleep):      # another line started it meanwhile
            return 'running'
        try:
            launch()
        except Exception as e:
            say(f'答题器没开，自动启动失败: {e}（请手动双击 {DIR / EXE}）')
            return 'failed'
        for _ in range(int(wait)):
            sleep(1)
            if running(tries=1, list_names=list_names, sleep=sleep):
                say('答题器没开，已自动启动')
                return 'started'
    say(f'答题器启动后 {wait} 秒还没看到进程（要管理员权限？请手动双击 {DIR / EXE}）')
    return 'failed'


if __name__ == '__main__':
    r = ensure()
    print({'running': '答题器已经在运行', 'started': '答题器已启动', 'failed': '答题器没能启动'}[r])
    sys.exit(0 if r != 'failed' else 1)
