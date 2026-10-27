# research/shitu — 师徒「大带小」流水线工具箱

一句话：两个 70 级师傅（伏地魔1、伏地魔2）各带 4 个新建小号，从 1 级做到 41 级出师。每个小号最后约 **50 万金币**，还有一套 40 级橙装。
完整流程、协议、坑和优化见 **[docs/SHITU_PIPELINE.md](../../../docs/SHITU_PIPELINE.md)**。这一页只是代码地图和命令清单。

- 所有脚本都在这个目录里运行：`python -X utf8 <脚本> ...`。
- 也可以从 `batch_provision/` 运行：`python -X utf8 research/shitu/<脚本>`。
- `common.py` 会把 `batch_provision/` 加进 `sys.path`，所以能直接用 `provisioner` 和 `factory`。

## 目录

| 路径 | 内容 | 进仓库？ |
|---|---|---|
| `*.py` / `r3_*.sh` | 工具和每一步的脚本 | 是 |
| `ANALYSIS.md` | 考验一二三、拜师、10 级转职、解除师徒的协议分析（第 1 轮） | 是 |
| `GATHER.md` | 遗忘洞穴采集、地头蛇、任务 224（第 1 轮） | 是 |
| `notes/` | 第 2、3 轮的逐条流水和报告 | 是 |
| `bank.json` | 考验一二的题库（题目 → 正确答案） | 是 |
| `logs/` | `mem_<角色>.jsonl`、`net_<角色>.jsonl`（monitor.py 录的）和各步日志 | 否（几百 MB） |
| `runtime/` | DLL 录包 `tap_<pid>.jsonl` | 否 |
| `bin/` | attach_tap.py 复制过来的 DLL | 否 |
| `state*.json` | 每队的进度文件（拜师 / 考验一二三做过没有） | 否 |

## 环境变量（一队一套）

| 变量 | 意思 | 例子 |
|---|---|---|
| `SHITU_MASTERS` | 这一队的师傅（第一个当队长） | `伏地魔1` |
| `SHITU_APPRENTICES` | 这一队的徒弟 | `千万1,千万2,千万3,千万4` |
| `SHITU_STATE` | 进度文件，两队同时跑时必须分开 | `state_r3a.json` |
| `SHITU_SCROLLS` | supply_go 给每个徒弟几张回城卷 | `10` |
| `SHITU_QID` | talk_chain.py 读哪个任务的步骤 | `183` |
| `SHITU_GATHER_CAST` / `SHITU_DTS_ONCE` | 采集者自己出手 / 地头蛇只点一次 | `1` |

## 模块地图（按职责分层）

**第 0 层：读和看（只读）**
- `common.py`：按窗口标题找角色、模块基址、路径和环境变量。
- `trial_run.py`：`Client`（一个窗口：内存 + 发请求）、`wait`、`say`、对话工具 `pick` / `choose` / `body`。
- `monitor.py`：只读录制器，每 0.2 秒记一次内存变化，同时记录所有收发的封包，写到 `logs/mem_*.jsonl`、`logs/net_*.jsonl`。
- `attach_tap.py`：给已经进游戏的窗口挂上录包。
- `r2_status.py`、`check_rosters.py`：状态和角色列表，只读。

**第 1 层：移动**
- `pp_chain.py`：`PP` 表记录每个地图上的 PP 鸡；`hop()` 坐一次 PP 鸡，`walk()` 在城里走路。菜单里没有目标时，先走中转站。
- `maze_train.py`：带队主循环。腿表 legs 写每张地图怎么走（walk / click），stage 写目标（练到几级 / 走到哪个点 / 巡逻）；队长自动打怪、加天赋，徒弟死亡就停。
- `go_goal.py`、`desert_go.py`、`ruin_go.py`、`guji_entrance.py`、`tower1_go.py`、`tower2_go.py`、`go_cave.py`、`back_longeer.py`：只是 maze_train 的一个 stage 配置。
- `portal_test.py`：逍遥村 ↔ 自由市场的免费传送门（菜单里也有梦幻岛）。

**第 2 层：队伍和战斗**
- `well10.form_team`：组队（队长离太远时自己走过去邀请）。
- `dew_team.py`：`regroup`（徒弟走到队长脚下 → 邀请 → 1.5 秒后接受，最多 4 次）、`lead_to`（站着不动 3 秒就重发寻路）、`past`（队长走过目标点 80 像素，让队尾的人站到目标旁）、`step_to`（徒弟独自走几步，遇怪就逃跑）。**以后新写的带队脚本都用这几个。**
- `lunhui15.Caster`：战斗里放技能（师傅：扫射 + 宠物烈焰爆发；徒弟：普攻）。
- `dew.Escaper`：战斗里只发逃跑（不一定逃得掉，所以徒弟不要单独在野外走）。
- `fight_helper.py`：后台帮打。

**第 3 层：NPC 对话和任务**
- `take224.talk`：点 NPC，按关键词一层层选。
- `talk_chain.py`：城里多人并行，每人走到 NPC 旁边，对话一路点到底，遇到多个选项就停。
- `team_npc.py`：野外版，师傅带队到了以后，徒弟离队、走近、对话，再回队。关键词用 `|` 分隔，按顺序优先选。
- 每个任务的脚本：
  - 拜师：`bai_shi.py`
  - 考验一二：`trial_run.py`
  - 考验三：`trial3_run.py`
  - 10 级转职（任务 24）：`zhuanzhi_take.py`、`quanshou.py`、`zhuanzhi_finish.py`
  - 任务 224：`take224.py`、`gather.py`、`dts.py`、`shoe_dagewang.py`
  - 40 级战士的试炼（任务 181）：`quan100.py`、`guji_crystal.py`、`dew_team.py`
  - 勇者的考验（任务 183）：`yongzhe_take.py`、`scorpion_water.py`、`scorpion_king.py`
  - 出师：`chushi.py`
  - 流程总控（第 1 轮）：`shitu_flow.py`

**第 4 层：背包和钱**
- `sell_tradable.py`：在小美那里卖东西，用开关选卖哪类：
  - `--safe`：杂物、残骸、低于蓝色的装备
  - `--zawu`：只卖杂物
  - `--stones`：杂物、残骸、技能石、图纸、配方
  - `--noorange`：杂物 + 橙色以下的装备
  - `--name 词1,词2`：按名字卖
- `buy_scroll.py`：在铁公鸡那里买回城卷（2.100 版的买包格式）。
- `supply_go.py`：交易工具 `trade_until`，用来给物品和金币。
- `give_box.py`：把橙装和全部金币交易给收货号。
- `mail_sell.py`：分批提取宝箱邮件，然后卖掉。
- `open_packs.py`：开成长礼包。
- `eat_items.py`：吃掉指定的东西。
- `drop_prank.py`：丢整人道具。
- `heal.py`：吃萝卜糕补血。
- `wear_best.py`：穿上背包里最好的装备。
- `unequip_all.py`：脱下身上所有装备。

**建号 / 删号**
- `make_apprentices.py`：建号。
- `delete_apprentices.py`：删号。

## 第 3 轮的命令顺序（每队一套环境变量，两队同时跑）

```
# A 队：export SHITU_STATE=state_r3a.json SHITU_MASTERS=伏地魔1 SHITU_APPRENTICES=千万1,千万2,千万3,千万4
# B 队：export SHITU_STATE=state_r3b.json SHITU_MASTERS=伏地魔2 SHITU_APPRENTICES=千万5,千万6,千万7,千万8
python -X utf8 make_apprentices.py ...           # 建号，进游戏后还要 attach_tap.py / native.arm
python -X utf8 bai_shi.py                        # 拜师
python -X utf8 well10.py                         # 1 -> 10，阴森古井
python -X utf8 supply_go.py                      # 回城卷 + 5 万金币，到海岸，PP鸡 认证
python -X utf8 lunhui15.py                       # 10 -> 15，轮回之城
python -X utf8 maze_train.py                     # 15 -> 23，然后走到大个王
bash r3_zhuanzhi.sh                              # 飞鞋，224 交了重接，10 级转职，任务 94
bash r3_mid.sh                                   # 卖杂物，考验一二，通天塔练到 30
bash r3_cave.sh; SHITU_DTS_ONCE=1 python -X utf8 dts.py   # 任务 224，打地头蛇（第一次会弹题）
bash r3_end.sh                                   # 回城，卖杂物，考验三
python -X utf8 tower2_go.py; python -X utf8 tower2_patrol.py 40   # 通天塔二区巡逻到 40
# 40 级之后的任务 181 / 183 / 出师 / 收尾，逐条命令见 docs/SHITU_PIPELINE.md 第 4 节
```
