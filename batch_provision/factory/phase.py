"""Which phase an alt is in, derived ONLY from what we can observe now plus a few ledger facts.

No "current step" is stored anywhere: after a crash, relog or restart the same rules put the alt back
where it belongs (FACTORY_DESIGN.md section 4). Everything here is pure and unit-tested
(tests/test_factory_phase.py); reading the facts from the game is the job of later stages.
"""
from dataclasses import dataclass

NOVICE_MAP, VILLAGE_MAP, MEADOW_MAP, WELL_MAP, COAST_MAP = 271, 1, 130, 651, 81
TARGET_LEVEL = 11
TELEPORT_FEE = 190
GOLD_GIFT = 500                 # covers two teleports (e.g. died at the coast and must come back)
GOLD_TOPUP_BELOW = 2 * TELEPORT_FEE   # user, 2026-10-12: keep enough for two teleports, top up below 380
LEGS_ITEM, RUMPS_ITEM, DISH_ITEM = 10571, 10572, 27002
LEGS_NEEDED, RUMPS_NEEDED = 10, 20
MEAT_ITEM, POTATO_ITEM, SCROLL_ITEM = 30188, 32004, 9801
POTATO_SECONDS = 3600           # one 地瓜 = 1 h double exp
POTATO_RENEW = 55 * 60          # still below 11 this long after eating -> eat the second one
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
QUEUE_RECEIVER = 'queue_receiver'
DELETE = 'delete'
DELETED = 'deleted'             # server accepted the delete (stage 10); set by db.mark_deleted, never derived
QUARANTINED = 'quarantined'
UNKNOWN = 'unknown'

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

    @property
    def materials_done(self):
        return self.legs >= LEGS_NEEDED and self.rumps >= RUMPS_NEEDED


@dataclass(frozen=True)
class Ledger:
    """Facts only our own successful actions can tell (not readable from the game, or not yet)."""
    meat_at: float | None = None
    shoe_recorded_at: float | None = None
    shoe_used_at: float | None = None
    potato_at: float | None = None
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


def derive_phase(obs, ledger, stations):
    """stations: {char_id: role} of the resident station characters."""
    if ledger.quarantined:
        return Plan(QUARANTINED, '已隔离，等人工处理')
    if obs.map_id == NOVICE_MAP:
        return Plan(NOVICE, '在菜鸟训练营')
    gold = needs_gold(obs)
    leader_role = stations.get(obs.team_leader) if obs.team_leader else None
    if obs.team_leader and leader_role is None:
        return Plan(LEAVE_TEAM, f'在陌生队伍里（队长 {obs.team_leader}）')

    if obs.dishes > 0:
        if obs.map_id == COAST_MAP:
            if obs.team_leader:
                return Plan(LEAVE_TEAM, '有料理但还在队里')
            return Plan(QUEUE_RECEIVER, f'有料理 {obs.dishes} 个，排队交给收货人')
        return _to_coast(obs, leader_role, gold, '有料理但不在海岸')
    if obs.quest == QUEST_DONE:
        return Plan(DELETE, '任务已完成、料理已交出，删除角色')

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
        if obs.materials_done:
            return Plan(HANDIN, f'材料齐（腿{obs.legs} 鸡屁股{obs.rumps}），交任务')
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


def should_eat_potato(obs, ledger, now):
    """Eat one 地瓜 when the well team is formed and about to leave; a second one only if the first ran out."""
    if obs.level >= TARGET_LEVEL or obs.potatoes <= 0:
        return False
    return ledger.potato_at is None or now - ledger.potato_at >= POTATO_RENEW
