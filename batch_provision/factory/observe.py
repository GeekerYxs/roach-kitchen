"""Read one alt's client into an AltObs (phase.py) — the observation every stage saves before deciding."""
from provisioner.world import item_count, read_bag, read_equipment, read_gold, read_level, read_quest, read_team

from . import items

from .phase import (COAST_MAP, DISH_ITEM, LEGS_ITEM, POTATO_ITEM, QUEST_ACTIVE, QUEST_DONE, QUEST_ID, QUEST_NONE, RUMPS_ITEM,
                    SCROLL_ITEM, AltObs)


def quest_state(quest):
    """provisioner.world.Quest -> QUEST_NONE / QUEST_ACTIVE / QUEST_DONE."""
    if quest.done:
        return QUEST_DONE
    return QUEST_ACTIVE if quest.active else QUEST_NONE


def observe(mem, world):
    """AltObs, or None while anything is still loading."""
    if world is None:
        return None
    level, bag, team, quest = read_level(mem), read_bag(mem), read_team(mem), read_quest(mem, QUEST_ID)
    if level is None or bag is None or team is None or quest is None:
        return None
    dishes = item_count(bag, DISH_ITEM)
    junk = 0
    if dishes and world.map_id == COAST_MAP:        # only the junk run (phase.SELL_JUNK) needs it
        worn = read_equipment(mem)
        if worn is None:
            return None
        junk = items.junk_count(bag, worn, items.table())
    return AltObs(char_id=world.char_id, map_id=world.map_id, level=level, gold=read_gold(mem),
                  team_leader=team.leader, quest=quest_state(quest),
                  legs=item_count(bag, LEGS_ITEM), rumps=item_count(bag, RUMPS_ITEM),
                  dishes=dishes, scrolls=item_count(bag, SCROLL_ITEM),
                  potatoes=item_count(bag, POTATO_ITEM), junk=junk)
