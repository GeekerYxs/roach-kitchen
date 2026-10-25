"""Read one alt's client into an AltObs (phase.py) — the observation every stage saves before deciding."""
from provisioner.world import (item_count, read_bag, read_bag_capacity, read_equipment, read_gold, read_level, read_quest,
                               read_team)

from . import items

from .phase import (COAST_MAP, DISH_ITEM, LEGS_ITEM, POTATO_ITEM, QUEST_ACTIVE, QUEST_DONE, QUEST_ID, QUEST_NONE, RUMPS_ITEM,
                    SCROLL_ITEM, AltObs, bag_blocked)


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
    dishes, legs, rumps = item_count(bag, DISH_ITEM), item_count(bag, LEGS_ITEM), item_count(bag, RUMPS_ITEM)
    capacity = read_bag_capacity(mem)
    free = None if capacity is None else max(0, capacity - len(bag))
    junk = 0
    if (dishes or quest.done) and world.map_id == COAST_MAP:    # only the junk run (phase.SELL_JUNK) needs it; quest
        # done counts too: without the 料理 trade (phase.DISH_TRADE off) the sale must not hang on the 料理 being there
        worn = read_equipment(mem)
        if worn is None:
            return None
        junk = items.junk_count(bag, worn, items.table())
    elif world.map_id == COAST_MAP and bag_blocked(legs, rumps, free):
        junk = len(items.sell_slots(bag, items.table()))   # mid-chain sale: the bag only, the alt keeps its gear
    return AltObs(char_id=world.char_id, map_id=world.map_id, level=level, gold=read_gold(mem),
                  team_leader=team.leader, quest=quest_state(quest),
                  legs=legs, rumps=rumps, dishes=dishes, scrolls=item_count(bag, SCROLL_ITEM),
                  potatoes=item_count(bag, POTATO_ITEM), junk=junk, bag_free=free)
