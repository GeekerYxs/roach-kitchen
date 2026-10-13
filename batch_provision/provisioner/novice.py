"""Stage: new character in 菜鸟训练营 (map 271) -> talk to 新手传送师 -> 逍遥村西区 (map 1).

Entry: python -m provisioner.novice [novice.toml]
Attaches to every running client that has our DLL and is in the world; only characters on
map 271 are driven. Each client gets its own loop: read state -> decide -> do at most one action.

decide() is a pure function of (state, memo, now) so it is unit-tested without a game
(tests/test_novice.py). Every action is chosen from the CURRENT state, so the stage can be
stopped and restarted at any point.
"""
import json
import math
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import log, native, procs
from .game import Game
from .memory import ProcessMemory
from .world import read_world

ROOT = Path(__file__).resolve().parent.parent

NOVICE_MAP, VILLAGE_MAP = 271, 1
SPAWN_POINT = (280, 600)               # every new character starts here
TELEPORTER_NPC = 32                    # 新手传送师
TELEPORTER_POINT = (2656, 528)         # walkable spot next to the NPC (Codex run 2026-10-09)
NAV_TARGET = (2694, 477)               # official path-finder target that lands on TELEPORTER_POINT
TALK_RANGE = 80
DESTINATION_LABEL = '逍遥村'

# Timing rules (seconds)
NAV_RETRY = 2.0           # do not re-issue navigation more often than this
STALL_TIMEOUT = 6.0       # navigating but not moving for this long -> cancel and re-issue
CLICK_RETRY = 3.0         # re-click the NPC if no dialog appeared
SELECT_RETRY = 3.0
ESCAPE_FALLBACK = 6.0     # SP unchanged this long in battle -> send escape again anyway
MAX_CLICKS = 8


@dataclass(frozen=True)
class Decision:
    kind: str      # 'done' | 'fail' | 'wait' | 'escape' | 'select' | 'click' | 'cancel_nav' | 'navigate'
    reason: str
    arg: object = None


@dataclass
class Memo:
    """What the loop remembers between ticks (only timing / counters, never 'what step we are in')."""
    last_sp: int | None = None
    last_escape: float = 0.0
    escapes: int = 0
    battles: int = 0
    in_battle: bool = False
    last_nav: float = 0.0
    last_click: float = 0.0
    clicks: int = 0
    last_select: float = 0.0
    progress_xy: tuple | None = None
    progress_at: float = 0.0

    def observe(self, state, now):
        """Bookkeeping before each decision: remember when the character last made progress."""
        if state and (self.progress_xy is None or math.dist((state.x, state.y), self.progress_xy) > 15):
            self.progress_xy, self.progress_at = (state.x, state.y), now

    def record(self, d, state, now):
        """Update after decision d was executed successfully."""
        if d.kind == 'escape':
            self.last_sp, self.last_escape, self.escapes = state.my_sp, now, self.escapes + 1
        elif d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (state.x, state.y), now
        elif d.kind == 'cancel_nav':
            self.last_nav = 0.0
        elif d.kind == 'click':
            self.last_click, self.clicks = now, self.clicks + 1
        elif d.kind == 'select':
            self.last_select = now


def decide(state, memo, now):
    if state is None:
        return Decision('wait', '加载中（读不到角色）')
    if state.map_id == VILLAGE_MAP:
        return Decision('done', '已在逍遥村西区')
    if state.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if state.map_id != NOVICE_MAP:
        return Decision('fail', f'不在菜鸟训练营也不在逍遥村，地图={state.map_id}')

    if state.in_battle:
        if state.my_sp is None:
            return Decision('wait', '战斗中，读不到自己的蓄力点')
        if state.my_sp != memo.last_sp:
            return Decision('escape', f'蓄力点 {memo.last_sp} -> {state.my_sp}，发送逃跑')
        if now - memo.last_escape >= ESCAPE_FALLBACK:
            return Decision('escape', f'蓄力点 {state.my_sp} 已 {ESCAPE_FALLBACK:.0f}s 未变，补发逃跑')
        return Decision('wait', '战斗中，等蓄力点变化')
    if state.busy:
        return Decision('wait', f'角色忙 flags={state.flags:#x}')

    if state.dialog:
        hits = [(i, label) for i, label in state.dialog.options if DESTINATION_LABEL in label]
        if len(hits) != 1:
            return Decision('fail', f'对话框选项不认识: {state.dialog.options}')
        if now - memo.last_select < SELECT_RETRY:
            return Decision('wait', '已选择逍遥村，等待传送')
        return Decision('select', f'选择「{hits[0][1]}」', hits[0][0])

    distance = math.dist((state.x, state.y), TELEPORTER_POINT)
    if distance <= TALK_RANGE:
        if state.nav_active:
            return Decision('cancel_nav', f'已到传送师旁 ({distance:.0f})，停止寻路')
        if memo.clicks >= MAX_CLICKS:
            return Decision('fail', f'点了 {memo.clicks} 次传送师都没成功')
        if now - memo.last_click < CLICK_RETRY:
            return Decision('wait', '等待对话框')
        return Decision('click', f'和新手传送师对话 (距离 {distance:.0f})', TELEPORTER_NPC)

    if state.nav_active or state.moving:
        if now - memo.progress_at > STALL_TIMEOUT:
            return Decision('cancel_nav', f'{STALL_TIMEOUT:.0f}s 没有移动，重新寻路')
        return Decision('wait', '寻路中')   # keep the text constant: it is logged only when it changes
    if now - memo.last_nav < NAV_RETRY:
        return Decision('wait', '等待寻路开始')
    return Decision('navigate', f'寻路去新手传送师 (距离 {distance:.0f})', NAV_TARGET)


@dataclass(frozen=True)
class NoviceSettings:
    escape_action: int
    timeout: float
    tick: float


def load_settings(path):
    data = tomllib.loads(Path(path).read_text('utf-8')) if Path(path).is_file() else {}
    s = data.get('novice', {})
    return NoviceSettings(escape_action=int(s.get('escape_action', 8)),
                          timeout=float(s.get('timeout', 300)), tick=float(s.get('tick', 0.15)))


class NoviceJob:
    def __init__(self, client, settings, log_):
        self.c, self.s, self.log = client, settings, log_

    def run(self):
        started = time.monotonic()
        memo, last_reason, last_snapshot = Memo(), None, 0.0
        result = {'name': self.c.name, 'pid': self.c.session.pid, 'char_id': self.c.char_id, 'ok': False}
        with ProcessMemory(self.c.session.pid, self.c.session.base) as mem:
            game = Game(self.c.session, mem)
            try:
                while True:
                    now = time.monotonic()
                    if now - started > self.s.timeout:
                        raise RuntimeError(f'{self.s.timeout:.0f}s 内没到逍遥村')
                    if not native.alive(self.c.session.pid):
                        raise RuntimeError('游戏进程已退出')
                    state = read_world(mem)
                    if state and state.char_id != self.c.char_id:
                        raise RuntimeError(f'角色变了 {self.c.char_id} -> {state.char_id}')
                    self._track_battle(state, memo)
                    memo.observe(state, now)
                    if state and now - last_snapshot >= 2:
                        last_snapshot = now
                        self.log.debug('状态 map=%d xy=(%.0f,%.0f) flags=%#x busy=%s battle=%s sp=%s nav=%s dialog=%s',
                                       state.map_id, state.x, state.y, state.flags, state.busy, state.in_battle,
                                       state.my_sp, state.nav_active, bool(state.dialog))
                    d = decide(state, memo, now)
                    if d.reason != last_reason and d.kind == 'wait':
                        self.log.info('%s', d.reason)
                    last_reason = d.reason
                    if d.kind == 'done':
                        self.log.info('到达逍遥村西区 坐标=(%.0f,%.0f)，用时 %.1fs，战斗 %d 场，逃跑指令 %d 次',
                                      state.x, state.y, now - started, memo.battles, memo.escapes)
                        result.update(ok=True, x=round(state.x), y=round(state.y))
                        break
                    if d.kind == 'fail':
                        raise RuntimeError(d.reason)
                    if d.kind != 'wait':
                        self._execute(game, d, state)
                        memo.record(d, state, now)
                    time.sleep(self.s.tick)
            except Exception as e:
                result['error'] = f'{type(e).__name__}: {e}'
                self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        result.update(seconds=round(time.monotonic() - started, 1), battles=memo.battles, escapes=memo.escapes)
        return result

    def _track_battle(self, state, memo):
        in_battle = bool(state and state.in_battle)
        if in_battle and not memo.in_battle:
            memo.battles += 1
            memo.last_sp = None   # like the official auto-fight: first SP seen in a battle triggers an action
            self.log.info('进入战斗（第 %d 场），蓄力点=%s', memo.battles, state.my_sp)
        elif memo.in_battle and not in_battle:
            self.log.info('战斗结束')
            memo.last_nav = 0.0   # battle interrupts navigation; allow re-issue at once
        memo.in_battle = in_battle

    def _execute(self, game, d, state):
        self.log.info('%s', d.reason)
        if d.kind == 'escape':
            ret = game.fight_command(self.s.escape_action)
            self.log.debug('SendFightCmdPacket(0,0,%d,0) -> %#x', self.s.escape_action, ret)
        elif d.kind == 'select':
            game.select_dialog(d.arg)
        elif d.kind == 'click':
            game.click_npc(d.arg)
        elif d.kind == 'cancel_nav':
            game.cancel_navigation()
        elif d.kind == 'navigate':
            game.navigate(NOVICE_MAP, *d.arg)


def main():
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'novice.toml'
    log_path = log.setup(ROOT / 'logs', prefix='novice')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    settings = load_settings(cfg)
    logger.info('逃跑动作编号=%d 超时=%.0fs', settings.escape_action, settings.timeout)
    clients = procs.discover(logger)
    targets = []
    for c in clients:
        if c.map_id == NOVICE_MAP:
            at_spawn = math.dist((c.x, c.y), SPAWN_POINT) < 1
            logger.info('%s 在菜鸟训练营 (%.0f,%.0f)%s → 处理', c.name, c.x, c.y, '，新号出生点' if at_spawn else '')
            targets.append(c)
        else:
            logger.info('%s 在地图 %d，不是新手村，跳过', c.name, c.map_id)
    if not targets:
        logger.info('没有需要处理的角色')
        return 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix='novice') as pool:
        results = list(pool.map(lambda c: NoviceJob(c, settings, log.for_account(c.name)).run(), targets))
    out = ROOT / 'logs' / (log_path.stem.replace('novice_', 'novice_summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    logger.info('=' * 60)
    for r in results:
        logger.info('%-8s %s 用时%.1fs 战斗%d 逃跑指令%d %s', r['name'], '到达' if r['ok'] else '失败', r['seconds'],
                    r['battles'], r['escapes'], r.get('error', ''))
    ok = sum(r['ok'] for r in results)
    logger.info('完成 %d/%d，总用时 %.1fs。汇总: %s', ok, len(results), time.monotonic() - started, out)
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
