"""Who is in a batch: masters, apprentice names, accounts, log ids, the env every script gets.

Teams come from line.toml [team.<name>] (master, slot, gold). Same rules as r4_env.sh for slots 0..3 (tests/test_line.py
checks the two agree for teams a..d), so old logs / state files keep their names:
  batch N, slot k (0..3) = 亿万(16(N-1)+4k+1 .. +4); team slot i uses account cap(21+4k+i), role slot N.
  LOGID r4<team> for batch 1, r4<team>_b<N> after (the team name, not the slot: a new master = a new name).
A team may instead name its own accounts and role names (2026-10-29 exp-map trial: cap37.. and Opus55A1..):
  accounts = first account number (the team uses capN..capN+3), names = name prefix: batch N, account i -> prefix(4(N-1)+i).
  levels = where this team leaves each map (keys of LEVELS; unset = the v5 route's level).
"""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MASTER_SLOTS = 4                 # a master holds 4 apprentices at most (excluded ones stay bound and take a slot)
SCROLLS = 20                     # 回城卷 each apprentice gets from the master (SHITU_SCROLLS)
CONFIG = Path(__file__).with_name('line.toml')
# the v5 route leaves 轮回之城 at 15, 暗影迷城 at 19, 八阵图 at 23 (maze_train) and 25 (bazhen25), 遗忘洞穴 at 28
LEVELS = {'lunhui': 15, 'maze1': 19, 'maze2': 23, 'bazhen': 25, 'cave': 28}
# 任务 224 遗忘洞穴的恐慌 (the q224 / snake steps right after the cave) is taken at 28 only: below it 大个王 answers
#「好吧」 and nothing else (2026-10-29 ob team left the cave at 27 and q224 failed)
MIN_LEVELS = {'cave': 28}


@dataclass(frozen=True)
class Team:
    master: str
    slot: int                    # which 4 accounts / which names (0..3)
    gold: int                    # starting gold the master hands out
    tower1: int = 33             # 通天塔一区 up to this level, then 二区
    accounts: int = 0            # first cap account number (0 = the slot's: 21 + 4 * slot)
    names: str = ''              # role name prefix ('' = 亿万 numbered by the slot)
    levels: tuple = ()           # ((key, level), ...) overrides of LEVELS

    @property
    def first_account(self):
        return self.accounts or 21 + 4 * self.slot

    def level(self, key):
        return dict(LEVELS, **dict(self.levels))[key]


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
        t = Team(v['master'], int(v.get('slot', 0)), int(v.get('gold', 50000)), int(v.get('tower1', 33)),
                 int(v.get('accounts', 0)), v.get('names', ''), tuple(sorted((a, int(b)) for a, b in levels.items())))
        if not t.accounts and not 0 <= t.slot < 4:
            raise ValueError(f'line.toml [team.{k}] slot {t.slot} 不在 0..3')
        if bool(t.accounts) != bool(t.names):
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
        for acc in range(teams[n].first_account, teams[n].first_account + MASTER_SLOTS):
            if acc in seen:
                raise ValueError(f'队 {seen[acc]} 和 {n} 都用账号 cap{acc}，不能一起跑')
            seen[acc] = n
    masters = [teams[n].master for n in names]
    if len(set(masters)) != len(masters):
        raise ValueError(f'同一个师傅出现在两队: {masters}')


def batch_names(team, batch):
    t = TEAMS[team]
    if t.names:
        return [f'{t.names}{4 * (batch - 1) + i}' for i in range(1, 5)]
    o = 16 * (batch - 1) + t.slot * 4
    return [f'亿万{o + i}' for i in range(1, 5)]


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
    def all_names(self):
        return batch_names(self.team, self.batch)

    @property
    def apprentices(self):
        return [n for n in self.all_names if n not in self.skip]

    @property
    def pairs(self):
        """'capNN:亿万M' for the kept apprentices (account of their team slot, whatever was skipped)."""
        n0 = TEAMS[self.team].first_account
        return [f'cap{n0 + i}:{n}' for i, n in enumerate(self.all_names) if n not in self.skip]

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
            'SHITU_SCROLLS': str(SCROLLS),
            'LOGID': self.logid,
            'PAIRS': ' '.join(self.pairs),
            'BATCH': str(self.batch),
        }
