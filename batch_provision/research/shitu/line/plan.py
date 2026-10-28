"""Who is in a batch: masters, apprentice names, accounts, log ids, the env every script gets.

Same rules as r4_env.sh (tests/test_line.py checks the two agree), so old logs / state files keep their names:
  team a..d = 伏地魔1..4; batch N, team k (0..3) = 亿万(16(N-1)+4k+1 .. +4); team slot i uses account cap(n0+i),
  role slot N (n0: a 21, b 25, c 29, d 33). LOGID r4<team> for batch 1, r4<team>_b<N> after.
"""
from dataclasses import dataclass, field

MASTER_SLOTS = 4                 # a master holds 4 apprentices at most (excluded ones stay bound and take a slot)
TEAMS = {                        # team -> (master, first account number, starting gold the master hands out)
    'a': ('伏地魔1', 21, 50000),
    'b': ('伏地魔2', 25, 50000),
    'c': ('伏地魔3', 29, 50000),
    'd': ('伏地魔4', 33, 10000),
}
SCROLLS = 20                     # 回城卷 each apprentice gets from the master (SHITU_SCROLLS)


def batch_names(team, batch):
    k = 'abcd'.index(team) * 4
    o = 16 * (batch - 1) + k
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
        return TEAMS[self.team][0]

    @property
    def all_names(self):
        return batch_names(self.team, self.batch)

    @property
    def apprentices(self):
        return [n for n in self.all_names if n not in self.skip]

    @property
    def pairs(self):
        """'capNN:亿万M' for the kept apprentices (account of their team slot, whatever was skipped)."""
        n0 = TEAMS[self.team][1]
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
            'SHITU_GOLD': str(TEAMS[self.team][2]),
            'SHITU_SCROLLS': str(SCROLLS),
            'LOGID': self.logid,
            'PAIRS': ' '.join(self.pairs),
            'BATCH': str(self.batch),
        }
