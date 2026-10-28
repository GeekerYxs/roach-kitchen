# 答题器源码（2.100 版 + boss 题）

这里是 `启动答题器.exe` 和 `quizbot_hook.dll` 的源码。原来只有编译好的文件，源码在 `D:\Codes\Gemini_Prj\smsm2_game\quiz_dismiss_bot\`（2.98 地址，不在 git 里）。2026-10-27 复制进来，改成 2.100，并加上 boss 题。

## 和原来发布版的关系

- 原来包里的 2.100 版是把 2.98 编译产物里的地址数字直接改掉（提交 8c94697）。逐字节对比过：除了这些地址，和 Gemini 目录里编出来的文件完全一样，所以这份源码就是发布版的源码。
- 地址全部集中到 `dll/game_addrs.h`，以后换游戏版本只改这一个文件。
- Gemini 目录里的 DLL 源码在编译之后（10-09）又加了一个「本场最低血量」功能，从来没发布过。它要调用三个 2.98 地址（0x10070、0x100D0、0x5166DC），2.100 里对应在哪还没核实，调错会让游戏崩溃。所以用 `QB_ENABLE_MIN_HP` 开关关掉了（默认 0）。关掉以后，战斗结算事件里会多出 `min_hp` / `max_hp` 两个字段，值都是 0，控制器不用它们。

## boss 题（0x46F5）怎么做的

协议和内存见 `batch_provision/research/shitu/BOSS_QUIZ.md`。

| 步骤 | 在哪 | 做什么 |
|---|---|---|
| 收题 | `dll/quizbot_hook.cpp` handle_frame | 收到 0x46F5，跳过 4 字节 char_id，按 0x46F4 的格式解析，丢掉空的第 5 项，推 `{"type":"question","kind":"map",...}` |
| 决策 | `controller/boss_quiz.h` decide | ① 按题号查 `data\boss_bank.tsv`，按答案文字找选项，选项换了位置也能找到；② 查不到就排除干扰项（书名号、`data\boss_decoys.txt` 里的字），剩一个就建议它，剩几个就挑和题目共有字最多的 |
| 作答决定 | `controller/main.cpp` handle_map_question | **静默，不弹窗**：一律等 1.5 秒后自动答 `bq::decide` 的 guess（题库命中 > 排除法建议 > 排除干扰项后第一个）。控制台里「[猜的]」标红 |
| 作答 | `dll/quizbot_hook.cpp` answer_map_quiz | 走游戏自己的提交函数：面板 `[ui+0x10C8]` 开着、题号对得上、+0x1B4==1 时，写 +0x1AC，调 0x224330，再 CloseDialog。只发一次 0x1F05，和手动点完全一样。3 秒内面板没就绪就直接发 0x1F05 包（答题框可能留在屏幕上） |
| 记表 | `report_map_result` → `handle_map_result` | 收到「测试通过！」后报出题号和下标，自动答的、你手动答的都会报，控制器记进 `boss_bank.tsv`，其余选项进 `boss_decoys.txt` |

战斗里的题（0x46F4）流程完全没动。

## 编译和测试

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

- 先跑两个离线测试，任何一项失败就不编：
  - `protocol_test`：原来的 10 组，加上 boss 题 2 组真实录包。0x46F5 解析出的题号、char_id、GBK 题目都对；构造的 0x1F05 和客户端手动答题时发的线上字节**逐字节一致**。
  - `boss_quiz_test`：用 9 道实录 boss 题测决策逻辑。
    - 空题库时：8 道建议对、1 道不建议（钟表），0 道建议错；
    - 留一法（用另外 8 道学到的干扰项猜第 9 道）：全对或不建议，没有错的；
    - 另外测了选项换位置、TSV 文件来回读写。
- 产物在 `src\build\`，**不会覆盖包里正在用的文件**。

## 上线记录

- 2026-10-27 22:14 上线（弹窗确认版）。22:26–22:28 欧皇、伏地魔2、伏地魔1 各打一次 boss，3 道都是题库里没有的新题，弹窗点「是」按建议答，**全部「测试通过」**，面板自己关了，3 道都记进了题库。
  - 已确认：boss 面板 +0x1C 弹题时 = 1；走原生提交 + CloseDialog 没问题；每题只发一次 0x1F05。
- 2026-10-27 22:36 换成静默版（只换 启动答题器.exe，DLL 没变）。
- 22:17 那次「打 boss 断线」：3 个窗口在 23 秒内被服务器断开，欧皇当时没收到 boss 题，DLL 也没发东西；旧版时 10-26 06:13、10-27 18:00 出现过同样的集体断线，判断与答题器无关。

## 还不知道的

1. 答错时服务器说什么。没见过；带「错 / 失败 / 不正确」的提示会被当成答错，不记表。静默模式下猜的题可能答错。
2. 师徒脚本的兜底（`batch_provision/research/shitu/boss_quiz.py`，答题器没开时自己答）还没在游戏里跑过。

## 上线（要先问用户）

1. 关掉正在跑的 `启动答题器.exe`。
2. 备份包里的 `启动答题器.exe`、`quizbot_hook.dll`。
3. 把 `src\build\quizbot.exe` 复制成 `..\启动答题器.exe`，`src\build\quizbot_hook.dll` 复制成 `..\quizbot_hook.dll`。
4. 已经开着的游戏窗口里注入的是旧 DLL（DLL 卸不掉），要**重开游戏窗口**才会用上新 DLL。
