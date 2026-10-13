"""factory.toml -> Settings."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path
    tick: float
    meat_timeout: float
    shoe_timeout: float
    gold_amount: int
    gold_topup_below: int
    gold_timeout: float
    trade_step_gap: float
    well_team_size: int
    well_form_timeout: float
    well_lease: float
    well_train_timeout: float
    leader_skill: int
    pet_magic: int
    pet_mp_min: int
    member_attack: bool
    transport_team_size: int
    transport_timeout: float
    transport_lease: float
    quest_timeout: float
    coast_team_size: int
    coast_form_timeout: float
    coast_farm_timeout: float
    coast_lease: float
    coast_legs_patrol: tuple
    coast_rumps_patrol: tuple
    receiver_post: tuple
    receive_post_timeout: float
    receive_timeout: float
    receive_lease: float


def _point(value, name):
    if len(value) != 2:
        raise ValueError(f'{name} 应是一个 [x, y] 点，实际 {value}')
    return tuple(int(v) for v in value)


def _patrol(value, name):
    points = tuple(tuple(int(v) for v in p) for p in value)
    if len(points) != 2 or any(len(p) != 2 for p in points):
        raise ValueError(f'{name} 应是两个 [x, y] 点，实际 {value}')
    return points


def load_settings(path):
    data = tomllib.loads(Path(path).read_text('utf-8')) if Path(path).is_file() else {}
    f = data.get('factory', {})
    size = int(f.get('well_team_size', 4))
    if not 1 <= size <= 4:
        raise ValueError(f'well_team_size 应在 1..4，实际 {size}')
    transport_size = int(f.get('transport_team_size', 4))
    if not 1 <= transport_size <= 4:
        raise ValueError(f'transport_team_size 应在 1..4，实际 {transport_size}')
    coast_size = int(f.get('coast_team_size', 4))
    if not 1 <= coast_size <= 4:
        raise ValueError(f'coast_team_size 应在 1..4，实际 {coast_size}')
    return Settings(db_path=ROOT / f.get('db', 'state/factory.db'), tick=float(f.get('tick', 0.2)),
                    meat_timeout=float(f.get('meat_timeout', 60)), shoe_timeout=float(f.get('shoe_timeout', 60)),
                    gold_amount=int(f.get('gold_amount', 500)),
                    gold_topup_below=int(f.get('gold_topup_below', 380)), gold_timeout=float(f.get('gold_timeout', 60)),
                    trade_step_gap=float(f.get('trade_step_gap', 0.5)), well_team_size=size,
                    well_form_timeout=float(f.get('well_form_timeout', 120)),
                    well_lease=float(f.get('well_lease', 1200)),
                    well_train_timeout=float(f.get('well_train_timeout', 1800)),
                    leader_skill=int(f.get('leader_skill', 803)), pet_magic=int(f.get('pet_magic', 1504)),
                    pet_mp_min=int(f.get('pet_mp_min', 100)), member_attack=bool(f.get('member_attack', False)),
                    transport_team_size=transport_size,
                    transport_timeout=float(f.get('transport_timeout', 240)),
                    transport_lease=float(f.get('transport_lease', 600)),
                    quest_timeout=float(f.get('quest_timeout', 120)),
                    coast_team_size=coast_size, coast_form_timeout=float(f.get('coast_form_timeout', 120)),
                    coast_farm_timeout=float(f.get('coast_farm_timeout', 1800)),
                    coast_lease=float(f.get('coast_lease', 1200)),
                    coast_legs_patrol=_patrol(f.get('coast_legs_patrol', [[678, 1821], [400, 1880]]),
                                              'coast_legs_patrol'),
                    coast_rumps_patrol=_patrol(f.get('coast_rumps_patrol', [[1170, 2883], [1000, 2700]]),
                                               'coast_rumps_patrol'),
                    receiver_post=_point(f.get('receiver_post', [1780, 1370]), 'receiver_post'),
                    receive_post_timeout=float(f.get('receive_post_timeout', 180)),
                    receive_timeout=float(f.get('receive_timeout', 60)),
                    receive_lease=float(f.get('receive_lease', 120)))
