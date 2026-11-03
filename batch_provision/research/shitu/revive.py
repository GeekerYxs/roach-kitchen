"""In battle, the master revives an apprentice that went down (user 2026-11-02, 元素使 team: 体质 3, everything in 敏捷).

Turned on by env SHITU_REVIVE = the item id (美味小强料理 27002, box02 holds them); lunhui15.Caster asks Reviver first
on every tick of a master, so every master battle loop (well, 轮回, mazes, towers, quests) gets it.

User's rule: an apprentice is down -> the master uses the item on it at once, and the master's PET must not cast that
round (its spell would kill the monsters and end the battle before the apprentice is up). If the pet already acted,
never mind. A revive that does not work is tried MAX_TRIES times, then left alone: the battle ends, the apprentice is
sent to the village, and the fallback is everybody scrolls home and the step starts again from the spawn.

Mechanics: an apprentice's own battle memory gives its client position (cached per battle); every member of a team
stands on the same side, so that position is the master's target too, and the dead flag is read from the MASTER's
battle view at that position. First live revive (2026-11-02 23:15, 通天二, 元素使04): read from the apprentice's own
client the death showed 0.12 s too late, the master's 扫射 went out first at the new round, killed the last monsters
and the battle ended with 元素使04 down (the 0x1003 never took effect, 99 items left); the master's client had the
server's 0x4112 for that position 5.5 s earlier. The item goes through the client's own Lua
function UseItemToFighter(target client pos, bag slot) (RVA 0x13310 in 2.101, stdcall, sends 0x1003; found by its
Lua registration next to CastSkillToFighter 0x134E0). The pet gets 防御 (fight action 4) instead of nothing, so the
round does not sit out the timer.
"""
import os
from dataclasses import dataclass

import trial_run as t
from provisioner import native, world as w

ITEM = int(os.environ.get('SHITU_REVIVE', '0') or 0)
RVA_USE_ITEM_TO_FIGHTER = 0x13310
FIGHT_DEFEND = 4
MAX_TRIES = 3
STICKY = 1.5         # s: a death seen this recently still counts (the flag blinks off as a new round starts, 23:18)
ROUND_GAP = 4.0      # s: one item per apprentice per round (the master's SP changes again right after acting, so a
                     # changed SP is not a new round: 23:18:58 the item went out twice 0.6 s apart)


@dataclass(frozen=True)
class Plan:
    use: tuple = ()          # (name, client pos) of the apprentice to revive now, or ()
    pet_defend: bool = False
    block: bool = False      # True: the caller sends nothing else this tick


def decide(me, pet, me_last, pet_last, down, tries, waiting=()):
    """me / pet = the master's Fighters (or None), *_last = the SP the Caster last acted on, down = [(name, pos)] of
    dead apprentices, tries = {name: revives already sent}, waiting = names whose item went out this round -> Plan."""
    down = [(n, p) for n, p in down if tries.get(n, 0) < MAX_TRIES]
    if not down or me is None or me.dead:
        return Plan()
    fresh = [(n, p) for n, p in down if n not in waiting]
    if not fresh or me.sp == me_last:        # item already out this round / the master already acted: send nothing
        return Plan(block=True)
    return Plan(use=fresh[0], pet_defend=pet is not None and not pet.dead and pet.sp != pet_last, block=True)


class Reviver:
    def __init__(self, c, names):
        self.c = c
        self.apps = [t.Client(n) for n in names]
        self.tries, self.pos, self.seen, self.used = {}, {}, {}, {}
        self.flag = {}                       # last dead flag per apprentice: flips are logged (first live runs)

    def down(self, now):
        out = []
        for a in self.apps:
            if a.name not in self.pos:
                b = w.read_battle(a.mem)
                if b and b.me:
                    self.pos[a.name] = b.me.pos
            pos = self.pos.get(a.name)
            f = w.read_fighter(self.c.mem, pos) if pos is not None else None
            dead = bool(f and f.dead)
            if pos is not None and dead != self.flag.get(a.name, False):
                me = w.read_battle(self.c.mem)
                t.say(f'[{self.c.name}] 看到 {a.name}（位置 {pos}）{"倒地" if dead else "站着"}，师傅蓄力点 '
                      f'{me.me.sp if me and me.me else None}')
                self.flag[a.name] = dead
            if dead:
                self.seen[a.name] = now
            if pos is not None and now - self.seen.get(a.name, -1e9) < STICKY:
                out.append((a.name, pos))
        return out

    def slot(self):
        return next((s.slot for s in w.read_bag(self.c.mem) if s.item_id == ITEM), None)

    def tick(self, battle, caster, now):
        """-> True when the Caster must not act on this tick."""
        if battle is None:
            self.tries, self.pos, self.seen, self.used, self.flag = {}, {}, {}, {}, {}
            return False
        down = self.down(now)
        if not down:
            return False
        waiting = {n for n, at in self.used.items() if now - at < ROUND_GAP}
        plan = decide(battle.me, battle.pet, caster.me.last_sp, caster.pet.last_sp, down, self.tries, waiting)
        if plan.use:
            slot = self.slot()
            if slot is None:
                t.say(f'[{self.c.name}] 没有复活道具 {ITEM} 了，{plan.use[0]} 救不了')
                self.tries[plan.use[0]] = MAX_TRIES
                return False
            name, pos = plan.use
            self.tries[name] = self.tries.get(name, 0) + 1
            self.used[name] = now
            native.call(self.c.game.session, RVA_USE_ITEM_TO_FIGHTER, pos, slot)
            caster.me.record(battle.me.sp, now)
            t.say(f'[{self.c.name}] {name} 倒地（位置 {pos}），用复活道具（第 {self.tries[name]} 次）')
            if plan.pet_defend:
                self.c.game.fight_command(FIGHT_DEFEND, is_pet=True, target=battle.pet.pos)
                caster.pet.record(battle.pet.sp, now)
                t.say(f'[{self.c.name}] 宠物这回合防御，不施法')
        if plan.block and not plan.pet_defend and battle.pet and not battle.pet.dead and                 battle.pet.sp != caster.pet.last_sp:
            # 23:56 元素使02: the item went out before the pet's SP changed, nobody commanded the pet later, the
            # monsters died that round and 元素使02 was sent home; so while anybody is down, the pet defends as soon
            # as its own turn comes
            self.c.game.fight_command(FIGHT_DEFEND, is_pet=True, target=battle.pet.pos)
            caster.pet.record(battle.pet.sp, now)
            t.say(f'[{self.c.name}] 有人倒地，宠物防御（蓄力点 {battle.pet.sp}）')
        return plan.block
