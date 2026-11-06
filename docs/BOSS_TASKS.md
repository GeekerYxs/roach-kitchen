# boss 任务：做成共用能力，哪条队伍都能调用

更新：2026-11-06。给人看，也给接手的 AI 看。现状、规划和迁移顺序都在这一页。

## 1. 为什么要共用

- 很多 boss 任务**每天能打 10 次**（例：「让鹰王倒下」打独眼鹰王），不同 boss 的次数分开算（鹰王 10 次，虎王另外 10 次）。
- 练级队本来就会经过这些地图。例：满爆方士线在**陷阱囚牢**（map 1150）把小号从 53 练到 58，然后去荒芜之地旁边的禁锢之地；
  而鹰王任务的接任务人、打 boss 的地点就在荒芜之地1区和陷阱囚牢，任务要求 58 级。练到 58 时顺路让队长带着打 10 次 boss，
  经验、潜能、boss 掉落都多拿一份。
- 所以「打某个 boss 一轮」应该是一个**能力**，像回城、坐 PP鸡一样，任何产品线传进一支队伍就能用；不能只写在 5 人打 boss 这条线里。

## 2. 现状（2026-11-06）

鹰王的全部步骤先写在独立产品线 `batch_provision/projects/boss_gear_5/`，已经实跑通 5 轮：

| 步骤 | 脚本 |
|---|---|
| 回城 → 组队 → PP鸡到荒芜之地1区 | `go_desert1.py` |
| 接任务（莫吉，任务 1130；先发包，失败按菜单选） | `take_eagle.py` |
| 进陷阱囚牢 | `enter_cage.py` |
| 队长点瓶子拿三种结晶 → 琉璃瓶召唤 → 全队打 | `eagle_cage.py` |
| 回城 PP鸡回莫吉交任务，并续接下一轮 | `handin_eagle.py` |
| 从当前进度接着跑 N 轮 | `round.py N` |

游戏事实（任务规则、瓶子、惩罚、boss 题）写在 `projects/boss_gear_5/README.md` 和各脚本开头的注释里。

现状的两个限制，就是下面规划要解决的：

1. 队伍是通过环境变量（`_bootstrap.py` 设 `SHITU_LEADER` 等）定死的，别的产品线没法传自己的队伍进来。
2. 没有「今天还能打几次」的概念，也不知道打满 10 次后服务器会怎么样（**待实测**：今天已经打了 6～7 次，再打几轮就能看到）。

## 3. 放在哪：`batch_provision/kit/boss/`

按 [ARCHITECTURE.md](ARCHITECTURE.md) 第 6 节的方向，共用能力以后都进 `batch_provision/kit/`。boss 任务是第一批正式放进去的能力：

```
batch_provision/kit/
  __init__.py
  boss/
    __init__.py      对外只有两个入口：available(boss, team) 和 run(boss, team, times)
    base.py          一个 boss 任务的「规格」+ 通用的一轮流程（从当前进度接着做、每步可重跑）
    daily.py         每个队长每个 boss 今天打了几次（runtime/boss_daily.json），到上限就不打
    travel.py        带队回城、坐 PP鸡到某张图（显式传队伍，不读环境变量）
    eagle.py         鹰王（任务 1130）：从 projects/boss_gear_5 搬过来
    tiger.py         虎王（下一步研究）
```

产品线只负责「什么时候打、打几次」：

| 调用方 | 怎么用 | 开关 |
|---|---|---|
| `projects/boss_gear_5/`（5 个 70 级专门打 boss） | `round.py --boss 鹰王 --times 10`，打满当天次数就停 | 本来就是这条线的事 |
| `projects/fullcrit_mage_leveling_70/`（满爆方士带 4 个号） | 陷阱囚牢阶段四个小号到 58 级后、去禁锢之地之前，调 `kit.boss.run('鹰王', team, times=今天剩余)`，打完照常去禁锢之地 | `team.toml` 加 `[bosses]`，例如 `鹰王 = 10`；**默认不打**，保持原来的路线 |
| 师徒线 | 不用（最多 41 级） | — |

## 4. 一个 boss 要写什么（接口）

每个 boss 一个模块，只描述「这个 boss 怎么打」，通用流程在 `base.py`：

```python
class Eagle(BossTask):
    name = '鹰王'
    quest = 1130            # 任务编号：用 read_quest 判断进行到哪一步
    min_level = 58          # 全队都要到这个等级
    daily = 10              # 每天次数上限
    npc_map = 180           # 接 / 交任务的地图（荒芜之地1区，PP鸡能直达）

    def take(self, team): ...       # 接任务（队长接 = 全队接）
    def go(self, team): ...         # 从接任务的地方带队到打 boss 的地方
    def fight(self, team): ...      # 准备（鹰王 = 三种结晶）+ 召唤 + 打
    def report(self, team): ...     # 回去交任务（并续接下一轮）
```

`base.run_once(team)` 读任务 1130 的进度，决定从哪一步开始。这样中途掉线、被停掉，重跑都能接上。
`team` 是 `Client` 列表，第一个是队长；所有步骤只用传进来的队伍，不读 `SHITU_LEADER` 这类环境变量，所以别的产品线可以直接传自己的队伍。

## 5. 迁移顺序（每一步都能单独上线，不影响正在跑的队）

1. ✅ 鹰王在 `projects/boss_gear_5/` 跑通（2026-11-06）。
2. 实测「每天 10 次」：打满后接任务 / 召唤时服务器怎么说，写进 `daily.py` 的注释。
3. 建 `kit/boss/`，把鹰王的逻辑搬进 `eagle.py` + `base.py`，改成显式传队伍；`projects/boss_gear_5/` 的几个脚本改成一行转发，文件名不变。
   加离线测试 `tests/test_boss_eagle.py`（假窗口：瓶子对 / 被传送 / 扣血 / 遇怪打断；从各个进度重跑）。
4. 加 `daily.py` 和 `round.py --boss --times`。
5. 满爆方士线在 58 级那一步按 `team.toml [bosses]` 调用；先用一队实跑。注意：那里是 1 个 70 级队长带 4 个 58 级，鹰王是 5 个 70 级测的，
   要先确认打得过。
6. 虎王按同一个接口写 `tiger.py`（任务研究另开）。

## 6. 鹰王已知规矩（摘要，细节见 `projects/boss_gear_5/README.md`）

- 队长接任务 = 全队接；只有队长点瓶子才算，拿到的结晶全队都有。
- 对的瓶子每轮重新分配，同一轮错的一直错；点之前站稳，点完看坐标和背包判断（被传送 / 扣血 = 错；进战斗 = 被遇怪打断，重点）。
- 琉璃瓶第一次选「召唤鹰王战斗」会弹 boss 题，答完再选一次才开战；打完全队任务都过。
- 奖励：每人 14580 经验 + 1740 潜能；交任务时选「没问题」就续接下一轮。
