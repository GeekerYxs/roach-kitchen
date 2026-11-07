"""Quest progress by the LENGTH of a quest's step bytes, never by their values.

world.read_quest gives steps = one status byte per step up to the current one (2 = finished, 1 = current), so
len(steps) is the number of steps reached. The bytes of steps the server skipped are not reliable: after a relog
(2026-11-07 r4ys25, 奥德赛25-28, task 25) the same apprentices read (0,0,1) before and (0,2,1) / (0,46,1) /
(0,221,1) / (125,0,2,3,1) after. So a check like `tuple(q.steps) == (0, 0, 1)` silently fails after a relog, and
the line loops; `len(q.steps)` is what r4_util.need ('U need QID N') has used all along.

  at(q, n)    the quest is active and exactly at its n-th step (len(steps) == n)
  past(q, n)  the quest is done, or active with at least n steps (the same test as `U need QID N`)

Item farms use past() to count an apprentice who already handed the items in as done (2026-11-07: 奥德赛25 had
handed in its 3 books, the rerun of shuidi.py waited for books it would never get again, the team farmed for ever).
"""

# Steps (len) of the class-change quests 24 (战士) / 25 (术士), recorded 2026-10-27 / 2026-11-02:
#   taken (0,0,1) = 3 -> handed the 拳手 / books in (0,0,2,0,1) = 5 -> 神仙姐姐 -> done
CLASS_ITEMS, CLASS_FAIRY = 3, 5


def at(q, n):
    return q is not None and q.active and not q.done and len(q.steps) == n


def past(q, n):
    return q is not None and (q.done or (q.active and len(q.steps) >= n))


def parse(spec):
    """'187:8' -> (187, 8): quest QID past step N (farm.py --past, U have alternatives)."""
    qid, _, n = spec.partition(':')
    return int(qid), int(n)
