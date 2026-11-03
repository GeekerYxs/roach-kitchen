"""Who is in a batch: masters, apprentice names, accounts, log ids, the env every script gets.

Teams come from line.toml [team.<name>] (master, slot, gold). Same rules as r4_env.sh for slots 0..3 (tests/test_line.py
checks the two agree for teams a..d), so old logs / state files keep their names:
  batch N, slot k (0..3) = 亿万(16(N-1)+4k+1 .. +4); team slot i uses account cap(21+4k+i), role slot N.
  LOGID r4<team> for batch 1, r4<team>_b<N> after (the team name, not the slot: a new master = a new name).
A team may instead name its own accounts and role names (2026-10-29 exp-map trial: cap37.. and Opus55A1..):
  accounts = first account number (the team uses capN..capN+3), names = name prefix: batch N, account i -> prefix(4(N-1)+i).
  levels = where this team leaves each map (keys of LEVELS; unset = the route's: BPLUS_LEVELS, or LEVELS for v5).
Or a list of account names (accounts = ["gm2g01t01u01", ...], 2026-10-30 B+ trial with 伏地魔2): batch N uses them all.
  route = 'bplus' (default since 2026-10-30) runs route.ROUTE_BPLUS, 'v5' the old route.ROUTE; tower1 default 35;
  tower2 = where 通天塔二区 stops: '40' or 'L+E' (default per route: TOWER2; level L and
  E exp into it, the late quests + 出师 fill the rest up to 40); batches = this team's own batch list.
"""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MASTER_SLOTS = 4                 # a master holds 4 apprentices at most (excluded ones stay bound and take a slot)
JOBS = ('战士', '术士')           # zhuanzhi_take.JOBS; 战士 -> 勇者 (route B+ / v5), 术士 -> 元素使 (route.ROUTE_YUANSU)
TALENT_STATS = ('力量', '感知', '体质', '敏捷', '运气')     # = provisioner.game.TALENT_STATS (not importable here)
SCROLLS = 20                     # 回城卷 each apprentice gets from the master (SHITU_SCROLLS)
CONFIG = Path(__file__).with_name('line.toml')
# the v5 route leaves 轮回之城 at 15, 暗影迷城 at 19, 八阵图 at 23 (maze_train) and 25 (bazhen25), 遗忘洞穴 at 28
LEVELS = {'lunhui': 15, 'maze1': 19, 'maze2': 23, 'bazhen': 25, 'cave': 28}
# route B+ (the default since 2026-10-30): 轮回 10-12, 迷城 12-16, 八阵图 16-23 without the trip home, 洞穴 23-28
# (exp-map trial EXP_MAP_TRIAL.md: at 24 洞穴 10,639/min vs 八阵图 6,984; the bp live run used 24)
BPLUS_LEVELS = {'lunhui': 12, 'maze1': 16, 'maze2': 23, 'bazhen': 23, 'cave': 28}
ROUTE_NAMES = ('bplus', 'v5')    # route.ROUTES keys; bplus = default
GOLD = 10000                     # starting gold per apprentice (user 2026-11-01): spent before the first income
                                 # (考验 at 35) is ~2-2.5k of PP鸡; 1万 ran whole batches twice (r4 d, 11-01 w2);
                                 # give_gold returns it all at the batch end, more only ties up the master's gold
TOWER1 = 35                      # user 2026-10-30: masters differ in strength, every team does 通天一 to 35 for now
# 通天塔二区 target per route. B+ live 2026-10-30 (BPLUS_NOTES.md): left 二区 at 38+19.9万, the 181 reward + quest
# battles up to 蝎子王 gave ~19.2万 -> 39+11.9万, short of the 40 that 神仙姐姐 wants; 39+125000 gets there without topup
# 2026-10-31 pa / pb: 39+125000 still needed a 2-3 min topup on both (the late quests earned < 187,448 = 312,448 - 125,000,
# bp's 19.2万 left a 2% margin) -> 'auto' (user: test, record, optimize): ops exp_note writes the exp where 二区 was
# left and after 蝎子王 (logs/tower2_exp.csv); tower2_auto takes this master's smallest earning of its last batches
TOWER2 = {'bplus': 'auto', 'v5': '40'}
TOWER2_FIRST = '39+170000'       # no history for the master yet: ~26% margin on bp's earning
TOWER2_MARGIN = 25000            # exp kept over the smallest earning seen (one 二区 minute is 2.2-3.9万); user 2026-11-02 (was 40000)
                                 # w1: the same master earned 23.4万 then 19.6万 (25000 left it 1万 short -> topup)
TOWER2_LOOKBACK = 3              # batches of history that count
EXP_CSV = Path(__file__).resolve().parent.parent / 'logs' / 'tower2_exp.csv'
EXPLIB = Path(__file__).resolve().parents[3] / 'expwatch' / 'explib.csv'
# 任务 224 遗忘洞穴的恐慌 (the q224 / snake steps right after the cave) is taken at 28 only: below it 大个王 answers
#「好吧」 and nothing else (2026-10-29 ob team left the cave at 27 and q224 failed)
MIN_LEVELS = {'cave': 28}


@dataclass(frozen=True)
class Team:
    master: str
    slot: int                    # which 4 accounts / which names (0..3)
    gold: int                    # starting gold the master hands out
    tower1: int = TOWER1         # 通天塔一区 up to this level, then 二区
    accounts: int = 0            # first cap account number (0 = the slot's: 21 + 4 * slot)
    names: str = ''              # role name prefix ('' = 亿万 numbered by the slot)
    levels: tuple = ()           # ((key, level), ...) overrides of LEVELS
    account_names: tuple = ()    # explicit accounts (instead of capN..capN+3)
    route: str = 'bplus'         # 'bplus' = route.ROUTE_BPLUS (default), 'v5' = route.ROUTE
    tower2: str = ''             # 通天塔二区 target: '40' or 'L+E'; '' = the route's TOWER2
    stat: str = '体质'           # where the apprentices' talent points go (provisioner.game.TALENT_STATS)
    job: str = '战士'            # 10 级 class (zhuanzhi_take.JOBS: 战士 / 术士)
    revive: int = 0              # item the master uses on a downed apprentice in battle (revive.py; 0 = off)
    tidy: bool = False           # every U home also runs tidy.py (packs / pranks / gear / selling)
    first: int = 1               # number of batch 1's first role (names + number); 2026-11-03 ys2: 元素使05.. on fresh accounts

    def __post_init__(self):
        if not self.tower2:
            object.__setattr__(self, 'tower2', TOWER2[self.route])

    @property
    def first_account(self):
        return self.accounts or 21 + 4 * self.slot

    @property
    def account_list(self):
        return list(self.account_names) or [f'cap{self.first_account + i}' for i in range(MASTER_SLOTS)]

    def level(self, key):
        return dict(LEVELS if self.route == 'v5' else BPLUS_LEVELS, **dict(self.levels))[key]


def _explib(path=EXPLIB):
    import csv
    with open(path, encoding='utf-8') as f:
        return {int(r['level']): int(r['playerexp']) for r in csv.DictReader(f)}


def tower2_auto(master, rows, need=None, size=None):
    """'39+E' for this master: E = exp 39 -> 40 - the smallest per-apprentice earning between leaving 二区 and
    蝎子王 over its last TOWER2_LOOKBACK batches + TOWER2_MARGIN (rows = tower2_exp.csv dicts); TOWER2_FIRST without
    history. Earning = total exp at 'king' - at 'tower2' (levels through the exp table). size = this batch's number
    of apprentices: batches of that size count when there are any (2026-11-01: with 3 instead of 4 both 伏地魔1 and
    伏地魔4 earned 3-4万 less)."""
    need = need or _explib()
    base = lambda lv, e: sum(need[k] for k in range(1, lv)) + e          # noqa: E731
    at = {}
    for r in rows:
        if r['master'] == master:
            at.setdefault(r['logid'], {}).setdefault(r['point'], {})[r['name']] = base(int(r['level']), int(r['exp']))
    gains = []                        # (team size, smallest earning) per batch, oldest first
    for logid, pts in at.items():
        g = [pts['king'][n] - pts['tower2'][n] for n in pts.get('king', {}) if n in pts.get('tower2', {})]
        if g:
            gains.append((len(pts['tower2']), min(g)))
    same = [g for k, g in gains if k == size]
    gains = same or [g for _, g in gains]
    if not gains:
        return TOWER2_FIRST
    e = need[39] - min(gains[-TOWER2_LOOKBACK:]) + TOWER2_MARGIN
    return f'39+{max(0, min(e, need[39] - 1))}'


def _tower2_rows(path=EXP_CSV):
    import csv
    try:
        with open(path, encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _check_name(team, prefix):
    for n in (f'{prefix}1', f'{prefix}{4 * MASTER_SLOTS}'):          # role slots 1..4 -> suffix 1..16
        try:
            ok = n.isalnum() and 1 <= len(n.encode('gbk')) <= 15
        except UnicodeEncodeError:
            ok = False
        if not ok:
            raise ValueError(f'line.toml [team.{team}] names = {prefix!r}: 角色名要 1..15 字节的字母/数字/汉字（{n}）')


def load_teams(path=CONFIG):
    raw = tomllib.loads(path.read_text(encoding='utf-8')).get('team', {})
    teams = {}
    for k, v in raw.items():
        levels = v.get('levels', {})
        bad = set(levels) - set(LEVELS)
        if bad:
            raise ValueError(f'line.toml [team.{k}] levels 里没有这些段: {sorted(bad)}（只有 {list(LEVELS)}）')
        low = {a: b for a, b in levels.items() if b < MIN_LEVELS.get(a, 0)}
        if low:
            raise ValueError(f'line.toml [team.{k}] levels {low} 太低：最低 {MIN_LEVELS}（任务 224 要 28 级才能接）')
        acc = v.get('accounts', 0)
        listed = tuple(acc) if isinstance(acc, list) else ()
        if listed and len(listed) != MASTER_SLOTS:
            raise ValueError(f'line.toml [team.{k}] accounts 要正好 {MASTER_SLOTS} 个: {listed}')
        route = v.get('route', 'bplus')
        if route not in ROUTE_NAMES:
            raise ValueError(f'line.toml [team.{k}] route = {route!r}：只有 {ROUTE_NAMES}')
        tower2 = str(v.get('tower2', TOWER2[route]))
        if tower2 != 'auto' and not re.fullmatch(r'\d+(\+\d+)?', tower2):
            raise ValueError(f'line.toml [team.{k}] tower2 = {tower2!r}：写 40、38+200000 或 auto')
        t = Team(v['master'], int(v.get('slot', 0)), int(v.get('gold', GOLD)), int(v.get('tower1', TOWER1)),
                 0 if listed else int(acc), v.get('names', ''), tuple(sorted((a, int(b)) for a, b in levels.items())),
                 listed, route, tower2, v.get('stat', '体质'), v.get('job', '战士'), int(v.get('revive', 0)),
                 bool(v.get('tidy', False)), int(v.get('first', 1)))
        if t.job not in JOBS:
            raise ValueError(f'line.toml [team.{k}] job = {t.job!r}：只有 {JOBS}（默认 战士 = 勇者线，术士 = 元素使线）')
        if t.stat not in TALENT_STATS:
            raise ValueError(f'line.toml [team.{k}] stat = {t.stat!r}：只有 {TALENT_STATS}')
        if not t.accounts and not listed and not 0 <= t.slot < 4:
            raise ValueError(f'line.toml [team.{k}] slot {t.slot} 不在 0..3')
        if bool(t.accounts or listed) != bool(t.names):
            raise ValueError(f'line.toml [team.{k}] accounts 和 names 要一起写')
        if t.names:
            _check_name(k, t.names)
        teams[k] = t
    return teams


TEAMS = load_teams()


def check_teams(names, teams=None):
    """Teams run together must exist and use different account groups (same slot = same accounts and names)."""
    teams = TEAMS if teams is None else teams
    missing = [n for n in names if n not in teams]
    if missing:
        raise ValueError(f'line.toml 里没有这些队: {missing}')
    seen = {}
    for n in names:
        for acc in teams[n].account_list:
            if acc in seen:
                raise ValueError(f'队 {seen[acc]} 和 {n} 都用账号 {acc}，不能一起跑')
            seen[acc] = n
    masters = [teams[n].master for n in names]
    if len(set(masters)) != len(masters):
        raise ValueError(f'同一个师傅出现在两队: {masters}')


# a name the server refused (0x4003 result 3: 敏感词, user 2026-11-01:「J8 是谐音梗」) -> the name make_apprentices
# created instead; every later step of the batch reads it through batch_names
ALIAS_FILE = Path(__file__).resolve().parent.parent / 'logs' / 'name_alias.json'


def aliases(path=ALIAS_FILE):
    import json
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def batch_names(team, batch):
    t = TEAMS[team]
    if t.names:
        names = [f'{t.names}{4 * (batch - 1) + t.first - 1 + i}' for i in range(1, 5)]
    else:
        o = 16 * (batch - 1) + t.slot * 4
        names = [f'亿万{o + i}' for i in range(1, 5)]
    al = aliases()
    return [al.get(n, n) for n in names]


def plan_skip(team, batch, stuck):
    """Names left out of a batch: the stuck ones (bound to the master) and, since each takes a master slot, as many
    of this batch's last names."""
    names = batch_names(team, batch)
    room = max(0, MASTER_SLOTS - len(stuck))
    return list(stuck) + names[room:]


def logid(team, batch):
    return f'r4{team}' if batch == 1 else f'r4{team}_b{batch}'


@dataclass
class Batch:
    team: str
    batch: int
    skip: list = field(default_factory=list)      # names left out (plan_skip + any excluded during the run)

    @property
    def master(self):
        return TEAMS[self.team].master

    @property
    def tower1(self):
        return TEAMS[self.team].tower1

    def level(self, key):
        return TEAMS[self.team].level(key)

    @property
    def route(self):
        return TEAMS[self.team].route

    @property
    def job(self):               # route.route_of: 术士 -> the 元素使 line, anything else the 勇者 line as before
        return TEAMS[self.team].job

    @property
    def tower2(self):
        t2 = TEAMS[self.team].tower2
        return tower2_auto(self.master, _tower2_rows(), size=len(self.apprentices)) if t2 == 'auto' else t2

    @property
    def all_names(self):
        return batch_names(self.team, self.batch)

    @property
    def apprentices(self):
        return [n for n in self.all_names if n not in self.skip]

    @property
    def pairs(self):
        """'capNN:亿万M' for the kept apprentices (account of their team slot, whatever was skipped)."""
        accs = TEAMS[self.team].account_list
        return [f'{accs[i]}:{n}' for i, n in enumerate(self.all_names) if n not in self.skip]

    @property
    def prev_names(self):
        """The batch before, skipped ones too: they log in with the same accounts and must be closed first."""
        return batch_names(self.team, self.batch - 1) if self.batch > 1 else []

    @property
    def logid(self):
        return logid(self.team, self.batch)

    @property
    def state_file(self):
        return f'state_{self.logid}.json'

    def env(self):
        """SHITU_* for the stage scripts (common.py reads them), LOGID / PAIRS like r4_env.sh."""
        return {
            'SHITU_STATE': self.state_file,
            'SHITU_MASTERS': self.master,
            'SHITU_APPRENTICES': ','.join(self.apprentices),
            'SHITU_GOLD': str(TEAMS[self.team].gold),
            'SHITU_STAT': TEAMS[self.team].stat,
            'SHITU_JOB': TEAMS[self.team].job,
            'SHITU_REVIVE': str(TEAMS[self.team].revive),
            'SHITU_TIDY': '1' if TEAMS[self.team].tidy else '0',
            'SHITU_SCROLLS': str(SCROLLS),
            'LOGID': self.logid,
            'PAIRS': ' '.join(self.pairs),
            'BATCH': str(self.batch),
        }
