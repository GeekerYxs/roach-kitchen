"""Who is in a batch: masters, apprentice names, accounts, log ids, the env every script gets.

Teams come from line.toml [team.<name>] (master, slot, gold). Same rules as r4_env.sh for slots 0..3 (tests/test_line.py
checks the two agree for teams a..d), so old logs / state files keep their names:
  batch N, slot k (0..3) = 亿万(16(N-1)+4k+1 .. +4); team slot i uses account cap(21+4k+i), role slot N.
  LOGID r4<team> for batch 1, r4<team>_b<N> after (the team name, not the slot: a new master = a new name).
"""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MASTER_SLOTS = 4                 # a master holds 4 apprentices at most (excluded ones stay bound and take a slot)
SCROLLS = 20                     # 回城卷 each apprentice gets from the master (SHITU_SCROLLS)
CONFIG = Path(__file__).with_name('line.toml')


@dataclass(frozen=True)
class Team:
    master: str
    slot: int                    # which 4 accounts / which names (0..3)
    gold: int                    # starting gold the master hands out

    @property
    def first_account(self):
        return 21 + 4 * self.slot


def load_teams(path=CONFIG):
    raw = tomllib.loads(path.read_text(encoding='utf-8')).get('team', {})
    teams = {k: Team(v['master'], int(v['slot']), int(v.get('gold', 50000))) for k, v in raw.items()}
    for k, t in teams.items():
        if not 0 <= t.slot < 4:
            raise ValueError(f'line.toml [team.{k}] slot {t.slot} 不在 0..3')
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
        s = teams[n].slot
        if s in seen:
            raise ValueError(f'队 {seen[s]} 和 {n} 用同一组账号（slot {s}），不能一起跑')
        seen[s] = n
    masters = [teams[n].master for n in names]
    if len(set(masters)) != len(masters):
        raise ValueError(f'同一个师傅出现在两队: {masters}')


def batch_names(team, batch):
    o = 16 * (batch - 1) + TEAMS[team].slot * 4
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
