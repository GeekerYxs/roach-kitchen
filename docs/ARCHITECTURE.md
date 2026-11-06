# 仓库架构：几条产品线 + 一套共用的游戏能力

更新：2026-11-06。给人看，也给接手的 AI 看（AI 另见仓库根目录 `AGENTS.md`）。

## 1. 仓库里有什么

| 产品线 | 做什么 | 入口 | 代码在哪 | 说明文档 |
|---|---|---|---|---|
| **小强料理** | 工位化生产「美味小强料理」：调度员、古井队长、海岸队长、收货人 + 小号流水 | `一键总大脑.cmd`（`python -m factory.supervisor`） | `batch_provision/factory/` | [FACTORY_DESIGN.md](FACTORY_DESIGN.md)、[DEPLOY.md](DEPLOY.md) |
| **师徒 → 勇者** | 70 级师傅每批带 4 个新号，1 级 → 41 级出师（勇者），每号约 48 万金币 | `python -X utf8 -m line`（在 `research/shitu/` 下） | `batch_provision/research/shitu/`（`line/` = 总控和路线表） | [SHITU_LINE.md](SHITU_LINE.md)、[SHITU_MASTER_GUIDE.md](SHITU_MASTER_GUIDE.md)、[SHITU_PIPELINE.md](SHITU_PIPELINE.md) |
| **师徒 → 元素使** | 同一条师徒产线，`line.toml` 里 `job = "术士"` 的队走元素使任务 | 同上 | 同上（`route.ROUTE_YUANSU`、`shuidi.py`、`rooms.py`、`fifth.py` …） | `research/shitu/YUANSU_NOTES.md` |
| **满爆方士带到 70 级** | 无任务练级：满爆方士带 4 个号一路刷到 70 | `projects/fullcrit_mage_leveling_70/run_level_to_70.py` | `batch_provision/projects/fullcrit_mage_leveling_70/` | 该目录 `README.md` |
| **5 人打 boss** | 5 个 70 级组队打每天限次的 boss 任务（现在：鹰王任务 1130、虎力仙任务 1185、老树叶任务 673） | `projects/boss_gear_5/round.py N`、`round_tiger.py N`、`round_leaf.py N` | `batch_provision/projects/boss_gear_5/`（以后能力搬进 `kit/boss/`） | [BOSS_TASKS.md](BOSS_TASKS.md)、该目录 `README.md` |
| **抓一级宝宝** | 巡逻、认出一级目标、用捕捉道具 | `抓宠一级宝宝/runner.py` | `抓宠一级宝宝/` | 该目录 `README.md`、`研究记录.md` |
| 七一领工资 / 金鼓刷怪（研究） | 小实验 | 见目录 | `research/qiyi/`、`research/jingu/` | `research/qiyi/FLOW.md` |

工具：

| 工具 | 做什么 | 在哪 |
|---|---|---|
| 答题器 | 普通战斗题 + boss 开打题，解锁游戏自带辅助工具的战斗辅助、自动采集、自动任务三页；**自动发现并注入每个新开的游戏窗口**。一台电脑开一个，所有产线共用；**每条产线启动时 `provisioner.quizbot.ensure()` 检查，没开才启动**（启动会先关掉已有的，所以不能多开） | `大冒险2_自动答题器_原生无感关窗版/`，启动逻辑 `batch_provision/provisioner/quizbot.py` |
| 战斗记录 | 每场战斗一行进 SQLite，报表 | `batch_provision/battlelog/`，[BATTLELOG.md](BATTLELOG.md) |
| 经验监测 | 每场经验、各级速度 | `batch_provision/expwatch/` |

## 2. 分层：谁能用谁

```
            ┌──────────────── 产品线（只编排，不写游戏细节）────────────────┐
            │ factory/（料理）  research/shitu/line/（勇者、元素使）          │
            │ projects/fullcrit_mage_leveling_70/   抓宠一级宝宝/             │
            └───────────────────────────┬────────────────────────────────────┘
                                        │ 只调用下面一层
            ┌───────────── 共用游戏能力（每种能力只写一份）─────────────────┐
            │ 现在主要在 research/shitu/*.py（历史原因放在这里），            │
            │ 一部分在 factory/（items.py 物品分类、supply.ShopClient 商店）    │
            └───────────────────────────┬────────────────────────────────────┘
                                        │
            ┌───────────── 游戏接口（读内存、发包、登录）───────────────────┐
            │ batch_provision/provisioner/  + native/（DLL、launcher）         │
            └──────────────────────────────────────────────────────────────────┘
```

规则：

0. **改共用能力之前，先查谁在用**：`grep -rn 模块名 batch_provision 抓宠一级宝宝`。满爆方士项目复用了 `research/shitu/` 的大部分
   能力（`trial_run`、`maze_train`、`pp_chain`、`lunhui15`、`revive`、`sell_tradable`、`shoe_point`、`quanshou`、`r4_util.home` …），
   改它们就是同时改了两条线。
1. **产品线之间不互相导入。** 满爆方士项目可以用 `research/shitu/` 里的能力，但不能导入 `line/route.py` 这种师徒线自己的编排。
2. **一种能力只写一份，修好了大家一起受益。** 例：「掉线 30 秒就报错」写在 `trial_run.Gone`，古井、轮回、迷宫、通天塔、满爆方士项目的
   练级循环全部自动用上。不要在自己的产品线里复制一份再改。
3. **产品线各自的规矩用开关，不要写死在共用代码里。** 例：徒弟丢葫芦、回城卖武器只在师徒产线打开（环境变量 `SHITU_TRASH=1`，
   `line/plan.py` 设）；满爆方士项目也调用同一个回城函数，但不设这个开关，行为不变。
4. **游戏事实（坐标、NPC、选项文字、协议）写在用它的能力模块里，旁边注明日期和来源**，文档只放结论和链接。

## 3. 共用能力目录（现在在哪、谁在用）

> 想加一个新功能，先在这张表里找：已经有的直接用；没有的，按「属于哪一类」加到对应模块，再登记到这里。

| 类别 | 能力 | 现在的位置 | 已经在用的产品线 |
|---|---|---|---|
| **连接窗口** | 找窗口、读内存、发命令（`Client`）；等待；日志 `say` | `research/shitu/trial_run.py`、`common.py`、`provisioner/` | 全部 |
| | 几个号同时做各自的事 `each` | `trial_run.each`、`teamwalk.each` | 师徒 |
| | 掉线检测（30 秒读不到人物就报错）、答题弹窗 90 秒没人答就报错 | `trial_run.Gone` | 师徒、满爆方士 |
| | 关掉开着的对话框（回城 / 离队前） | `r4_util.close_dialogs` | 师徒、满爆方士 |
| | 确保答题器在运行（没开就启动，加锁防两条线同时启动） | `provisioner/quizbot.py` | 全部（料理总大脑、师徒总控、满爆方士、抓宠） |
| | 登录 / 建角 / 进角色 / 新手出村 | `provisioner/`、`research/shitu/make_apprentices.py`、`master_login.py` | 料理、师徒 |
| **移动** | 坐 PP鸡（按目的地找路线） | `pp_chain.py` | 师徒、满爆方士 |
| | 地图能走的格子、路程、「离 NPC 多近就能点」的站位（服务器约 500 像素、隔墙也行，按 300 用） | `provisioner/mapgrid.py`（读游戏资源包 `map\mapNNNNN.bar`） | 5 人打 boss |
| | 城里走到某点 | `pp_chain.walk`、`zhuanzhi_finish.walk` | 师徒 |
| | 带队穿地图 / 练级 / 巡逻（一张「每张图怎么走」的表） | `maze_train.py`（及 `go_goal.py`、`tower1_go.py` … 这些配置） | 师徒、满爆方士 |
| | 回城（全员，徒弟先回、师傅最后） | `r4_util.home` | 师徒、满爆方士 |
| | 用回城卷；没卷先借、再让师傅来接（同图走过去 / 飞鞋到同一记录点） | `quanshou.scroll`、`quanshou.borrow`、`quanshou.fetch` | 师徒、满爆方士 |
| | 飞鞋记点 / 飞（全员、查冷却） | `shoe_point.py` | 师徒、满爆方士 |
| | 外城传送员组队传到无尽2路口 | `team_tp.py` | 师徒 |
| **队伍** | 组队（同时邀请、远的队长走过去、失败再走到脚下） | `well10.form_team`、`well10.invite_near`、`teamwalk.regroup` | 全部带队的 |
| | 解散前等全队站稳、打完这场 | `teamwalk.settle`、`teamwalk.fight_out` | 师徒 |
| | 全员离队、全员回队 | `teamwalk.leave_all`、`teamwalk.regroup_all` | 师徒 |
| **战斗** | 队长放技能 + 宠物技能：人物按 猎人扫射 803 → 方士天之箭 354 → 魔法槽里的技能（元素使魔法火焰 206）→ 普攻 的顺序；宠物烈焰爆发同一时间只挂一个，等服务器结算包（0x4111）后，还有蓄力点就立即再放；看到"轮到你"的包（0x4105）就立即出手，不等内存；战斗中每 0.03 秒检查一次（`BATTLE_TICK`）。说明见 [PET_MAGIC_CONTINUOUS_CASTING_AND_TIANZHIJIAN.md](PET_MAGIC_CONTINUOUS_CASTING_AND_TIANZHIJIAN.md) | `lunhui15.Caster` | 师徒（勇者 / 元素使）、满爆方士 |
| **战斗** | 走路途中遇到战斗：队长（或单人）用 Caster 打完，宠物开场就放烈焰爆发、有蓄力点立刻再放；队员只等 | `lunhui15.fight_out` / `lunhui15.BattleHand` | 师徒（采花、走去大个王、PP鸡链、飞鞋记点、补给交易） |
| | 只逃跑 | `teamwalk.Escaper`、`quanshou.flee` | 师徒、满爆方士 |
| | 复活道具 | `revive.py` | 师徒、满爆方士 |
| | boss 开打题 | `boss_quiz.py`（答题器优先） | 师徒 |
| **NPC 对话** | 点 NPC、按关键词一层层选 | `take224.talk` | 师徒 |
| | 先原地点，点不开再走过去 | `teamwalk.click_here` | 师徒 |
| | 城里每人各自走去对话 | `talk_chain.py` | 师徒 |
| | 野外：队长带到、全员同时对话 | `team_npc.py` | 师徒 |
| **商店** | 商店协议（买 / 卖） | `factory/supply.py` 的 `ShopClient` | 料理、师徒、满爆方士 |
| | 买回城卷 / 胡萝卜汁（铁公鸡） | `buy_scroll.py` | 师徒、满爆方士 |
| | 按规则卖（`--safe`、`--stones`、`--weapons` …） | `sell_tradable.py` | 师徒、满爆方士 |
| | 队长补给（料理工位：回城卷、萝卜糕、甜点） | `factory/supply.py` | 料理 |
| | 队长补蓝：汉尼拔买劲爆汽水（三轮实测） | `projects/fullcrit_mage_leveling_70/hannibal_soda.py` | 满爆方士 |
| **boss 任务** | 打一轮限次 boss（接任务 → 去 → 准备 + 打 → 交）；规划成任何队伍都能调用 | 现在 `projects/boss_gear_5/`，规划 `kit/boss/`（见 [BOSS_TASKS.md](BOSS_TASKS.md)） | 5 人打 boss；规划给满爆方士 58 级顺路打 |
| **背包** | 物品分类（能不能卖、是不是任务品） | `factory/items.py`、`factory/data/items.csv` | 全部 |
| | 腾空格（杂物 → 整人道具 → 其他杂物） | `r4_util.space_one`、`r4_util.drop_order` | 师徒 |
| | 定时丢葫芦 / 特赦令 / 整人道具，回城卖武器 | `trash.py` | 师徒 |
| | 开礼包、穿装备、吃东西、丢整人道具、取邮件 | `open_packs.py`、`wear_best.py`、`eat_items.py`、`drop_prank.py`、`mail_sell.py` | 师徒 |
| | 交易（给东西、给金币） | `supply_go.trade_until` | 师徒 |

## 4. 已知的重复：同一件事写了两份（待合并）

| 能力 | 份数 | 建议 |
|---|---|---|
| 小号没回城卷、队长去接 | `quanshou.fetch`（师徒，2026-11-05）、`projects/…/rescue_scrollless_apprentice.py` | 比较两边，保留实测过的那份做成共用，另一份改成调用它 |
| 队长补蓝 | 师徒的胡萝卜汁已取消（2026-11-05）；`projects/…/hannibal_soda.py` 是劲爆汽水 | **师徒线的新补蓝直接用 `hannibal_soda.py` 的做法**：挪到共用位置，两条线一起用 |
| 队长补给 | `factory/supply.py`（料理）、`r4_util.restock_master` + `buy_scroll.py`（师徒）、`projects/…/home_supply.py`（满爆方士） | 合成一个「回城补给」能力，补什么、补到多少由各产线传参数 |
| 卖东西规则 | `factory/sell.py` + `factory/items.py`、`sell_tradable.py`、`projects/…/home_supply.py` | 卖什么的规则都放进 `factory/items.py`，三处都只调用 |
| 古井带练 | `factory/welltrain.py`（决策）、`research/shitu/well10.py` | `well10` 已经复用 `welltrain` 的决策；继续往一处收 |
| 回城整理徒弟背包 | `tidy.py`（元素使：脱武器、丢整人道具、卖、开包、穿装备）、`trash.at_home`（勇者：丢葫芦 / 特赦令 / 整人道具、卖武器） | 合成一个「回城整理」，丢什么、卖什么、穿不穿武器按产品线配置 |

## 5. 以后加功能怎么放（例：队长修理装备）

修理装备本质上就是「回城时，队长走到修理 NPC、对话选『修理』、付钱」。做法：

1. **能力**：写一个函数 `repair(c)`，放进共用能力里「商店 / NPC 服务」这一类（现在可以先放 `research/shitu/` 下新建的
   `services.py`；以后整体迁到 `kit/`，见第 6 节）。它只管一件事：给它一个窗口，它把这个号的装备修好，失败就 `Stop` 并说清原因。
   里面用现成的 `take224.talk`（点 NPC 选选项）、`pp_chain.walk`（走到 NPC）。
2. **什么时候修**：由产品线决定。师徒线可以在 `r4_util.home` 末尾按开关调用（像 `trash.at_home` 那样）；料理线在它自己的补给流程里
   调用；满爆方士在它的回城补给里调用。
3. **开关**：哪条线要修、耐久低于多少才修，用环境变量或配置文件传进去，不要写死。
4. **测试**：给 `repair` 写一个不连游戏的单元测试（用假窗口），再在第 3 节表格里登记一行。

买药、卖东西、补蓝、开礼包都是同一个套路：**能力写一份 → 产品线选时机 → 开关控制差异**。

## 6. 往哪个方向整理（分步做，不一次大搬家）

产线一直在跑，所有脚本按文件名被 `line/route.py` 调用（`C('sell_tradable.py', ...)`），满爆方士项目也按模块名导入，一次性搬文件风险很大。
所以按下面的顺序一点点来，每一步都能单独上线：

1. **现在（本次已做）**：文档讲清楚哪些是共用能力、哪些是产品线；删掉已经没人用的旧脚本；产品线差异都改成开关。
2. **下一步**：建 `batch_provision/kit/` 包，先只放「转发」：`kit/bag.py` 里 `from research.shitu.r4_util import space_one` 这种。
   新代码一律从 `kit` 导入，旧代码不动。
3. **然后**：每次要改某个能力时，顺手把它的实现搬进 `kit/`，原位置留一行转发，跑测试，合并。重复的那几份（第 4 节）在搬的时候合成一份。
4. **最后**：`research/shitu/` 里只剩师徒线自己的任务脚本（拜师、考验、181、183、元素使 187 / 189 …），满爆方士、抓宠只依赖 `kit/` 和
   `provisioner/`。

目标目录（参考）：

```
batch_provision/
  provisioner/            游戏接口
  kit/                    共用能力：client / move / team / combat / npc / shop / bag / travel / services
  factory/                小强料理产品线
  lines/shitu/            师徒产品线（勇者、元素使：路线表 + 任务脚本）
  projects/fullcrit_mage_leveling_70/
抓宠一级宝宝/              独立产品线（只用 provisioner + kit）
```

## 7. 文档地图

| 想知道 | 看 |
|---|---|
| 接手的 AI 怎么开始、怎么跑测试、有哪些规矩 | 仓库根目录 `AGENTS.md` |
| 新电脑怎么部署 | [DEPLOY.md](DEPLOY.md) |
| 料理产线的设计 | [FACTORY_DESIGN.md](FACTORY_DESIGN.md)、`batch_provision/README.md` |
| 师徒产线怎么跑、出问题怎么办 | [SHITU_LINE.md](SHITU_LINE.md) |
| 换一个大号当师傅要准备什么 | [SHITU_MASTER_GUIDE.md](SHITU_MASTER_GUIDE.md) |
| 师徒任务的游戏事实（NPC、坐标、对话、奖励） | [SHITU_PIPELINE.md](SHITU_PIPELINE.md)、`research/shitu/ANALYSIS.md`、`GATHER.md` |
| 师徒线每个脚本是干什么的 | `batch_provision/research/shitu/README.md` |
| 各张图练级多快 | [LEVELING_STAGE0.md](LEVELING_STAGE0.md)、`research/shitu/EXP_MAP_TRIAL.md` |
| boss 任务（鹰王、虎力仙、老树叶已做）怎么做成共用能力 | [BOSS_TASKS.md](BOSS_TASKS.md) |
| 战斗记录 | [BATTLELOG.md](BATTLELOG.md) |
| 宠物连续施法、方士天之箭 | [PET_MAGIC_CONTINUOUS_CASTING_AND_TIANZHIJIAN.md](PET_MAGIC_CONTINUOUS_CASTING_AND_TIANZHIJIAN.md) |
| **游戏更新以后做什么**（地址、封包、实测；地址档案） | [GAME_UPDATE.md](GAME_UPDATE.md)；2.101 那次的逐项核对 [GAME_UPDATE_2101.md](GAME_UPDATE_2101.md) |
| 历次实跑记录（只做参考，不是操作手册） | `research/shitu/ROUND*_NOTES.md`、`BPLUS_NOTES.md`、`YUANSU_NOTES.md`、`notes/` |
