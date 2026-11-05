# research/shitu — 师徒产线（勇者 / 元素使）+ 现在放在这里的共用能力

更新：2026-11-05。

- **怎么跑**：`python -X utf8 -m line`（在这个目录下），说明见 [docs/SHITU_LINE.md](../../../docs/SHITU_LINE.md)。
- **路线**只看 `line/route.py`（`ROUTE` = v5、`ROUTE_BPLUS` = B+ 默认、`ROUTE_YUANSU` = 元素使）。
- 这里的很多模块**别的产品线也在用**（满爆方士项目复用了大半），改之前先看 [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) 第 3 节，
  `grep -rn <模块名> ../..` 查谁在用。
- 所有脚本都在这个目录里运行：`python -X utf8 <脚本> ...`；`common.py` 会把 `batch_provision/` 加进 `sys.path`。

## 目录

| 路径 | 内容 | 进仓库？ |
|---|---|---|
| `line/` | 产线总控、路线表、批次计划、小操作（`__main__` / `runner` / `route` / `plan` / `ops`）、`line.toml` 设置 | 是 |
| `*.py` | 共用能力和每一步的脚本（见下） | 是 |
| `bank.json` | 考验一二的题库 | 是 |
| `*_NOTES.md`、`notes/`、`ANALYSIS.md`、`GATHER.md`、`BOSS_QUIZ.md`、`EXP_MAP_TRIAL.md`、`GPT_REVIEW.md` | 历次实跑记录、协议分析、实验数据（参考用，不是操作手册） | 是 |
| `logs/` | 产线日志、进度（`line_state.json`、`<LOGID>_line.json`）、报警、`LINE_STOP`、飞鞋冷却 `shoe_used.json`、改名记录 `name_alias.json`、通天二收入 `tower2_exp.csv` | 否 |
| `runtime/`、`bin/`、`state*.json` | DLL 录包、复制的 DLL、每批进度 | 否 |

## 环境变量（产线 `line/plan.py` 每批设好，单独跑脚本时自己设）

| 变量 | 意思 |
|---|---|
| `SHITU_MASTERS` / `SHITU_APPRENTICES` | 这一队的师傅（第一个当队长）/ 徒弟 |
| `SHITU_STATE` | 这一批的进度文件 |
| `SHITU_GOLD` / `SHITU_SCROLLS` | 启动金 / 每个徒弟的回城卷 |
| `SHITU_JOB` | `战士`（勇者）/ `术士`（元素使） |
| `SHITU_TIDY` | `1` = 元素使：每次回城 `tidy.py` 整理背包 |
| `SHITU_TRASH` | `1` = 师徒产线：丢葫芦 / 特赦令 / 整人道具，勇者线回城卖武器（`trash.py`） |
| `SHITU_REVIVE` | 复活道具的物品 id（`revive.py`） |
| `SHITU_QID` | `talk_chain.py` / `tower1_go.py` 看哪个任务 |
| `BATCH`、`PAIRS`、`LOGID` | 第几批（建角槽的上限）、`账号:角色名` 列表、日志名 |

## 共用能力（别的产品线也能用，分类和 ARCHITECTURE.md 第 3 节一致）

**连接窗口**
- `trial_run.py`：`Client`（一个窗口：内存 + 发命令）、`wait`、`say`、`each`（几个号同时做各自的事）、`Gone`（30 秒读不到人物 = 掉线）；
  对话工具 `pick` / `choose` / `body`；也是考验一二的脚本（见下）。
- `common.py`：按窗口标题找角色、模块基址、环境变量。`attach_tap.py`：给已在游戏里的窗口挂录包。`monitor.py`：只读录制器。
- `make_apprentices.py`：建角 / 进角色 / 新手出村（`slot_problem`：第 N 批的槽是上限）；`master_login.py`：师傅自动登录。

**移动**
- `pp_chain.py`：坐 PP鸡（按目的地自动中转）、`walk` 城里走路。
- `maze_train.py`：带队主循环（每张图怎么走的 legs 表、练到几级 / 走到哪 / 巡逻；队长自动打怪、加天赋）。
  这些只是它的一个配置：`go_goal.py`、`go_cave.py`、`desert_go.py`、`ruin_go.py`、`guji_entrance.py`、`tower1_go.py`、`tower2_go.py`、
  `back_longeer.py`、`quan100.py`、`bazhen25.py`、`cave_train.py`、`tower28.py`、`tower2_patrol.py`、`shuidi.py`、`quanshou.py`。
- `lunhui15.py`：轮回之城练级，也定义 `Caster`（战斗里放技能）。`well10.py`：古井练级，也定义 `form_team`、`invite_near`、`Unarm`。
- `r4_util.py`（名字是历史遗留，现在是产线的常用小操作）：`home`（全员回城，徒弟先、师傅最后）、`leave`（`--home-if-split`）、`restock`、
  `restock_master`、`supply`、`double`、`need`（任务闸门）、`windows`（窗口检查 + 重登）、`space` / `space_one` / `drop_order`（腾背包）。
- `quanshou.py`：`scroll`（用回城卷）、`borrow`（向身边的人借）、`fetch`（师傅来接）、`flee`（逃出战斗）；也是转职任务 24 的打拳手脚本。
- `shoe_point.py`：飞鞋记点 / 全员飞（查冷却）。`team_tp.py`：全队坐外城传送员到无尽2路口。`master_go.py`：师傅单独走。

**队伍、战斗**
- `teamwalk.py`：`lead_to`、`past`、`step_to`、`regroup`、`regroup_all`、`settle`（解散前等全队站稳）、`fight_out`、`leave_all`、`each`、
  `click_here`（先原地点 NPC）、`Escaper`（只逃跑）。**新写的带队脚本都用这几个。**
- `revive.py`：战斗里复活倒下的徒弟。`boss_quiz.py`：boss 开打题（答题器优先，这里兜底）。`boss_fight.py`：徒弟带队开打 NPC 战斗。
- `farm.py`：带队刷某个掉落直到每人够数。

**NPC 对话**
- `take224.talk`：点 NPC 按关键词一层层选。`talk_chain.py`：城里每人同时走去对话。`team_npc.py`：野外队长带到、全员同时对话。

**背包和钱**
- `sell_tradable.py`：在小美那里按规则卖（`--safe`、`--stones`、`--zawu`、`--noorange`、`--tidy`、`--name 词…`、`--weapons` 卖光徒弟武器）。
- `buy_scroll.py`：铁公鸡买回城卷 / 胡萝卜汁。`supply_go.py`：交易工具 `trade_until`、到平静海岸2区。
- `trash.py`：丢葫芦 / 特赦令 / 整人道具（定时、开包后、回城），勇者线回城卖武器。`tidy.py`：元素使回城整理。
- `open_packs.py`、`wear_best.py`（`--no-weapon`）、`eat_items.py`、`drop_prank.py`、`mail_sell.py`、`heal.py`、`unequip_all.py`、
  `master_bag.py`（师傅背包清理）、`give_gold.py`（徒弟金币交给师傅）、`give_box.py`（橙装和金币交给收货号）。

## 师徒线自己的任务脚本

| 任务 | 脚本 |
|---|---|
| 拜师 | `bai_shi.py` |
| 10 级转职：勇者（任务 24 拳手）/ 元素使（任务 25 水滴精灵）；任务 94；3 小时双倍 | `zhuanzhi_take.py`、`quanshou.py` / `shuidi.py`、`zhuanzhi_finish.py`、`line.ops q94`、`double_exp.py` |
| PP鸡 权限 | `pp_unlock.py` |
| 考验一二 / 考验三 | `trial_run.py`、`trial3_run.py` |
| 任务 224（采集 + 地头蛇） | `take224.py`、`gather.py`、`dts.py`（`shoe_dagewang.py`：旧的大个王记点） |
| 任务 181 战士的试炼（勇者） | `talk_chain.py`、`quan100.py`、`team_npc.py`、`dew_team.py` |
| 任务 183 勇者的考验 | `yongzhe_take.py`、`scorpion_water.py`、`scorpion_king.py`、`line.ops fairy` |
| 任务 187 术士的试炼 / 189 元素使的考验（元素使） | `stones.py`、`yaodao.py`、`bird.py`、`fire.py`、`mole.py`、`rooms.py`、`fifth.py`、`buy_gear.py` |
| 出师 | `chushi.py` |

## 只读工具 / 分析

`check_rosters.py`（每个账号的角色列表）、`npc_peek.py`（看一个 NPC 的对话）、`boss_quiz_peek.py`（看答题面板）、
`sp_watch.py`（量蓄力）、`r4_stats.py`、`exp_trial.py`、`r5_compare.py`（每批每步用时、各图每分钟经验）、`delete_apprentices.py`（删角色）。

## 2026-11-05 删掉的

第 4 轮 shell 版产线（`r4_line.py`、`r4_line.toml`、`r4_*.sh`）、第 2 / 3 轮的一次性脚本（`r2_status.py`、`r3_*.sh`、`shitu_flow.py`、
`dew.py`、`dew_solo.py`、`guji_crystal.py`、`fight_helper.py`、`portal_test.py`）。都已被 `line/` 和上面的模块取代，要看在 git 历史里。
