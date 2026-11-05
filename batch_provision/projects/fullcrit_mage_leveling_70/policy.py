"""Pure decisions of the 1-70 leveling supervisor (no game client needed, unit-tested on any OS)."""
import math

# (label, map, until): the user-directed no-task route. A stage is active while the lowest apprentice level is
# below its `until`; map/route details live in route.py.
LADDER = (
    ("阴森古井", 651, 10),
    ("轮回之城", 555, 14),
    ("暗影迷城", 600, 18),
    ("八阵图", 700, 24),
    ("遗忘洞穴", 750, 28),
    ("通天塔一区", 280, 33),
    ("通天塔二区", 281, 43),
    ("巨石之城东部遗址", 1100, 48),
    ("惊魂监狱", 264, 53),
    ("陷阱囚牢", 1150, 58),
    ("禁锢之地", 1200, 70),
)
FINAL_LEVEL = LADDER[-1][2]

SODA_EMPTY = "队长劲爆汽水为0"          # Stop text shared by every stage guard and the supervisor
OFFLINE = "客户端离线"                  # supervisor's own text when a role's client cannot be read
DEATH_WORDS = ("倒下", "倒地", "knocked out", "不在", "离开", "缺员")
STUCK_WORDS = ("卡住", "走不到", "停滞", "意外的地图", "没走到", "没换地图")
OFFLINE_WORDS = ("窗口没找到", "读不到等级", OFFLINE)
RESOURCE_WORDS = ("金币不足", "金币不够", "不够买", "不够放", "背包无空格")   # gold / bag space: needs a human


def stage_index(min_level):
    """Index into LADDER of the stage to run for the lowest apprentice level, or None once everyone is 70."""
    for i, (_label, _map, until) in enumerate(LADDER):
        if min_level < until:
            return i
    return None


def fallback_index(index):
    """The next easier map to train one level in when `index` keeps failing (None for the first map).
    惊魂监狱 is skipped: its entry needs the shoe / 铁男 flow, the generic field route cannot enter it."""
    for i in range(index - 1, -1, -1):
        if LADDER[i][0] != "惊魂监狱":
            return i
    return None


def classify_stop(message, maps_split=False, party_incomplete=False):
    """Why a stage stopped.

    'offline'  - a client window / memory is gone: wait for it to come back, stop only if it does not
    'resource' - not enough gold: the only case the supervisor gives up on by itself
    'soda' / 'death' / 'stuck' - known recoverable causes
    'other'    - anything else: still recovered (recall, refill, retry with back-off), never a reason to stop
    """
    text = str(message)
    if any(w in text for w in OFFLINE_WORDS):
        return "offline"
    if any(w in text for w in RESOURCE_WORDS):
        return "resource"
    if SODA_EMPTY in text:
        return "soda"
    if maps_split or party_incomplete or any(w in text for w in DEATH_WORDS):
        return "death"
    if any(w in text for w in STUCK_WORDS):
        return "stuck"
    return "other"


class Action:
    def __init__(self, streak, wait, fallback):
        self.streak, self.wait, self.fallback = streak, wait, fallback

    def __repr__(self):
        return f"Action(streak={self.streak}, wait={self.wait}, fallback={self.fallback})"


class RetryBook:
    """Failure book of the supervisor. There is no retry limit: a failure always leads to recovery.

    streak  - failures of a stage in a row without the team gaining a level; restarts on any level gained or
              when the stage finishes, so a long stage is never judged by deaths spread over hours.
    wait    - back-off before the next attempt: 0 for the first failure, then base, 2*base ... up to cap, so a
              repeating fault (server lag, a blocked path) is not hammered.
    fallback- every `fallback_after`-th failure in a row: train one level on an easier map first. Gaining that
              level both makes the team stronger and restarts the streak.
    """

    def __init__(self, base=30, cap=600, fallback_after=3):
        self.base, self.cap, self.fallback_after = base, cap, fallback_after
        self.count = {}
        self.progress = {}

    def failed(self, label, progress):
        if progress > self.progress.get(label, -1):
            self.count[label] = 0
        self.progress[label] = max(progress, self.progress.get(label, -1))
        streak = self.count[label] = self.count.get(label, 0) + 1
        wait = 0 if streak == 1 else min(self.cap, self.base * 2 ** (streak - 2))
        fallback = bool(self.fallback_after) and streak % self.fallback_after == 0
        return Action(streak, wait, fallback)

    def succeeded(self, label):
        self.count[label] = 0


def backoff(attempt, base=30, cap=600):
    """Wait before the attempt-th retry of a recovery step that itself failed (attempt >= 1)."""
    return min(cap, base * 2 ** (attempt - 1))


YAM_NAMES = ("加钙地瓜", "(御)加钙地瓜")    # exactly these; never the 礼包 / 超级 / 倍能 variants


def yam_ids(items):
    """Item ids that are a plain 加钙地瓜 (items = {id: Item}). Matching by substring also hit
    (御)加钙地瓜礼包 (opening the gift pack would be logged as eating a yam) and the 超级 / 倍能 variants."""
    return {i for i, it in items.items() if it.name in YAM_NAMES}


def stacks_needed(stacks, need, stack_max=99):
    """Free bag slots a purchase of `need` items needs, when the existing stacks of that item can top up first.
    stacks = quantities already in the bag."""
    room = sum(max(0, stack_max - q) for q in stacks)
    return max(0, math.ceil((need - room) / stack_max))


def shoe_plan(cooldown_left, wait_max, has_record):
    """'fly' / 'wait' / 'paid' for a character that must reach the 龙之都内城 record point."""
    if not has_record:
        return "paid"
    if cooldown_left <= 0:
        return "fly"
    return "paid" if cooldown_left > wait_max else "wait"
