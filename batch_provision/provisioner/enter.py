"""Log in N accounts in parallel and enter the chosen role slot.

Entry: python -m provisioner.enter [enter.toml]
Per account: login to the selection screen -> read the roster and check the slot has a role
-> DLL command "enter slot" -> wait for the world pointer -> verify the in-world char id.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, log, native
from .login import LaunchThrottle, login, read_session
from .memory import ProcessMemory
from .world import read_world

ROOT = Path(__file__).resolve().parent.parent


def enter_role(session, slot, timeout, log_):
    """From the selection screen: DLL selects `slot` and presses Enter until the world pointer appears."""
    native.enter_world(session, slot)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if not native.alive(session.pid):
            raise RuntimeError('游戏进程在进入过程中退出')
        st = native.read_status(session.pid)
        if st['stage'] != last:
            log_.debug('DLL stage=%d(%s) error=%d enter_messages=%d', st['stage'],
                       native.STAGE.get(st['stage'], '?'), st['error'], st['enter_messages'])
            last = st['stage']
        if st['stage'] == native.WORLD_STAGE:
            log_.info('世界指针已出现（DLL 用时 %dms，按回车 %d 次）', st['finished'] - st['started'], st['enter_messages'])
            return
        if st['stage'] < 0:
            raise RuntimeError(f"进入失败 error={st['error']}({native.DLL_ERROR.get(st['error'], '未知')})")
        time.sleep(0.2)
    raise RuntimeError(f'{timeout:.0f} 秒内没进入世界')


def verify_in_world(session, char_id, name, log_, timeout=30):
    """The own player object must carry the selected role's id (the world pointer alone is not proof)."""
    deadline = time.monotonic() + timeout
    world = None
    with ProcessMemory(session.pid, session.base) as mem:
        while time.monotonic() < deadline:
            world = read_world(mem)
            if world and world.char_id == char_id and world.map_id:
                break
            time.sleep(0.5)
    if not world or world.char_id != char_id:
        raise RuntimeError(f'进入后的角色 ID={world.char_id if world else "无"}，不是选中的 {char_id}')
    title = native.window_title(session.hwnd)
    log_.info('已在游戏中: %s ID=%d 地图=%d 坐标=(%.0f,%.0f)', name, world.char_id, world.map_id, world.x, world.y)
    if name not in title:
        log_.warning('窗口标题里没有角色名（仅提示）: %s', title)
    return world


class EnterJob:
    def __init__(self, settings, account, throttle):
        self.s, self.account, self.throttle = settings, account, throttle
        self.slot = settings.slot_of(account)
        self.log = log.for_account(account.name)
        self.runtime = ROOT / 'runtime'
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.session = None
        self.step = 'init'

    def run(self):
        started = time.monotonic()
        summary = {'account': self.account.name, 'slot': self.slot, 'ok': False, 'step': None, 'error': None}
        try:
            self._step('登录')
            self.session = login(self.s, self.account, self.runtime, self.throttle, self.log, self.s.kill_on_failure)
            self._step('读取选角列表')
            _, roster = read_session(self.session, self.account.name, self.log)
            if self.slot > len(roster):
                raise RuntimeError(f'槽{self.slot} 没有角色（这个号只有 {len(roster)} 个角色），不进入')
            char_id, level, name = roster[self.slot - 1]
            summary.update(role=name, char_id=char_id)
            self._step(f'进入槽{self.slot}: {name} (ID={char_id}, {level}级)')
            self._enter()
            self._step('核验已进入游戏')
            world = self._verify(char_id, name)
            summary.update(ok=True, map_id=world.map_id, x=world.x, y=world.y)
        except Exception as e:
            summary.update(step=self.step, error=f'{type(e).__name__}: {e}')
            self.log.error('步骤「%s」失败: %s', self.step, e, exc_info=not isinstance(e, (RuntimeError,)))
            self._on_failure()
        summary['pid'] = self.session.pid if self.session else None
        summary['hwnd'] = self.session.hwnd if self.session else None
        summary['seconds'] = round(time.monotonic() - started, 1)
        self.log.info('结束: %s 用时 %.1fs%s', '成功' if summary['ok'] else '失败', summary['seconds'],
                      f" 错误={summary['error']}" if summary['error'] else '')
        return summary

    def _step(self, name):
        self.step = name
        self.log.info('== %s ==', name)

    def _enter(self):
        enter_role(self.session, self.slot, self.s.enter_timeout, self.log)

    def _verify(self, char_id, name):
        return verify_in_world(self.session, char_id, name, self.log)

    def _on_failure(self):
        if self.session and self.s.kill_on_failure:
            self.log.warning('kill_on_failure=true，关闭 pid=%d', self.session.pid)
            native.kill(self.session.pid)
        elif self.session:
            self.log.warning('保留窗口 pid=%d hwnd=%#x 供排查', self.session.pid, self.session.hwnd)


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'enter.toml'
    log_path = log.setup(ROOT / 'logs', prefix='enter')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        settings = config.load_enter(cfg_path)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg_path, e)
        return 2
    if not native.LAUNCHER.is_file():
        logger.error('缺少 %s，请先运行 native\\build.ps1', native.LAUNCHER)
        return 2
    logger.info('账号 %d 个: %s；默认进入槽%d；空闲内存下限 %dMB', len(settings.accounts),
                ', '.join(f'{a.name}(槽{settings.slot_of(a)})' for a in settings.accounts), settings.slot,
                settings.min_free_memory_mb)
    throttle = LaunchThrottle(settings.launch_interval, settings.min_free_memory_mb)
    jobs = [EnterJob(settings, a, throttle) for a in settings.accounts]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix='enter') as pool:
        results = list(pool.map(lambda j: j.run(), jobs))

    out = ROOT / 'logs' / (log_path.stem.replace('enter_', 'enter_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        if r['ok']:
            logger.info('%-6s 成功 槽%d %s ID=%s 地图=%s 坐标=(%s,%s) pid=%s', r['account'], r['slot'], r.get('role'),
                        r.get('char_id'), r.get('map_id'), r.get('x'), r.get('y'), r['pid'])
        else:
            logger.info('%-6s 失败 槽%d | 步骤=%s %s', r['account'], r['slot'], r['step'], r['error'])
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，总用时 %.1fs。汇总: %s', ok, len(results), time.monotonic() - started, out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
