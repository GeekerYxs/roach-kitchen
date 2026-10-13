"""Stage 8: an alt on 平静海岸2区 (map 81) with 10 legs + 20 rumps hands quest 78 in to 海子 (NPC 403) and gets
one 美味小强料理 27002.

Entry: python -m factory.handin [factory.toml]
Same frame as stage 6 (factory/quest.py: one thread per alt, no team, walk -> click -> menu by labels); only the
decision and the proof differ. Per tick: read -> decide -> at most one action -> verify.
  1. walk next to 海子 if needed (the coast teams disband at (1750,1300), about 110 px away, so usually no walk)
  2. click the NPC, then follow the menu: 飞刀王的晚餐 -> 当然，给你。 -> 谢谢！
  3. verified when quest 78 is in the done table AND the bag holds a 料理; close a dialog left open
Restart at any point continues from the observed state (quest already done -> done, nothing sent).
decide() is pure (tests/test_factory_handin.py).

Menu labels from the old runtime (Gemini mwxqll_game reference_runtime/muse_cycle.py handin(), not yet re-checked
by us): 飞刀王的晚餐 / 当然，给你。 / 谢谢！. Which of the last two pages actually completes the quest is not known,
so both are 'give' steps (pending mark written before each); the done table decides.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

from provisioner.world import item_count, read_bag, read_quest, read_team

from .config import ROOT, load_settings
from .phase import COAST_MAP, DISH_ITEM, LEGS_ITEM, LEGS_NEEDED, QUEST_ID, RUMPS_ITEM, RUMPS_NEEDED
from .quest import (CONFIRM_WAIT, MAX_SELECTS, SELECT_RETRY, Decision, Memo, QuestJob, approach, blocked,
                    menu_choice)
from .runner import run_stage

ACTION = 'handin78'
MENU = ('飞刀王的晚餐', '当然，给你', '谢谢')
GIVE_LABELS = MENU[1:]


@dataclass(frozen=True)
class Items:
    legs: int
    rumps: int
    dishes: int


def read_items(mem):
    bag = read_bag(mem)
    if bag is None:
        return None
    return Items(item_count(bag, LEGS_ITEM), item_count(bag, RUMPS_ITEM), item_count(bag, DISH_ITEM))


def decide(world, quest, team, items, alt_row, memo, now):
    """world: WorldState | None; quest: Quest | None; team: Team | None; items: Items | None; alt_row: alts row."""
    if world is None or quest is None or team is None or items is None:
        return Decision('wait', '加载中')
    acted = memo.accept_at is not None or alt_row['pending_action'] == ACTION
    if quest.done:
        if world.dialog and not world.in_battle and memo.closed_at is None:
            return Decision('close', '任务已交，关掉对话框', 0)
        if items.dishes > 0:
            if acted:
                return Decision('verified', f'任务 {QUEST_ID} 已完成，背包料理 {items.dishes} 个')
            return Decision('done', f'任务 {QUEST_ID} 已交过，背包料理 {items.dishes} 个')
        if not acted:
            return Decision('done', f'任务 {QUEST_ID} 已交过，料理已不在背包')
        if memo.accept_at is not None and now - memo.accept_at < CONFIRM_WAIT:
            return Decision('wait', '任务已完成，等料理进背包')
        return Decision('fail', f'任务 {QUEST_ID} 已完成，但背包里没有料理')
    if not quest.active:
        return Decision('fail', f'没有接任务 {QUEST_ID}')
    if world.map_id != COAST_MAP:
        return Decision('fail', f'不在平静海岸2区（地图 {world.map_id}）')
    if team.members:
        return Decision('fail', f'在队伍里（队长 {team.leader}），交任务要单人')
    if memo.accept_at is None and (items.legs < LEGS_NEEDED or items.rumps < RUMPS_NEEDED):
        return Decision('fail', f'材料不齐：腿 {items.legs}/{LEGS_NEEDED} 鸡屁股 {items.rumps}/{RUMPS_NEEDED}')
    d = blocked(world, memo, now)
    if d:
        return d
    if world.dialog:
        choice = menu_choice(world.dialog, MENU)
        if choice == 'ambiguous' or (choice is None and memo.accept_at is None):
            return Decision('fail', f'海子对话框选项不认识: {world.dialog.options}')
        if choice is not None:
            if world.dialog.text == memo.select_text and now - memo.select_at < SELECT_RETRY:
                return Decision('wait', '已选择，等下一页')
            if memo.selects >= MAX_SELECTS:
                return Decision('fail', f'对话选了 {memo.selects} 次还没交上任务')
            kind = 'give' if any(label in choice[1] for label in GIVE_LABELS) else 'select'
            return Decision(kind, f'选择「{choice[1]}」', choice[0])
    if memo.accept_at is not None:
        if now - memo.accept_at < CONFIRM_WAIT:
            return Decision('wait', '已交材料，等任务完成')
        return Decision('unconfirmed', f'交材料 {CONFIRM_WAIT:.0f}s 后任务 {QUEST_ID} 还没完成')
    return approach(world, memo, now)


class HandinJob(QuestJob):
    action = ACTION

    def _decide(self, mem, world, row, memo, now):
        return decide(world, read_quest(mem, QUEST_ID), read_team(mem), read_items(mem), row, memo, now)


def main():
    settings = load_settings(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'factory.toml')
    return run_stage('handin', settings, lambda c, account, slot, log_: HandinJob(c, account, slot, settings, log_),
                     map_id=COAST_MAP, map_name='平静海岸2区')


if __name__ == '__main__':
    sys.exit(main())
