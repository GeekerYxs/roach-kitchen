"""Clear this machine's logs: logs/ (run logs, reports, summaries) and runtime/ (launch results, tap captures).

Entry: python -m provisioner.cleanlogs [保留小时数] [--yes]   (一键清空日志.cmd asks interactively)
Never touches state/ (factory.db and the role records the supervisor needs to rebuild roles), config or code.
- files newer than the "keep hours" answer stay (0 = clear everything)
- while any game client runs, runtime/ is left alone (running windows still write their tap files there)
- a file another program holds open (e.g. the log of a running supervisor) is skipped and listed
Asks to type YES before deleting (not with --yes).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = ('logs', 'runtime')
CONFIRM_WORD = 'YES'


def select(files, now, keep_seconds):
    """files: [(path, mtime, size)] -> the ones older than keep_seconds (all when keep_seconds <= 0)."""
    return [f for f in files if keep_seconds <= 0 or now - f[1] > keep_seconds]


def size_text(n):
    return f'{n / 1048576:.1f} MB' if n >= 1048576 else f'{n / 1024:.0f} KB'


def scan(folder):
    return [(p, p.stat().st_mtime, p.stat().st_size) for p in folder.rglob('*') if p.is_file()]


def remove(files):
    """-> (deleted count, freed bytes, [skipped paths])"""
    done, freed, skipped = 0, 0, []
    for path, _, size in files:
        try:
            path.unlink()
            done, freed = done + 1, freed + size
        except OSError:
            skipped.append(path)
    return done, freed, skipped


def prune_dirs(folder):
    for d in sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()               # only empty folders go
        except OSError:
            pass


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    yes = '--yes' in sys.argv
    try:
        hours = float(args[0] if args else (input('保留最近几小时的日志？（0 = 全部清掉）[0]: ').strip() or 0))
    except ValueError:
        print('请输入数字')
        return 2
    from .procs import game_pids
    running = game_pids()
    folders = [f for f in FOLDERS if not (f == 'runtime' and running)]
    if running:
        print(f'有 {len(running)} 个游戏窗口在运行：runtime\\ 不清（运行中的窗口还在用），只清 logs\\')
    now = time.time()
    plan = {f: select(scan(ROOT / f), now, hours * 3600) if (ROOT / f).is_dir() else [] for f in folders}
    total = sum(len(v) for v in plan.values())
    for f, files in plan.items():
        print(f'  {f}\\  {len(files)} 个文件，{size_text(sum(x[2] for x in files))}')
    if not total:
        print('没有要清的文件')
        return 0
    print('不会动 state\\（factory.db 等，总大脑重建角色要用）和任何配置、代码。')
    if not yes and input(f'确认清空请输入 {CONFIRM_WORD} 后回车: ').strip().upper() != CONFIRM_WORD:
        print('没有确认，什么都没删')
        return 1
    skipped_all = []
    for f, files in plan.items():
        done, freed, skipped = remove(files)
        prune_dirs(ROOT / f)
        skipped_all += skipped
        print(f'{f}\\ 删除 {done} 个文件，释放 {size_text(freed)}')
    if skipped_all:
        print(f'{len(skipped_all)} 个文件正被别的程序占用，没删（比如还在运行的总大脑的日志）:')
        for p in skipped_all[:20]:
            print('  ', p.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
