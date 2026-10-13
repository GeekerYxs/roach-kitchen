"""Stage 6: an alt on 平静海岸2区 (map 81) accepts quest 78 飞刀王的晚餐 from 海子 (NPC 403).

Entry: python -m factory.quest [factory.toml]
Attaches to every client with our DLL that is in the world on map 81; one job per alt, all in parallel (no team:
the dispatcher's 回城卷 already disbanded it). Per tick: read -> decide -> at most one action -> verify.
  1. walk with the official path-finder next to 海子 (escape from any battle on the way)
  2. click the NPC, then follow the menu: 飞刀王的晚餐 -> 嘿，在嘀咕什么 -> 继续。 -> 接受任务。
  3. verified when quest 78 shows up in the client's active-quest table; close a dialog left open
Restart at any point continues from the observed state (quest already active -> done, nothing sent).
decide() is pure (tests/test_factory_quest.py).

Old facts (Codex/Gemini MW_QUEST78_RUNBOOK.md, accepted live 2026-10-09 on 美味05..08, re-checked here): NPC 403 at
(1830,1377); the old guard required <= 220 px; roles that stopped at (1544,1260) were refused, (1780,1370) worked.
"""
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from provisioner import native
from provisioner.game import FIGHT_ESCAPE, Game, NotSent
from provisioner.memory import ProcessMemory
from provisioner.world import read_quest, read_team, read_world

from . import db
from .config import ROOT, load_settings
from .observe import observe
from .phase import COAST_MAP, QUEST_ID, derive_phase
from .runner import run_stage

ACTION = 'quest78'

NPC = 403                       # 海子
NPC_POINT = (1830, 1377)
STAND_POINT = (1780, 1370)      # path-finder target next to the NPC (old runs accepted from here)
TALK_RANGE = 200                # closer than this to NPC_POINT counts as there (old guard: 220)
# The menu pages in order; checked from the last one back, so the deepest page shown wins.
MENU = ('飞刀王的晚餐', '嘿，在嘀咕什么', '继续', '接受任务')
ACCEPT_LABEL = MENU[-1]

NAV_RETRY = 2.0
STALL = 6.0
SETTLE = 0.4
CLICK_WAIT = 4.0                # the menu must open within this long after clicking
MAX_CLICKS = 3
SELECT_RETRY = 3.0              # the same page still open this long after choosing -> choose again
MAX_SELECTS = 10
CONFIRM_WAIT = 5.0              # quest must show up this long after 接受任务
ESCAPE_FALLBACK = 6.0           # SP unchanged this long in battle -> send escape again anyway


@dataclass(frozen=True)
class Decision:
    kind: str      # done verified fail wait unconfirmed escape navigate cancel_nav click select accept close
    reason: str
    arg: object = None


@dataclass
class Memo:
    """Timing and counters only (never 'which step we are in': the open menu page tells that)."""
    last_sp: int | None = None
    last_escape: float = -1e9
    escapes: int = 0
    battles: int = 0
    in_battle: bool = False
    last_nav: float = -1e9
    progress_xy: tuple | None = None
    progress_at: float = 0.0
    clicked_at: float | None = None
    clicks: int = 0
    select_at: float = -1e9
    select_text: str | None = None
    selects: int = 0
    accept_at: float | None = None
    closed_at: float | None = None

    def observe(self, w, now):
        if w and (self.progress_xy is None or math.dist((w.x, w.y), self.progress_xy) > 15):
            self.progress_xy, self.progress_at = (w.x, w.y), now

    def record(self, d, w, now):
        if d.kind == 'escape':
            self.last_sp, self.last_escape, self.escapes = w.my_sp, now, self.escapes + 1
        elif d.kind == 'navigate':
            self.last_nav, self.progress_xy, self.progress_at = now, (w.x, w.y), now
        elif d.kind == 'cancel_nav':
            self.last_nav = -1e9
        elif d.kind == 'click':
            self.clicked_at, self.clicks = now, self.clicks + 1
        elif d.kind in ('select', 'accept', 'give'):
            self.select_at, self.select_text, self.selects = now, w.dialog.text, self.selects + 1
            if d.kind != 'select':
                self.accept_at = now
        elif d.kind == 'close':
            self.closed_at = now


def menu_choice(dialog, menu=MENU):
    """(select_id, label) of the deepest known page shown, None if no known option, 'ambiguous' if two match."""
    for want in reversed(menu):
        hits = [(i, label) for i, label in dialog.options if i and want in label]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return 'ambiguous'
    return None


def decide(world, quest, team, alt_row, memo, now):
    """world: WorldState | None; quest: provisioner.world.Quest | None; team: Team | None; alt_row: alts row."""
    if world is None or quest is None or team is None:
        return Decision('wait', '加载中')
    if quest.done:
        return Decision('done', f'任务 {QUEST_ID} 已完成过，不再接')
    if quest.active:
        if world.dialog and not world.in_battle and memo.closed_at is None:
            return Decision('close', '任务已接上，关掉对话框', 0)
        if memo.accept_at is not None or alt_row['pending_action'] == ACTION:
            return Decision('verified', f'任务表里出现任务 {QUEST_ID}（步骤 {list(quest.steps)}）')
        return Decision('done', f'任务 {QUEST_ID} 已在进行中')
    if world.map_id != COAST_MAP:
        return Decision('fail', f'不在平静海岸2区（地图 {world.map_id}）')
    if team.members:
        return Decision('fail', f'在队伍里（队长 {team.leader}），接任务要单人')
    d = blocked(world, memo, now)
    if d:
        return d
    if memo.accept_at is not None:
        if now - memo.accept_at < CONFIRM_WAIT:
            return Decision('wait', '已选接受任务，等任务表')
        return Decision('unconfirmed', f'选了接受任务 {CONFIRM_WAIT:.0f}s 后任务表里还没有任务 {QUEST_ID}')
    if world.dialog:
        choice = menu_choice(world.dialog)
        if choice is None or choice == 'ambiguous':
            return Decision('fail', f'海子对话框选项不认识: {world.dialog.options}')
        if world.dialog.text == memo.select_text and now - memo.select_at < SELECT_RETRY:
            return Decision('wait', '已选择，等下一页')
        if memo.selects >= MAX_SELECTS:
            return Decision('fail', f'对话选了 {memo.selects} 次还没接上任务')
        kind = 'accept' if ACCEPT_LABEL in choice[1] else 'select'
        return Decision(kind, f'选择「{choice[1]}」', choice[0])
    return approach(world, memo, now)


def blocked(world, memo, now):
    """Verification popup, battle (escape) or busy -> that Decision; None when free to walk / talk."""
    if world.verification:
        return Decision('wait', '验证码弹窗，等待答题')
    if world.in_battle:
        if world.my_sp is None:
            return Decision('wait', '战斗中，读不到自己的蓄力点')
        if world.my_sp != memo.last_sp:
            return Decision('escape', f'战斗中蓄力点 {memo.last_sp} -> {world.my_sp}，发送逃跑')
        if now - memo.last_escape >= ESCAPE_FALLBACK:
            return Decision('escape', f'蓄力点 {world.my_sp} 已 {ESCAPE_FALLBACK:.0f}s 未变，补发逃跑')
        return Decision('wait', '战斗中，等蓄力点变化')
    if world.busy:
        return Decision('wait', f'角色忙 flags={world.flags:#x}')
    return None


def approach(world, memo, now):
    """No dialog open: walk next to 海子, settle, click it."""
    distance = math.dist((world.x, world.y), NPC_POINT)
    if distance > TALK_RANGE:
        if world.nav_active or world.moving:
            if now - memo.progress_at > STALL:
                return Decision('cancel_nav', f'{STALL:.0f}s 没有移动，重新寻路')
            return Decision('wait', '走向海子')
        if now - memo.last_nav < NAV_RETRY:
            return Decision('wait', '等寻路开始')
        return Decision('navigate', f'寻路去海子（距离 {distance:.0f}）', (COAST_MAP, *STAND_POINT))
    if world.nav_active:
        return Decision('cancel_nav', f'到海子旁边（距离 {distance:.0f}），停止寻路')
    if memo.clicked_at is not None and now - memo.clicked_at < CLICK_WAIT:
        return Decision('wait', '已点海子，等对话框')
    if memo.clicks >= MAX_CLICKS:
        return Decision('fail', f'点了 {memo.clicks} 次海子都没出对话框')
    if world.moving or world.still_for < SETTLE:
        return Decision('wait', '在海子旁站稳')
    return Decision('click', f'点海子 NPC {NPC}（距离 {distance:.0f}）', NPC)


class QuestJob:
    action = ACTION

    def __init__(self, client, account, slot, settings, log_):
        self.c, self.account, self.slot, self.s, self.log = client, account, slot, settings, log_

    def _decide(self, mem, world, row, memo, now):
        return decide(world, read_quest(mem, QUEST_ID), read_team(mem), row, memo, now)

    def run(self):
        started = time.monotonic()
        result = {'name': self.c.name, 'pid': self.c.session.pid, 'char_id': self.c.char_id, 'ok': False}
        conn = db.connect(self.s.db_path)
        cid = self.c.char_id
        db.register_alt(conn, cid, self.account, self.slot, self.c.name, time.time())
        memo, last_reason = Memo(), None
        try:
            with ProcessMemory(self.c.session.pid, self.c.session.base) as mem:
                game = Game(self.c.session, mem)
                try:
                    self._save_phase(conn, mem, result, 'phase_before')
                    while True:
                        now = time.monotonic()
                        if now - started > self.s.quest_timeout:
                            raise RuntimeError(f'{self.s.quest_timeout:.0f}s 内没有完成')
                        if not native.alive(self.c.session.pid):
                            raise RuntimeError('游戏进程已退出')
                        world = read_world(mem)
                        if world and world.char_id != cid:
                            raise RuntimeError(f'角色变了 {cid} -> {world.char_id}')
                        row = db.alt(conn, cid)
                        if row['quarantined']:
                            raise RuntimeError(f'已隔离: {row["last_error"]}')
                        self._track_battle(world, memo)
                        memo.observe(world, now)
                        d = self._decide(mem, world, row, memo, now)
                        if d.reason != last_reason:
                            self.log.info('%s', d.reason)
                        last_reason = d.reason
                        if d.kind == 'done':
                            if row['pending_action'] == self.action:
                                db.complete_action(conn, cid, time.time())
                            result.update(ok=True, skipped=True)
                            break
                        if d.kind == 'verified':
                            db.complete_action(conn, cid, time.time())
                            result.update(ok=True, seconds_to_verify=round(now - (memo.accept_at or now), 2))
                            break
                        if d.kind == 'fail':
                            raise RuntimeError(d.reason)
                        if d.kind == 'unconfirmed':
                            memo = Memo()
                            if db.record_failure(conn, cid, d.reason, time.time()):
                                raise RuntimeError(f'连续失败 {db.MAX_RETRIES} 次，已隔离')
                            continue
                        if d.kind != 'wait':
                            self._execute(conn, game, d)
                            memo.record(d, world, now)
                        time.sleep(self.s.tick)
                    result.update(battles=memo.battles, escapes=memo.escapes, clicks=memo.clicks,
                                  selects=memo.selects)
                    self._save_phase(conn, mem, result, 'phase_after')
                finally:
                    game.close()
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            self.log.error('失败: %s', e, exc_info=not isinstance(e, RuntimeError))
        finally:
            conn.close()
        result['seconds'] = round(time.monotonic() - started, 1)
        return result

    def _execute(self, conn, game, d):
        if d.kind == 'escape':
            game.fight_command(FIGHT_ESCAPE)
        elif d.kind == 'navigate':
            game.navigate(*d.arg)
        elif d.kind == 'cancel_nav':
            game.cancel_navigation()
        elif d.kind == 'click':
            game.click_npc(d.arg)
        elif d.kind in ('select', 'close'):
            game.select_dialog(d.arg)
        elif d.kind in ('accept', 'give'):
            db.mark_pending(conn, self.c.char_id, self.action, time.time())
            try:
                game.select_dialog(d.arg)
            except NotSent as e:
                db.clear_pending(conn, self.c.char_id, time.time(), str(e))
                raise

    def _track_battle(self, world, memo):
        in_battle = bool(world and world.in_battle)
        if in_battle and not memo.in_battle:
            memo.battles += 1
            memo.last_sp = None      # the first SP seen in a battle triggers the escape
            self.log.info('遇怪进入战斗（第 %d 场）', memo.battles)
        elif memo.in_battle and not in_battle:
            self.log.info('战斗结束')
            memo.last_nav = -1e9     # battle interrupts navigation; allow re-issue at once
        memo.in_battle = in_battle

    def _save_phase(self, conn, mem, result, key):
        obs = observe(mem, read_world(mem))
        if obs is None:
            return
        plan = derive_phase(obs, db.ledger(conn, self.c.char_id), db.station_roles(conn))
        db.save_observation(conn, obs, plan, time.time())
        result[key] = plan.phase
        self.log.info('%d 级 任务%d=%s 阶段=%s（%s）', obs.level, QUEST_ID, obs.quest, plan.phase, plan.reason)


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    return run_stage('quest', settings, lambda c, account, slot, log_: QuestJob(c, account, slot, settings, log_),
                     map_id=COAST_MAP, map_name='平静海岸2区')


if __name__ == '__main__':
    sys.exit(main())
