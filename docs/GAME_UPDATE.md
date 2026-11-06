# 游戏更新以后要做什么：地址、封包、实测

更新：2026-11-05。游戏大约每周更新一次。这一页讲：每次更新后要改什么、哪些封包可能要重新抓、按什么顺序做、新电脑上没有旧 exe 怎么办。
上一次真实更新（2.100 → 2.101）的逐项核对记录见 [GAME_UPDATE_2101.md](GAME_UPDATE_2101.md)。

## 1. 一句话

- **地址**：几乎每次更新都会挪，用 `addrscan` 自动找，代码里有 62 个特征码，**不需要旧 exe**。
- **封包**：极少改。改封包要服务端和客户端一起改，旧客户端会直接用不了，游戏公司不会轻易动。
  目前知道的只有一处：**2.100 把商店买卖包（0x55）的数量从 1 字节改成 2 字节**，旧格式被服务器拒收（回 0x40c1；共用商店模块漏改，
  满爆方士项目 11-03 才发现）。2.101 逐项核对过，没改任何封包（组包函数和 2.100 逐条指令一致）。更早的 2.98 → 2.99 没逐项核对封包。
- **哪些可能要重新抓**：只有「我们自己拼包体发出去」的那十几个动作（第 3 节表 B）。调用游戏自己函数的动作（走路、寻路、点 NPC、选对话、
  战斗指令、放技能、宠物魔法、抓宠用道具、组队接受 / 离队、答题提交）由游戏自己组包，封包怎么变都跟着变，**只需要改函数地址**。

## 2. 每次更新后按这个顺序做

1. **看版本**：双击 `batch_provision/一键检查环境.cmd`。它会比对 exe 的 SHA256（`native/launcher.cpp` 的 `CLIENT_HASHES`），并跑 `addrscan`。
2. **找新地址**：`cd batch_provision && python -X utf8 -m provisioner.addrscan`。每个地址列出「代码里的值 / 新 exe 里找到的值 / 一致还是不对」，
   以及代码以外还要改的文件（DLL 源码、答题器的 `game_addrs.h`）。按提示改完，重编 `native/`（`build.ps1`）和答题器。
   - 有「没找到」的：特征码在新版里变了，要拿上一版 exe 和新 exe 逐条指令对照（做法见 GAME_UPDATE_2101.md「怎么做的」）。
     上一版每个地址的值查地址档案：`python -X utf8 -m provisioner.addrscan --history`（第 4 节）。
3. **存档案**：全部一致后 `python -X utf8 -m provisioner.addrscan --save`，把新版本的版本号、SHA256、全部地址存进
   `provisioner/addr_versions/<版本>.json`，提交进仓库。把新 exe 的 SHA256 加进 `CLIENT_HASHES`。
4. **只读核对**：开一个窗口进游戏，只读内存（`world.read_world`、背包、队伍），确认读到的东西合理，再做任何写操作。
5. **封包实测**（第 5 节）：在一个测试号上把表 B 的动作各做一次，最小代价验证。有不成功的，按第 6 节重新抓包。
6. **先跑一队一批**，确认整批走通再全开。

## 3. 动作清单：哪些跟着游戏走，哪些要我们自己维护

### 表 A：调用游戏自己的函数（游戏组包，只需改地址，`addrscan` 会找）

| 动作 | 游戏函数（`provisioner/game.py`） | 谁在用 |
|---|---|---|
| 同图走路 / 官方寻路 / 取消寻路 | `MoveTo`、`Navigate`、`CancelNav` | 全部 |
| 点 NPC / 选对话选项 | `ClickNpc`、`SelectNpcDialogEntry` | 全部 |
| 战斗指令：普攻 2、逃跑 8、捕捉 0xB | `SendFightCmdPacket` | 全部，抓宠 |
| 人物技能 / 宠物魔法 | `CastSkillToFighter`、`CastPetMagicToFighter` | 带队、满爆方士 |
| 接受组队 / 离队 | `RVA_TEAM_ACCEPT`、`RVA_TEAM_LEAVE` | 全部 |
| 对战斗目标用道具（抓宠）、读战斗单位名字 | `UseItemToFighter`、`GetFighterName`（`抓宠一级宝宝/fighters.py`，有签名检查） | 抓宠 |
| 答题提交、关答题框 | `QUIZ_SUBMIT`、`CLOSE_DIALOG`（`boss_quiz.py`、答题器） | 全部 |

### 表 B：我们自己拼包体，用游戏的发包函数（`RVA_SEND`）发出去（**格式一变就要重新抓**）

| 包号 | 动作 | 包体 | 在哪 | 谁在用 |
|---|---|---|---|---|
| 0x0002 / 0x0003 | 建角 / 删角 | 见 `provisioner/protocol.py` | `make_apprentices.py`、`factory/wipe.py` | 料理、师徒 |
| 0x0030 | 邀请组队 | 33 字节：目标、自己等级、会话字节、自己名字 | `game.team_invite` | 全部带队 |
| 0x0035 | 移交队长 | `<I 0><I 新队长角色号>` | `chushi.py`、`fifth.py` | 师徒 |
| 0x0047 | 移动物品（穿 / 脱装备、换格） | 12 字节 `<IBBHBBH>` | `game.unequip`、`wear_best.py` | 师徒、料理 |
| 0x0048 | 丢物品 | `<IBBH>(0, 0, 格, 数量)` | `drop_prank.py`、`trash.py`、`r4_util.space_one`、`master_bag.py`、`farm.py` | 师徒 |
| 0x0049 | 用物品（吃、开包、回城卷） | 19 字节 `<IIiI>(0,0,-1,0)` + (0, 格, 1) | `game.use_item` | 全部 |
| 0x0050 / 0x0051 / 0x0055 | 商店：点 NPC、选「购买」、**买 / 卖**（2.100 改过：数量 2 字节） | `<IIBBHBH>`；卖一次最多 20 格 | `factory/supply.py`（`ShopClient`）、`buy_scroll.py`、`buy_gear.py`、`projects/boss_gear_5/take_eagle.py`（莫吉接任务，2026-11-06） | 全部 |
| 0x0060 / 61 / 63 / 65 | 交易：邀请、接受、放东西 / 金币、确认 | 见 `game.py` | `supply_go.trade_until`、`factory/gold.py` | 全部 |
| 0x0070 | 加天赋点 | 24 字节 `<6i>`，第 N 个 = 某项属性 | `game.add_talent` | 师徒、满爆方士 |
| 0x0082 / 0x0083 | 飞鞋记点 / 飞回 | 4 个 0 字节（服务器不看） | `game.shoe_record`、`shoe_return` | 师徒、满爆方士、料理 |
| 0x0105 | 设置出战宠物 | 见 `pet_level_40.py` | 满爆方士 | 满爆方士 |
| 0x0197 | 拜师弹窗点「同意」 | `<I 0><u8 1>` | `bai_shi.py` | 师徒 |
| 0x01E5 / 0x01E2 / 0x01E3 | 邮件：选中、打开、取附件 | 见 `mail_sell.py` | `mail_sell.py` | 师徒 |
| 0x1005 | 手动魔法技能（方士天之箭，抓包得到的前缀） | 见 `game.cast_magic_skill_captured` | 满爆方士 | 满爆方士 |

### 表 C：我们读的服务器回包（格式一变，计数 / 判断会出错，但不会发错东西）

| 包号 | 是什么 | 谁在读 |
|---|---|---|
| 0x46FF | 系统消息文字（「已经杀死了 N 个」「已经采集 N 滴花露」「物品栏已满」…） | 打拳手、采花露、组队失败原因、`battlelog` |
| 0x46F4 / 0x46F5 | 战斗答题 / boss 开打答题 | 答题器、`boss_quiz.py` |
| 0x4003 / 0x4004 | 建角 / 删角回包 | `make_apprentices.py`、删号 |
| 0x4338 / 0x4337 | 拜师弹窗 / 拜师成功 | `bai_shi.py` |
| 0x40C0 / 0x40C1 | 商店货架 / 买卖被拒 | `factory/supply.py` |
| 0x4411 / 0x4416 | 邮件列表 / 取附件成功 | `mail_sell.py` |
| 0x4100 / 0x4101 / 0x472A … | 战斗开始、单位、结束、结算 | `battlelog/` |

> 绝大多数状态（地图、坐标、等级、背包、队伍、对话框、任务）是**读内存**得到的，不靠回包；内存结构的偏移也在 `addrscan` 的特征码里。

## 4. 地址档案（换电脑不怕没有旧 exe）

`batch_provision/provisioner/addr_versions/<版本>.json`：每个版本一个文件，只有数字（版本号、文件大小、SHA256、PE 时间戳、全部地址），
**不含游戏程序**（仓库是公开的，游戏 exe 不能放进来）。现在有 2.100.2642.6130 和 2.101.2643.6157 两份。

- 看每个地址各版本的值（默认只列变过的）：`python -X utf8 -m provisioner.addrscan --history`，或指定 `--history UI SEND`。
- 新版本核对完：`python -X utf8 -m provisioner.addrscan --save`。
- 测试 `tests/test_addr_archive.py` 保证当前版本的档案和代码里的值一致。

**旧 exe 自己存一份在仓库以外**（网盘、移动硬盘或私有仓库），文件名带版本号，比如 `WAATClient_2.101.2643.6157.exe`，用档案里的 SHA256 核对。
只有 `addrscan` 有地址找不到、要逐条指令对照时才用得上它。

## 5. 封包实测（表 B，每次更新后在测试号上做一遍）

都选代价最小的做法；做完看日志或游戏里有没有生效。

| 动作 | 怎么测 | 成功的样子 |
|---|---|---|
| 用物品 0x49 | `eat_items.py --name 萝卜糕 测试号` | 萝卜糕少一个 |
| 移动物品 0x47 | `unequip_all.py 测试号`，再 `wear_best.py 测试号` | 装备脱下、穿上 |
| 丢物品 0x48 | 背包放一个 0 品质杂物，`drop_prank.py --name 那个杂物名 测试号` | 背包里没了 |
| 商店买 / 卖 0x55 | `buy_scroll.py <现有张数+1> 测试号`（补到这么多张，也就是买 1 张）；`sell_tradable.py --zawu 测试号` | 回城卷 +1；杂物卖掉、金币增加；日志没有 0x40c1 |
| 飞鞋 0x82 / 0x83 | `shoe_point.py record 地图 X Y 测试号`，走开后 `shoe_point.py fly 地图 X Y 测试号` | 记录点读回来对；飞回原地（1 小时冷却） |
| 交易 0x60–0x65 | `一键发金币.cmd`（调度员给小号 500 金币） | 小号金币 +500 |
| 邀请组队 0x30 | 任意带队脚本开头组队，如 `go_goal.py` | 日志「同时邀请 … 进队 …」 |
| 加天赋 0x70 | 新号升级时 `well10.py` 自动加点 | 体质增加（不可撤销，用新号测） |
| 建角 / 删角 0x02 / 0x03 | `make_apprentices.py` 建一个测试角色，再删掉 | 选角列表里出现 / 消失 |
| 移交队长 0x35、拜师 0x197、邮件、出战宠物、手动魔法 | 跟着实际流程跑时看日志 | 对应步骤不报错 |

## 6. 某个封包不灵了：怎么重新抓

1. 在游戏里**手动**做一次这个动作，同时开着录包：`python -X utf8 research/shitu/monitor.py 角色名`（录到 `logs/net_<角色>.jsonl`）。
2. 找到这次动作发出的包（包号和表 B 一样的那条），把包体和代码里拼的比一比：通常是某个字段变宽了、多了一个字段，或者顺序变了。
3. 改对应的拼包函数（表 B「在哪」那一列），在测试号上按第 5 节重测，再把这次变化记进这一页第 1 节。
4. 包号也变了的话，在客户端里按旧包号找组包函数（GAME_UPDATE_2101.md 用过的办法），或者直接用录到的新包号。

以后可以继续把表 B 里能换成游戏函数的动作换掉（比如商店买卖、丢东西如果找得到客户端自己的函数），换掉一个就少一个要维护的封包。
