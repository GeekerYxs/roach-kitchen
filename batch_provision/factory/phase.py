"""Which phase an alt is in, derived ONLY from what we can observe now plus a few ledger facts.

No "current step" is stored anywhere: after a crash, relog or restart the same rules put the alt back
where it belongs (FACTORY_DESIGN.md section 4). Everything here is pure and unit-tested
(tests/test_factory_phase.py); reading the facts from the game is the job of later stages.
"""
from dataclasses import dataclass

NOVICE_MAP, VILLAGE_MAP, MEADOW_MAP, WELL_MAP, COAST_MAP = 271, 1, 130, 651, 81
TARGET_LEVEL = 11
HANDIN_LEVEL = 18               # factory.toml handin_level (user, 2026-10-25): materials done -> the coast team farms
                                # on until this level, then hand in; config.load_settings sets it for the process
TELEPORT_FEE = 190
GOLD_GIFT = 500                 # covers two teleports (e.g. died at the coast and must come back)
GOLD_TOPUP_BELOW = 2 * TELEPORT_FEE   # user, 2026-10-12: keep enough for two teleports, top up below 380
LEGS_ITEM, RUMPS_ITEM, DISH_ITEM = 10571, 10572, 27002
LEGS_NEEDED, RUMPS_NEEDED = 10, 20
MEAT_ITEM, POTATO_ITEM, SCROLL_ITEM = 30188, 32004, 9801
POTATO_SECONDS = 3600           # one 地瓜 = 1 h double exp
POTATOES_AT_START = 2           # user, 2026-10-25: eat two 地瓜 in a row when the well team forms (was one)
POTATO_RENEW = POTATOES_AT_START * POTATO_SECONDS - 5 * 60   # still below 11 this long after eating -> eat again
SHOE_COOLDOWN = 3600            # 飞鞋 return: once per hour, server-checked

QUEST_ID = 78                   # 飞刀王的晚餐
QUEST_NONE, QUEST_ACTIVE, QUEST_DONE = 'none', 'active', 'done'

# Station roles (whose team an alt is in decides what it is doing)
WELL, DISPATCHER, COAST, RECEIVER = 'well', 'dispatcher', 'coast', 'receiver'

# Phases
NOVICE = 'novice'
EAT_MEAT = 'eat_meat'
RECORD_SHOE = 'record_shoe'
QUEUE_WELL = 'queue_well'
LEVELING = 'leveling'
RETURN_HOME = 'return_home'
QUEUE_TRANSPORT = 'queue_transport'
TRANSPORTING = 'transporting'
WAIT_DISBAND = 'wait_disband'
LEAVE_TEAM = 'leave_team'
ACCEPT_QUEST = 'accept_quest'
QUEUE_COAST = 'queue_coast'
FARMING = 'farming'
HANDIN = 'handin'
SELL_JUNK = 'sell_junk'         # after the hand-in: take the gear off, sell it and the loot at 花袭人 (user, 2026-10-20)
QUEUE_RECEIVER = 'queue_receiver'
DELETE = 'delete'
DELETED = 'deleted'             # server accepted the delete (stage 10); set by db.mark_deleted, never derived
QUARANTINED = 'quarantined'
UNKNOWN = 'unknown'

# factory.toml dish_trade (user, 2026-10-25: 美味小强料理 cannot be traded for now). Off: the 料理 stays in the
# alt's bag and is deleted with it; the receiver only collects the gold. config.load_settings sets this for the process.
DISH_TRADE = False

QUEUES = {QUEUE_WELL: WELL, QUEUE_TRANSPORT: DISPATCHER, QUEUE_COAST: COAST, QUEUE_RECEIVER: RECEIVER}


@dataclass(frozen=True)
class AltObs:
    """One read of the alt's own client. None in a field = could not be read this tick."""
    char_id: int
    map_id: int
    level: int
    gold: int | None
    team_leader: int            # leader char_id, 0 = not in a team
    quest: str                  # QUEST_NONE / QUEST_ACTIVE / QUEST_DONE (task 78)
    legs: int = 0
    rumps: int = 0
    dishes: int = 0
    scrolls: int = 0
    potatoes: int = 0
    junk: int = 0               # bag slots + worn items the shop would buy (factory/items.py alt rule)
    bag_free: int | None = None     # empty bag slots, None = unread

    @property
    def materials_done(self):
        return self.legs >= LEGS_NEEDED and self.rumps >= RUMPS_NEEDED

    @property
    def no_room(self):
        return bag_blocked(self.legs, self.rumps, self.bag_free)


def bag_blocked(legs, rumps, free):
    """No empty slot for a material the alt does not hold yet: the drop is lost and the count never moves (live
    2026-10-21: mw302r6 came out of the well with a full bag, cap07 farmed with it at 腿0 屁股0 for 2 h 15 min).
    A material already held only grows its stack."""
    return free == 0 and (legs == 0 or rumps == 0)


@dataclass(frozen=True)
class Ledger:
    """Facts only our own successful actions can tell (not readable from the game, or not yet)."""
    meat_at: float | None = None
    shoe_recorded_at: float | None = None
    shoe_used_at: float | None = None
    potato_at: float | None = None
    sold_at: float | None = None    # the junk run finished once (items a shop refuses must not loop it)
    quarantined: bool = False


@dataclass(frozen=True)
class Plan:
    phase: str
    reason: str
    needs_gold: bool = False    # in the village and short of the teleport fee: the dispatcher tops it up


def needs_gold(obs):
    """In the village with less than two teleports' worth: the dispatcher tops it up (one teleport still
    needs only TELEPORT_FEE; the dispatcher can transport an alt that has the fee but is due a top-up)."""
    return obs.map_id == VILLAGE_MAP and obs.gold is not None and obs.gold < GOLD_TOPUP_BELOW


def derive_phase(obs, ledger, stations, dish_trade=None):
    """stations: {char_id: role} of the resident station characters. dish_trade: None = DISH_TRADE."""
    if dish_trade is None:
        dish_trade = DISH_TRADE
    if ledger.quarantined:
        return Plan(QUARANTINED, '已隔离，等人工处理')
    if obs.map_id == NOVICE_MAP:
        return Plan(NOVICE, '在菜鸟训练营')
    gold = needs_gold(obs)
    leader_role = stations.get(obs.team_leader) if obs.team_leader else None
    if obs.team_leader and leader_role is None:
        return Plan(LEAVE_TEAM, f'在陌生队伍里（队长 {obs.team_leader}）')

    if obs.dishes > 0 and dish_trade:
        if obs.map_id == COAST_MAP:
            if obs.team_leader:
                return Plan(LEAVE_TEAM, '有料理但还在队里')
            if obs.junk and ledger.sold_at is None:
                return Plan(SELL_JUNK, f'有料理 {obs.dishes} 个，先去花袭人卖掉 {obs.junk} 样杂物和装备')
            return Plan(QUEUE_RECEIVER, f'有料理 {obs.dishes} 个，排队交给收货人')
        return _to_coast(obs, leader_role, gold, '有料理但不在海岸')
    if obs.quest == QUEST_DONE:
        if not dish_trade and obs.map_id == COAST_MAP and obs.junk and ledger.sold_at is None:
            # the junk run comes first, whatever the gold (its money goes to the receiver with the rest)
            if obs.team_leader:
                return Plan(LEAVE_TEAM, '任务已交，卖杂物前要离队')
            return Plan(SELL_JUNK, f'任务已交，先去花袭人卖掉 {obs.junk} 样杂物和装备')
        if obs.gold != 0 and obs.map_id == COAST_MAP:     # None = unread: the receiver reads it and skips at 0
            if obs.team_leader:
                return Plan(LEAVE_TEAM, '有金币待收回但还在队里')
            return Plan(QUEUE_RECEIVER, f'料理已交出，金币 {obs.gold} 排队交给收货人' if dish_trade else
                        f'任务已交，金币 {obs.gold} 排队交给收货人')
        if obs.gold != 0 and not dish_trade:      # the receiver stands at the coast
            return _to_coast(obs, leader_role, gold, '有金币待收回但不在海岸')
        return Plan(DELETE, '任务已完成、料理和金币已交出，删除角色' if dish_trade else
                    '任务已完成、金币已交出（料理不可交易，随角色删除），删除角色')

    if obs.level < TARGET_LEVEL:
        if leader_role == WELL:
            return Plan(LEVELING, f'古井队练级中 {obs.level} 级', gold)
        if obs.team_leader:
            return Plan(LEAVE_TEAM, f'{obs.level} 级却在{leader_role}队里')
        if obs.map_id != VILLAGE_MAP:
            return Plan(RETURN_HOME, f'{obs.level} 级掉队在地图 {obs.map_id}，回村重排')
        if ledger.meat_at is None:
            return Plan(EAT_MEAT, '到村，吃小肉林', gold)
        if ledger.shoe_recorded_at is None:
            return Plan(RECORD_SHOE, '在出生点记录飞鞋', gold)
        return Plan(QUEUE_WELL, f'{obs.level} 级，排古井队列', gold)

    # level >= 11
    if obs.map_id == COAST_MAP:
        if leader_role == DISPATCHER:
            return Plan(WAIT_DISBAND, '已传到海岸，等调度员回城解散')
        if obs.quest == QUEST_NONE:
            if obs.team_leader:
                return Plan(LEAVE_TEAM, '接任务前要离队')
            return Plan(ACCEPT_QUEST, '找海子接任务 78')
        if leader_role == COAST:
            return Plan(FARMING, f'刷怪中 腿{obs.legs} 鸡屁股{obs.rumps}')
        if obs.team_leader:
            return Plan(LEAVE_TEAM, f'任务中却在{leader_role}队里')
        if obs.materials_done and obs.level >= HANDIN_LEVEL:
            return Plan(HANDIN, f'材料齐（腿{obs.legs} 鸡屁股{obs.rumps}）、{obs.level} 级，交任务')
        if obs.materials_done:
            return Plan(QUEUE_COAST, f'材料齐，{obs.level} 级，排刷怪队列继续刷到 {HANDIN_LEVEL} 级')
        if obs.no_room:
            if obs.junk:
                return Plan(SELL_JUNK, f'背包满，腿/鸡屁股放不下，先去花袭人卖掉 {obs.junk} 格杂物')
            return Plan(QUARANTINED, '背包满，腿/鸡屁股放不下，又没有能卖的东西，等人工处理')
        return Plan(QUEUE_COAST, f'排刷怪队列 腿{obs.legs} 鸡屁股{obs.rumps}')
    if leader_role == WELL:
        return Plan(LEVELING, '已到 11 级，等古井队全员到级', gold)
    return _to_coast(obs, leader_role, gold, '11 级')


def _to_coast(obs, leader_role, gold, why):
    if obs.map_id != VILLAGE_MAP:
        if leader_role == DISPATCHER:
            return Plan(TRANSPORTING, f'{why}，调度员带队传送中')
        if obs.team_leader:
            return Plan(LEAVE_TEAM, f'{why}，却在{leader_role}队里')
        return Plan(RETURN_HOME, f'{why}，在地图 {obs.map_id}，先回村')
    if leader_role == DISPATCHER:
        return Plan(TRANSPORTING, f'{why}，调度员队伍里等传送')
    if obs.team_leader:
        return Plan(LEAVE_TEAM, f'{why}，却在{leader_role}队里')
    if gold:
        return Plan(QUEUE_TRANSPORT, f'{why}，金币 {obs.gold} 不足 {GOLD_TOPUP_BELOW}，等调度员补钱', True)
    return Plan(QUEUE_TRANSPORT, f'{why}，排传送队列')


def return_method(obs, ledger, now):
    """How a lost alt gets back to the village: 飞鞋 -> 回城卷 -> walk (dying on the way also lands home)."""
    if ledger.shoe_recorded_at is not None and (ledger.shoe_used_at is None
                                                or now - ledger.shoe_used_at >= SHOE_COOLDOWN):
        return 'shoe'
    if obs.scrolls > 0:
        return 'scroll'
    return 'walk'


def should_eat_potato(obs, ledger, now, eaten=0):
    """When the well team is formed and about to leave, eat POTATOES_AT_START 地瓜 in a row (eaten: how many this
    formation already ate); again only if they ran out before 11."""
    if obs.level >= TARGET_LEVEL or obs.potatoes <= 0 or eaten >= POTATOES_AT_START:
        return False
    return eaten > 0 or ledger.potato_at is None or now - ledger.potato_at >= POTATO_RENEW
