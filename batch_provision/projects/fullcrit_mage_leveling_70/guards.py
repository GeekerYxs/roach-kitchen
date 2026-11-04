"""Live guards shared by every leveling stage: captain soda, revive item, stage-local stop checks."""
import _bootstrap  # noqa: F401
import os

import trial_run as t
from provisioner import world as w
from policy import SODA_EMPTY

SODA_ID, SWEET_ID = 8456, 8573
LEADER = os.environ["SHITU_LEADER"]


def count(c, item_id):
    return w.item_count(w.read_bag(c.mem) or (), item_id)


def soda_guard():
    """maze_train done_when hook (called only out of battle): raise instead of returning True, so the supervisor
    sees a recoverable Stop (recall, Hannibal restock, re-run) instead of a normally finished stage."""
    if count(t.Client(LEADER), SODA_ID) == 0:
        raise t.Stop(f'{SODA_EMPTY}，立即停止刷怪并全队回城补给')
    return False


def all_of(*checks):
    """Combine done_when hooks; each may raise t.Stop."""
    return lambda: any(check() for check in checks)


def configure_revive():
    """Turn on in-battle revive only when the captain actually carries the configured item.

    Sets the shared modules' runtime switches (revive.ITEM, maze_train.MAX_FALLS) directly, because both read
    their environment variable once at import time. With revive on, a revived apprentice is still flagged as
    fallen by maze_train, so a few falls per stage are tolerated; an apprentice that is not revived is sent home,
    leaves the party and is caught by the missing-member check.
    """
    import maze_train
    import revive

    item = int(os.environ.get('SHITU_REVIVE_CANDIDATE', '0') or 0)
    have = count(t.Client(LEADER), item) if item else 0
    revive.ITEM = item if have else 0
    if have:
        maze_train.MAX_FALLS = int(os.environ.get('SHITU_MAX_FALLS_WITH_REVIVE', '3'))
        t.say(f'[{LEADER}] 复活道具 {item} x{have}：战斗中复活倒地小号，普通地图每段允许倒地 {maze_train.MAX_FALLS} 次')
    else:
        maze_train.MAX_FALLS = int(os.environ.get('SHITU_MAX_FALLS', '1'))
        t.say(f'[{LEADER}] 未携带复活道具 {item}：首次倒地即全队回城重跑' if item else
              f'[{LEADER}] 复活已关闭：首次倒地即全队回城重跑')
    return revive.ITEM
