# 师徒产线（无人值守版）：4 个师傅 × 每批 4 个新号，1 级 → 41 级出师，一批接一批

这份文档讲 **第 4 轮（2026-10-27 夜 → 10-28）定型的无人值守产线**：怎么启动、怎么停、出错时它自己怎么恢复、
人什么时候需要介入、代码在哪、改代码要注意什么。
游戏事实（地图、NPC、任务对话、协议）在 [SHITU_PIPELINE.md](SHITU_PIPELINE.md)；工位化的设计讨论在
[SHITU_STATIONS.md](SHITU_STATIONS.md)；第 4 轮逐条问题和数据在
[research/shitu/ROUND4_NOTES.md](../batch_provision/research/shitu/ROUND4_NOTES.md)。

> **2026-10-28 新架构 v5**：`python -X utf8 -m line`（`research/shitu/line/`）把总控、批次、监管器、三段 shell 合成
> 一个 Python 程序，路线是一张数据表。设计、用法、和第 4 轮的对照见 **第 8 节**。**2026-10-28 第 5 轮（第 3 批）v5 首次实跑，
> 四队全部出师**（师傅 伏地魔1、伏地魔2、飞天把你射成蜂窝、舔尊；强号快约 46–57 分钟/批，见
> [research/shitu/ROUND5_NOTES.md](../batch_provision/research/shitu/ROUND5_NOTES.md)）。第 4 轮的 `r4_line.py` + shell 原样保留作退路。

---

## 0. 一页看懂

- **人**：4 个 70 级师傅 伏地魔1–4（队 a–d，**人工登录**，脚本没有他们的账号），每人带 4 个新建徒弟。
- **徒弟**：账号 cap21–cap36（每队 4 个账号），第 N 批用每个账号的第 N 个角色位，名字 亿万1、亿万2…
  （队 a 第 1 批 = 亿万1–4，队 b = 亿万5–8 … 第 2 批从 亿万17 起；规则在 `r4_env.sh`）。密码 = `local.toml [accounts]`。
- **一批的产出**：每个徒弟 41 级、勇者、约 **46–49 万金币**（留在徒弟身上，不交易、不删号）。
- **一批用时**（第 2 批实测，有 3 小时双倍）：前段约 37 分钟，到 40 级约 2 小时 40 分，后段 40–60 分钟，
  整批约 4–4.5 小时。四队并行约 **3.5 个出师号/小时**；第 1、2 批共 30 个号、1,464 万金币（ROUND4_NOTES.md）。
- **一键**：`python -X utf8 r4_line.py`（在 `batch_provision/research/shitu/` 里）。停：建空文件 `logs/LINE_STOP`。

## 1. 路线（用户定的，第 4 轮）

| 等级 | 地方 | 脚本（都在 r4_early / r4_mid / r4_late 里按顺序调） |
|---|---|---|
| 1 | 建号、出新手村、拜师 | `make_apprentices.py`、`bai_shi.py` |
| 1→10 | 阴森古井 | `well10.py` |
| 10 | 补给（回城卷 + 金币）、转职（任务 24 拳手）、任务 94 | `r4_util.py supply`、`zhuanzhi_take.py`、`quanshou.py`、`zhuanzhi_finish.py` |
| 10 | **自由市场散福老人领 3 小时双倍**（开局不吃背包地瓜） | `double_exp.py` |
| 10→15 | 海岸 PP鸡 认证、轮回之城 | `supply_go.py`、`pp_unlock.py`、`lunhui15.py` |
| 15→23 | 暗影迷城 → 大个王 | `maze_train.py` |
| 23 | 卖杂物、考验一二 | `sell_tradable.py --safe`、`trial_run.py --armor 3` |
| 23→25 | 八阵图 | `bazhen25.py 25` |
| 25→28 | 遗忘洞穴（师傅先接 224 才能采集，顺手采 9 花 3 石） | `take224.py`、`go_cave.py`、`logs/gather_all.sh`、`cave_train.py 28` |
| 28 | 徒弟接 224、打地头蛇（boss 题自动答） | `take224.py`、`dts.py` |
| 28→33 | 通天塔一区 | `tower28.py 33` |
| 33 | 考验三、礼包、穿装备、吃增益 | `r3_end.sh`、`open_packs.py`、`wear_best.py`、`eat_items.py` |
| 33→40 | 通天塔二区 | `tower2_go.py`、`tower2_patrol.py 40` |
| 40 | 任务 181 战士的试炼（拳手 40 → 乌龙村 → 树 → 古迹水晶 → 通天花露 → 倒花露） | `r4_late.sh` q181…pour |
| 40 | 任务 183 勇者的考验（物资 → 水源 → 尸体情报 → 蝎子王 → 神仙姐姐） | `r4_late.sh` q183…fairy |
| 40→41 | 出师（+20 万金币）、开礼包、收宝箱邮件卖掉 | `chushi.py`、`open_packs.py`、`mail_sell.py` |

双倍规则（用户 2026-10-28）：10 级转职后去散福老人领 3 小时；3 小时用完后每次吃 1 个背包里的加钙地瓜（1 小时）。
练级脚本到点会自己中断去领 / 吃（`r4_util.py double`、`double_due`）。

## 2. 三层控制结构

```
r4_line.py（总控，常驻）               每队一条线程：批次循环、监管器放弃后的恢复、排除卡死的徒弟、报警
 └─ r4_batch.sh TEAM BATCH          关上一批窗口 → make_apprentices 建号/登录 → 挂录包 → 师傅补回城卷 → r4_sup.sh early
     └─ r4_sup.sh → r4_supervise.sh     监管器：r4_early → r4_mid → r4_late，每段按 "== STEP" 分步
         │                              • 每次开跑前 r4_util windows：徒弟窗口没了自动重新登录，师傅没了 → MASTER_DOWN
         │                              • 日志 15 分钟不动 = 卡死，杀掉整棵进程树，当作一次失败
         │                              • 一步失败：回城（后段）/ 离队（中段），从这一步重跑，同一步最多 3 次
         └─ r4_run.sh → r4_early.sh / r4_mid.sh / r4_late.sh    每一步是一串 python 脚本，跳过已做完的
```

- 每队的环境（师傅、徒弟名、进度文件、日志名、账号对应）全由 `r4_env.sh TEAM`（加 `BATCH`、`SKIP`）算出来。
- 进度文件 `state_r4<队>[_b<批>].json`：拜师、补给、考验、`double3h`、`kills5`、`kills40` 等「做过没有」的记号，
  让任何一步重跑都不重复做、不等不会再来的系统消息。
- 后段每一步末尾有**任务进度闸门** `r4_util.py need QID N`：有人没到第 N 步就报错 → 监管器重跑这一步。
  没到的名字写进 `logs/<LOGID>_short.txt`，总控在实在过不去时把他们排除。

### 总控的恢复规则（r4_line.py）

| 情况 | 处理 |
|---|---|
| 监管器在某步放弃（3 次） | 全队回城，等 5 分钟，从那一步再交给监管器；最多 2 次 |
| 还不行，且是后段任务闸门没过 | 把没到的徒弟**排除**（留在师傅名下，不出师），其余人从那一步继续 |
| 建号失败（`SUP_GIVEUP make -`） | 等 5 分钟重来，最多 2 次 |
| `MASTER_DOWN`（师傅窗口没了） | 这一队停摆、写报警；其他队照跑。人工登录师傅后重启 `r4_line.py`，会从 line_state.json 接着跑 |
| 监管器进程没了、没有结论 | 从最后一个 `== STEP` 接着跑 |
| 被排除的人占满师傅名额 | 这一队停摆、报警 |

被排除的徒弟一直占着师傅一个名额（一个师傅最多 4 个徒弟），之后这一队每批少建一个号（`plan_skip`）。

## 3. 操作手册

所有命令在 `batch_provision/research/shitu/` 下运行（Git Bash 或 PowerShell 都行）。

```bash
# 启动（先手动登录 4 个师傅，站在逍遥村；徒弟账号的上一批窗口开着没关系，会被关掉）
nohup python -X utf8 r4_line.py >> logs/line.log 2>&1 &
python -X utf8 r4_line.py --teams a,c          # 只跑某几队
python -X utf8 r4_line.py --status             # 每队：完成的批、排除的徒弟、当前批、是否停摆
touch logs/LINE_STOP                           # 当前批跑完就停（不打断）；删掉它再启动就接着跑
tail -f logs/line.log logs/line_alert.log      # 总控日志 / 报警
tail -f logs/r4a_b3_sup.log                    # 某队某批的监管器（start / stopped / done / SUP_GIVEUP / HANG）
tail -f logs/r4a_b3_r4_late.log                # 某队某批某段的详细日志
python -X utf8 r4_stats.py                     # 各地图各等级每分钟经验、升一级要几分钟（expwatch 的数据）
```

- **设置** `r4_line.toml`：要跑的批次（= 账号的角色位，1–4）、恢复次数和等待、已知排除的徒弟。
- **账号用完**：cap21–36 每个账号 4 个角色位，第 4 批跑完就没有空位了。继续要么加账号（改 `r4_env.sh` 的号段规则），
  要么删掉出过师的旧角色（删号后约 3 小时才能用回那个位，见 memory machine-capacity-facts）。删不删、金币怎么处理由用户定。
- **经验监测** `python -X utf8 -m expwatch expwatch_shitu.toml`（在 `batch_provision/`）：每场战斗记一行到
  `logs/expwatch/shitu_battles.csv`，`r4_stats.py` 读它。
- **答题器**（`大冒险2_自动答题器_原生无感关窗版/启动答题器.exe`）要开着：地头蛇、蝎子王开打时的 boss 题它静默答；
  它没答，`boss_quiz.py` 自己答。

### 单独补一个人 / 一步

```bash
. ./r4_env.sh d                                   # 先拿到这一队的环境
SHITU_APPRENTICES=亿万7 FROM=corpse UNTIL=corpse bash r4_late.sh    # 只给亿万7 跑「找尸体」这一步
SKIP="亿万13" bash r4_sup.sh d late q183          # 不带亿万13，监管器从任务 183 接着跑
BATCH=2 SKIP="亿万13 亿万32" bash r4_sup.sh d tower2   # 第 2 批中段从通天塔二区接着跑
```

`FROM` = 从哪一步开始，`UNTIL` = 跑完哪一步就停；步骤名见 `r4_mid.sh`（start bazhen cave q224 snake tower1 end packs tower2）
和 `r4_late.sh`（q181 quan wulong tree crystal dew pour q183 corpse king fairy chushi finish）。

## 4. 人什么时候要管

| 报警 / 现象 | 要做的 |
|---|---|
| `MASTER_DOWN` | 登录那个师傅，回逍遥村，重启 `r4_line.py` |
| 某队停摆：某步恢复 2 次都不行 | 看 `logs/<LOGID>_r4_late.log` 最后的「停止:」，按第 5 节对症处理，然后 `r4_sup.sh` 从那步接着跑，或重启总控 |
| 徒弟被排除（占名额） | 决定它的去留：留着等以后能重做任务，或解除师徒（脚本 `ANALYSIS.md` 有协议，目前没做成自动） |
| 账号角色位用完 | 加账号或删旧角色（用户决定） |
| 游戏更新 / 地址变了 | `game_addrs` / `world.py` 的偏移要重新确认，见 memory game-calls-and-battle-facts |

## 5. 第 4 轮踩过的坑（已经在代码里处理，改代码时别把它们弄回来）

| 坑 | 现在的处理 | 代码 |
|---|---|---|
| 路上打怪的掉落塞满背包，任务物品（日记、花露瓶、情报、蝎爪）没进包，NPC 之后不再给 | 每次和任务 NPC 对话、开打 BOSS 前清出 2 格；清之前先逃出战斗、站稳（战斗中丢东西会被忽略） | `r4_util.space_one`、`team_npc.talk`、`scorpion_king` |
| 蝎子王只给部分人蝎爪；有蝎爪的人当队长再挑战，BOSS 说「走开」 | 没拿到的人当队长再打，最多 3 次 | `scorpion_king.main` |
| 「与邀请者之间有障碍」：徒弟就在 54 像素外也进不了队 | 邀请失败后师傅走到徒弟脚下再邀请；徒弟 60 秒走不过来就师傅走过去 | `teamwalk.regroup` |
| 徒弟战斗中倒下（第 3 轮规矩：停下等人） | 无人值守：倒下后战斗结束就是满血、还在队里（亿万29 实测 1935/1935），记数继续；同一人一段里倒下 5 次才停（`MAX_FALLS`） | `maze_train` |
| 走近 NPC 点了没对话框（亿万24 水晶、尸体，亿万28 水源），服务器也没提示 | team_npc：走开 150 像素再走回来重点一次；还不行由监管器回城重跑（这一轮重跑都成功了） | `team_npc.talk` |
| 「你所邀请的对象与你距离太远」，两边客户端却显示距离 0（服务器上的位置没更新，苦无沙漠里见过） | 徒弟左右走 60 像素把位置发给服务器，师傅再走过去重新邀请；失败时日志会打印双方收到的系统提示 | `teamwalk.regroup` |
| 一次性的系统消息（拳手杀够、花露采满）重跑时等不到 | 记进度：`kills5`、`kills40`；花露看背包里有没有花露瓶 10692 | `quanshou`、`quan100`、`dew_team` |
| 寻路在某个点原地重试几百次 | 同一处连续卡 20 次就报错，交给监管器回城重来 | `maze_train.Route.walk` |
| 落单徒弟在野外遇怪，回城一直等战斗结束 | 不在队里 / 自己是队长的先逃跑 | `quanshou.flee`、`teamwalk.flee` |
| 师傅回城卷用光 | 回城后不足 10 张自动去铁公鸡补到 60；没卷时向身边徒弟借 5 张 | `r4_util.home`、`quanshou.borrow` |
| 一个脚本 import 另一个脚本时偷偷改了 `maze_train.STAGES`（去洞穴的队跑去了夕阳草原） | 只在 `main()` 里设置 STAGES；导入别的模块后要恢复 STAGES | `quanshou`、`tower28`、`tower1_go`、`guji_entrance` |
| 改正在运行的 shell 脚本把运行中的队搞乱（`command not found`） | 所有阶段脚本和监管器整段 `{ … exit }` 包起来，bash 先读完再执行 | 见 memory feedback-running-bash-edits |
| 进古迹二层点一次 10153 不一定传 | 最多点 3 次，中间走到 (1428,924) | `guji_entrance` |
| 人已在古迹里时重跑，会去找一层入口而走不到 | 先全队回城 | `guji_entrance` |
| 收邮件时背包 39/40，一封也没取 | 先卖杂物、清 6 格 | `r4_late.sh` finish |
| 城里找完 NPC（嗜杀勇者、NPC 304）后徒弟在别的地图，组队时先白试 3 次接受、再一个个跨图走回来（每批每队约 6 分钟） | 不在同一张图：师傅在逍遥村就让徒弟用回城卷，否则直接走过来；同图接受失败 1 次就走过来；嗜杀勇者之后全员回城 | `well10.form_team`、`r4_late.sh` wulong |
| 野外做完一件事（拿树、看 / 浇黑色水晶、拾取情报、最后一朵花、最后一瓶蝎子药）后先全员重新组队，下一条命令又是全员回城（回城本来就解散队伍） | `team_npc.py --no-regroup`；`dew_team`、`scorpion_water` 全员做完就不再组队。**规则：下一步是回城的，前一步结尾不组队** | `team_npc`、`dew_team`、`scorpion_water`、`r4_late.sh` |
| 任务 181 第 4 步的日记丢了，树 NPC 953 不再理这个号 | 目前无解，只能排除（亿万13） | — |

## 6. 代码地图（第 4 轮新增 / 改动）

| 文件 | 作用 |
|---|---|
| `r4_line.py` / `r4_line.toml` | 总控和它的设置 |
| `r4_batch.sh` | 一批：关旧窗口、建号、挂录包、补卷、启动监管器 |
| `r4_sup.sh` → `r4_supervise.sh` | 监管器（`r4_sup.sh` 只是转发，别往里加东西） |
| `r4_env.sh` | 每队环境：`BATCH`、`SKIP` → 徒弟名、`PAIRS`（账号:角色）、`LOGID`、进度文件 |
| `r4_run.sh` | 跑一段，日志追加到 `logs/<LOGID>_<段>.log` |
| `r4_early.sh` / `r4_mid.sh` / `r4_late.sh` | 三段，每段若干 `== STEP`，`FROM` / `UNTIL` 控制起止 |
| `r4_util.py` | home / leave / restock / supply / double / need / windows / space 等小工具 |
| `r4_stats.py` | 经验统计表 |
| `r4_watch.sh` / `r4_stall.sh` | 给人（或 AI）看的等待器：监管器有新结论 / 后段 30 分钟没进步就退出 |
| `double_exp.py` | 散福老人领 3 小时双倍 |
| `bazhen25.py`、`cave_train.py`、`tower28.py`、`tower2_patrol.py` | 练级段（会在双倍到点时中断去领） |
| `boss_quiz.py`、`BOSS_QUIZ.md` | boss 开打答题 0x46f5 |
| `batch_provision/expwatch/` | 经验监测（每场战斗一行） |
| `batch_provision/tests/test_r4_line.py` 等 | 单元测试：`python -X utf8 -m unittest discover -s tests`（在 batch_provision 下） |

## 7. 给接手的 AI

1. 先读：这份文档 → `research/shitu/README.md`（模块地图）→ `SHITU_PIPELINE.md` 第 3、5、6 节（游戏事实、协议、坑）
   → `ROUND4_NOTES.md`（这一轮的数据）。memory 目录里 `shitu-flow-2026-10-27.md`、`feedback-running-bash-edits.md`
   是之前会话记下的经验。
2. 规矩（用户定的）：一个游戏窗口同一时间只能有一个脚本在操作；野外师傅带队、徒弟不单独走；不经用户同意不交易金币、
   不删号、不解除师徒；脚本要能重跑（每一步先看已经做到哪）；提交前跑单元测试；用户是中文用户，说明用中文、讲清楚原因。
3. 排查一个失败：`logs/<LOGID>_sup.log` 找「stopped in step X」→ 打开对应段的日志，看那一步最后几行和「停止:」→
   需要看服务器怎么回的，用 `monitor.Tap(pid, from_end=True)` 抓 0x46ff 系统消息（例子见 ROUND4_NOTES）。
4. 改 shell 脚本：只改整段包裹过的文件（`{ … exit }`）；没包裹的、正在跑的，新写一个文件替代。
   改 Python 不影响正在跑的进程（已经加载）。
5. 新加一个任务步骤：在 `r4_late.sh` 里加 `if at <名>; then … U need QID N; fi`，让每一步都能单独重跑、末尾有闸门。
6. 新架构 v5 的接手要点在第 8.7 节。

## 8. 新架构 v5（2026-10-28）：一个 Python 程序 + 一张路线表

### 8.1 为什么重做

第 4 轮能跑完，但一个问题要改好几个地方，有些坑是结构造成的：

| 第 1–4 轮的问题 | 根因（结构上的） | v5 怎么解决 |
|---|---|---|
| 改 shell 脚本把正在跑的队搞乱（exit 127） | bash 按字节偏移边读边执行 | 不再执行任何 shell 脚本；Python 进程启动时就把代码加载完了 |
| 五层套娃：r4_line → r4_batch → r4_sup → r4_supervise → r4_run → r4_*.sh | 每层各管一点恢复，要靠解析日志里的 `== STEP`、`SUP_GIVEUP` 互相传话 | `runner.py` 一个类管全部恢复；断点直接记在 `logs/<LOGID>_line.json`，不靠解析日志 |
| 中段 cave 步跑的是 `logs/gather_all.sh` | `logs/` 被 gitignore，新克隆的仓库里没有这个文件 | 采集改成 `line.ops gather`；测试保证路线里没有任何东西从 `logs/` 运行 |
| q181 步没有任务闸门 | 闸门是手写在 shell 里的，漏了也没人知道 | 路线是数据，测试检查后段每个任务步都以 `U need QID N` 结尾（这次查出 q181 漏了，已补 `need 181 1`） |
| 组完队马上回城（白组队） | 规则只在人脑子里 | 测试：同一步里后面有回城的 `team_npc` 必须带 `--no-regroup` |
| 背包满丢任务物品 | 同上 | 测试：tree / dew / corpse / king 第一条命令必须是 `U space` |
| 前段 r4_early.sh 没有步骤标记，失败只能从头来 | 一个大块 | 前段拆成 7 步（bai_shi、well、zhuanzhi、double3h、pp、lunhui、maze），每步单独重跑 |
| 改路线要同时改 shell、监管器的清场方式、总控的 resume 映射 | 路线、清场、恢复散在 4 个文件 | 每一步自己带：命令、跳过条件（`unless`）、重跑前清场（`retry`）、环境变量 |
| 打怪里的题（0x46F4）没人答就卡住 | 答题器没开，脚本不知道 | 每批开始前检查 `启动答题器` 在不在，不在就报警 |

### 8.2 结构

```
line/__main__.py   总控：每队一条线程，按 line.toml 一批接一批；LINE_STOP；--status / --dry-run / 手动补跑
   └─ line/runner.py   跑一队一批：逐步执行 route.ROUTE；健康检查、卡死检测、重试阶梯、排除、断点
        ├─ line/route.py   路线表（make → early → mid → late，共 32 步），唯一的流程定义
        ├─ line/plan.py    谁：师傅、徒弟名、账号、LOGID、环境变量（规则和 r4_env.sh 一致，测试对比过）
        └─ line/ops.py     原来 shell 里内联的小操作：close / arm / master_up / home_village / q94 /
                           take224_master / gather / fairy / when 条件
   各步调用的还是原来那些已经实战过的脚本（bai_shi.py、tower2_patrol.py、team_npc.py、r4_util.py …），一个没改。
```

### 8.3 用法（在 `batch_provision/research/shitu/` 下）

| 做什么 | 命令 |
|---|---|
| 全部队一批接一批 | `python -X utf8 -m line` |
| 只跑几队 | `python -X utf8 -m line --teams a,c` |
| 看进度 | `python -X utf8 -m line --status` |
| 只看要执行的命令（不碰游戏） | `python -X utf8 -m line --dry-run --teams d` |
| 一队一批补跑几步 | `python -X utf8 -m line --team a --batch 3 --from king --until king` |
| 只带几个徒弟补跑 | 再加 `--apps 亿万35,亿万36` |
| 停 | 建空文件 `logs/LINE_STOP`（当前批跑完再停） |

前提和第 4 轮一样：4 个师傅人工登录、站在逍遥村；`启动答题器.exe` 开着。
日志：`logs/<LOGID>_line_<段>.log`（每步一行 `== STEP 名 时间 apps=…`，每条命令一行 `$ …`），
进度：`logs/<LOGID>_line.json`（done 步骤、排除的人、事件流水），全局：`logs/line_state.json`、报警 `logs/line_alert.log`。

**换师傅 / 加队**（2026-10-28 起）：每队在 `line/line.toml` 里一段 `[team.<队名>]`：`master` 师傅角色名、`slot` 用第几组账号和徒弟名
（0–3：账号 cap(21+4·slot)…+3，第 N 批徒弟 亿万(16(N−1)+4·slot+1)…+4）、`gold` 启动金。`teams = [...]` 选这次跑哪几队。
队名同时是 `logs/line_state.json` 的键和 LOGID（`r4<队名>_b<批>`），所以换师傅就起个新队名，旧师傅的历史和排除名单（比如伏地魔4 名下的
亿万13）不会串过来。同一组账号（同 slot）或同一个师傅不能同时在两队，总控启动时会检查。现有队：a 伏地魔1、b 伏地魔2、c 伏地魔3、
d 伏地魔4、fei 飞天把你射成蜂窝（slot 2）、tian 舔尊（slot 3）。

### 8.4 一步失败以后（runner.py，参数在 line/line.toml）

1. 每次跑一步之前：师傅窗口不在、或窗口在但掉线（读不到世界 / socket=-1）→ 这一队停摆（MASTER_DOWN，人工登录师傅后
   用 `--team <队> --batch <批>` 单独续跑，从断点接着跑，别的队不受影响）；徒弟窗口不在或掉线 → `r4_util windows` 关窗、自动重新登录
   （建号段只查师傅）。窗口检查连续 10 次失败也停摆。
2. `unless` 成立（比如已经 25 级）→ 这一步算完成。
3. 日志 `silent`（900）秒没变化 = 卡死 → 杀掉这一步的进程树，算一次失败。
4. 失败阶梯：第 1–3 次失败 = 清场（`retry`: home 回城 / leave 原地离队）+ 5 秒再跑；第 4–5 次 = 全员回城 + 等 300 秒再跑；
   还不行且是后段闸门没过 → 把 `logs/<LOGID>_short.txt` 里的徒弟排除（留在师傅名下不出师，以后每批少建一个），
   其余人从这一步重来；否则这一队停摆、报警，别的队照跑。

### 8.5 加 / 改一步

在 `line/route.py` 的 `ROUTE` 里加一个 `Step(名, 段, (命令...), retry=..., unless=..., env=...)`，然后跑
`python -X utf8 -m unittest tests.test_line`（在 batch_provision 下）。测试会检查：脚本文件存在、ops 和条件名存在、
没从 logs/ 运行、回城前不组队、后段任务步有闸门、拿任务物品前清背包。新的游戏小操作写成 `line/ops.py` 里的一个函数。

### 8.6 答题器（启动答题器.exe）现在也解锁辅助工具

`大冒险2_自动答题器_原生无感关窗版/src/controller/native_unlock.h`：每发现一个游戏窗口，注入答题 DLL 之后再给它打两个
内存补丁，游戏自带「辅助工具」里的 **战斗辅助页** 和 **自动采集页** 不再显示「（待激活）」、可以设置。
来源是 Gemini 目录里的「战斗辅助原生界面解锁工具」（2.97 版），只拿了特征码和补丁字节，地址按 2.100 重新核对
（战斗 +0x5F570、采集 +0x5F2BF，exe 里各只出现一次，`tools/native_unlock_test.cpp` 每次编译都会核对）。
启动参数 `--no-unlock` 关掉。**新答题器只编译到 `src/build/`，还没换上线**（换法见 src/README.md「上线」）。

### 8.7 给接手的 AI（v5）

1. 流程定义只看 `line/route.py`；第 4 轮 shell 是历史版本，改流程别再改它们。
2. 跑之前先 `--dry-run` 看一遍命令；第一次真跑建议 `--teams a` 单队、有人看着，确认一批完整跑完再开四队。
3. 第 5 轮已在游戏里验证：v5 执行器、断点续跑、手动 `--team` 补跑、`line.ops gather`、地头蛇步从任意位置出发。
   还没验证的：答题器的解锁补丁（没在游戏里打开辅助工具看过）；`teamwalk._walk` 战斗不计时（第 5 轮花露失败后才改）。
4. 每批之后：`python -X utf8 r5_compare.py --teams ... --batch N` 出每步用时、各图每分钟经验、师傅蓄力（`sp_watch.py` 要在跑批时开着）。

