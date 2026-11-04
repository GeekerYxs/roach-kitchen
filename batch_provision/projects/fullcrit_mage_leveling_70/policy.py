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
DEATH_WORDS = ("倒下", "倒地", "knocked out", "不在", "离开", "缺员")
STUCK_WORDS = ("卡住", "走不到", "停滞", "意外的地图", "没走到", "没换地图")


def stage_index(min_level):
    """Index into LADDER of the stage to run for the lowest apprentice level, or None once everyone is 70."""
    for i, (_label, _map, until) in enumerate(LADDER):
        if min_level < until:
            return i
    return None


def classify_stop(message, maps_split=False, party_incomplete=False):
    """Why a stage stopped: 'death' / 'soda' / 'stuck', or None when it needs a human."""
    text = str(message)
    if SODA_EMPTY in text:
        return "soda"
    if maps_split or party_incomplete or any(w in text for w in DEATH_WORDS):
        return "death"
    if any(w in text for w in STUCK_WORDS):
        return "stuck"
    return None


class RetryBook:
    """Automatic recoveries per stage. The count restarts whenever the team gained levels since the last failure,
    so a long stage (58->70 takes hours) is not stopped by a few unrelated deaths spread over the whole grind."""

    def __init__(self, limit=3):
        self.limit = limit
        self.count = {}
        self.progress = {}

    def failed(self, label, progress):
        """Record a failure at `progress` (e.g. sum of apprentice levels); True while another retry is allowed."""
        if progress > self.progress.get(label, -1):
            self.count[label] = 0
        self.progress[label] = max(progress, self.progress.get(label, -1))
        self.count[label] = self.count.get(label, 0) + 1
        return self.count[label] <= self.limit

    def succeeded(self, label):
        self.count[label] = 0


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
