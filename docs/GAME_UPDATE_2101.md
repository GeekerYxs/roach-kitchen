# 游戏更新到 2.101：地址核对报告（2026-10-29）

## 结论

- **游戏 exe 确实变了**：`WAATClient.exe` 版本号 2.101.2643.6157（之前 2.100.2642.6130），大小 6,798,336 字节，
  SHA256 `ce609262…6100`（2.100 是 `bc7d6c22…b5ec`），PE 时间戳 0x6AE0AF0A（2.100 是 0x6AD8AC71）。
- **几乎所有地址都挪了**，旧代码直接跑会读错内存、调错函数：
  - 全局指针（UI / 战斗 / 会话 / 连接 / 登录 / 选角）整体 +0x1514C，玩家指针 +0x15140，忙碌掩码和编解码表 +0xD0C0。
  - 函数地址各挪了 +0x20 到 +0x9D00 不等（每个函数的指令和 2.100 一条一条对得上，只是地址和结构偏移变了）。
  - **界面窗口类整体变大了 0x230 字节**（从 +0x174 那个字段开始往后的都挪了）：UI 根对象上的面板指针、
    答题面板 / 寻路 / 飞鞋面板 / 登录框 / 选角框里的字段都跟着挪了。
  - 战斗对象里的字段 +8（站位数组、自己位置、阵营、宠物位置）。
  - **会话对象（地图、等级、背包、金币、装备、技能、宠物、任务）完全没变**。
  - 网络包格式没变（建角 / 删角 / 邀请组队 / 卖东西的组包函数和 2.100 指令一致），编解码表内容逐字节一样。
- 所有用到的地址都改好了，**单元测试 835 个全过**，在开着的 5 个 2.101 窗口上**只读**核对了读内存的部分，全部对得上。
- 新增 `batch_provision/provisioner/addrscan.py`：**用特征码在 exe 里自动找全部 64 个地址**，和代码里的值比对。
  这套特征码在 2.100 和 2.101 里都只匹配一次而且值都对；拿两个版本前的 2.98 exe 试，64 个能找到 62 个而且都是
  2.98 的正确值，所以下次更新大概率直接告诉你新地址。`一键检查环境`（doctor）现在也会跑它。

## 怎么做的（证据链）

1. 比 exe：版本号、大小、SHA256、PE 时间戳都不一样 → 确认更新。
2. 找到了上次更新时留下的 2.100 exe 副本（哈希核对过就是 2.100），和 2.101 逐条指令对照：
   - 函数：用"去掉数字后的指令序列"在新 exe 里找唯一位置，再对照到 `ret`，看哪些数字变了。
   - 全局变量：旧代码里每个引用点的前后字节（地址位置挡掉）在新 exe 里找，投票。
   - 结构偏移：成对的函数里同一条指令位置读出新旧数字，再按**对象类名**（exe 里的 RTTI，比如 `CUIQuestion`、
     `CRoleSelectDlg`、`CUIEquipDlg`）逐个类核对，避免上次 2.100 飞鞋那种"数字一样但不是同一个对象"的错。
   - 两个战斗出招函数长得几乎一样，用游戏给 Lua 注册的名字（`CastSkillToFighter` 等）定位。
3. 只读核对：在开着的 5 个窗口（曾经不曾、波大臀圆、自由一/二/三号）上**只用 ReadProcessMemory 读**，
   没有注入、没有发包、没有按键。读到的结果：三个窗口各自的角色号都出现在同一个 5 人队伍名单里，
   等级 70/70/67 对得上，地图 1100，飞鞋记录点三个号一样 (181, 648, 1716)，背包 / 金币 / 装备 / 技能 / 宠物合理；
   答题面板读出了完整题目，已答过的题"选中下标"正好是正确答案。

## 地址表

状态：**已修正** = 2.101 变了、已改并核对；**已核实可用** = 没变、核对过；**未能核实** = 没法在不动窗口的前提下验证。
"静态" = exe 对照；"实读" = 在开着的窗口上只读读出来对得上。

### 全局地址（RVA，相对 exe 基址）

| 名称 | 在哪个文件 | 读的是什么 | 2.100 | 2.101 | 状态 |
|---|---|---|---|---|---|
| UI | world.py `UI_RVA`、login_dll.cpp、答题器 game_addrs.h | 界面根对象（clMainGameRender） | 0x6959E8 | 0x6AAB34 | 已修正（静态+实读） |
| BATTLE | world.py、答题器 | 战斗对象 | 0x6959EC | 0x6AAB38 | 已修正（静态+实读） |
| SESSION | world.py `SESSION_MGR_RVA`、答题器 | 会话（地图/等级/背包…） | 0x6959F0 | 0x6AAB3C | 已修正（静态+实读） |
| CONNECTION | game.py、memory.py、delete.py、network.inc | 连接对象（发包用） | 0x6959F4 | 0x6AAB40 | 已修正（静态+实读：socket 有效、队伍对象 +8 等于它） |
| LOGIN | login_dll.cpp、答题器 `RVA_PLAYER0` | 登录场景 clGameLoginRender（角色名 +0xC84、账号 +0xB7C） | 0x6959E0 | 0x6AAB2C | 已修正（静态+实读：+0xC84 是角色名） |
| SELECTION | login_dll.cpp | 选角场景根 | 0x6959E4 | 0x6AAB30 | 已修正（静态+实读） |
| PLAYER | world.py `PLAYER_PTR_RVA`、答题器 | 自己的玩家对象（+0x34C 角色号） | 0x694DC0 | 0x6A9F00 | 已修正（静态+实读） |
| 忙碌掩码 ×7 | world.py `BUSY_MASK_RVAS` | 判断"忙"的标志位 | 0x57385C… | 0x58091C… | 已修正（静态+实读） |
| 编码表 / 解码表 | network.inc、答题器 | 发包加密表指针 | 0x571EE4 / 0x571F0C | 0x57EFA0 / 0x57EFC8 | 已修正（静态；表内容和 2.100 逐字节相同） |
| 会话上下文 vtable | memory.py `SESSION_VTABLE_RVA` | CUIRoleSelect，建角 / 删角用 | 0x4DCBEC | 0x4E7370 | 已修正（静态+实读：3 个窗口都唯一找到） |

### 函数（DLL 命令 106 调用 / 钩子）

| 名称 | 在哪个文件 | 作用 | 2.100 | 2.101 | 状态 |
|---|---|---|---|---|---|
| MoveTo | game.py | 同图走路 | 0x117E0 | 0x11800 | 已修正（静态，指令一致到 ret） |
| Navigate | game.py | 官方寻路 | 0x18CC80 | 0x18F500 | 已修正（静态） |
| CancelNav | game.py | 取消寻路 | 0x18CB80 | 0x18F400 | 已修正（静态） |
| ClickNpc | game.py | 点 NPC | 0x11180 | 0x111A0 | 已修正（静态 + Lua 注册名） |
| SelectNpcDialogEntry | game.py | 选对话项 | 0x11C70 | 0x11C90 | 已修正（静态 + Lua 注册名） |
| SendFightCmdPacket | game.py | 普攻 / 逃跑 | 0x16D110 | 0x16F4B0 | 已修正（静态） |
| Send（发包） | game.py、network.inc（钩子 + 命令 103/107） | 客户端自己的发包函数 | 0x316AB0 | 0x31B080 | 已修正（静态） |
| TeamAccept | game.py | 接受组队 | 0x220960 | 0x225A10 | 已修正（静态） |
| TeamLeave | game.py | 离队 | 0x2A0DA0 | 0x2A50D0 | 已修正（静态） |
| CastSkillToFighter | game.py | 放技能 | 0x134C0 | 0x134E0 | 已修正（静态 + Lua 注册名） |
| CastPetMagicToFighter | game.py | 宠物放技能 | 0x13580 | 0x135A0 | 已修正（静态 + Lua 注册名） |
| 答题提交 | research/shitu/boss_quiz.py、答题器 | 答题面板提交 | 0x224330 | 0x2293A0 | 已修正（静态） |
| CloseDialog | boss_quiz.py、答题器 | 关面板 | 0x3C7E50 | 0x3D1B50 | 已修正（静态） |
| 辅助页解锁补丁点 ×2 | 答题器 game_addrs.h | 战斗辅助 / 自动采集 | 0x5F570 / 0x5F2BF | 0x61B40 / 0x6188F | 已修正（静态；答题器自带的特征码测试在 2.101 exe 上通过） |

函数调用本身**没有在线上试**（试就要往窗口里注入并调用，会动到正在用的号），见"还没核实的"。

### 结构偏移

| 名称 | 在哪个文件 | 读的是什么 | 2.100 | 2.101 | 状态 |
|---|---|---|---|---|---|
| ui+寻路管理 / +8 寻路对象 | world.py `UI_NAV_MGR` | CUIAreaMap | 0xDA4 / 8 | 0xFD4 / 8 | 已修正（静态+实读，类名对） |
| 寻路对象 就绪 / 进行中 | world.py `NAV_READY` / `NAV_ACTIVE` | | 0x1A8 / 0x1D4 | 0x3D8 / 0x404 | 已修正（静态：取消寻路函数里逐条对上） |
| ui+战斗答题面板 | world.py `UI_QUESTION`、答题器 | CUIQuestion "Question" | 0x10C4 | 0x12F4 | 已修正（静态+实读：读出题目） |
| ui+boss 答题面板 | world.py `UI_QUESTION_MAP`、boss_quiz.py、答题器 | CUIQuestion "QuestionOnMap" | 0x10C8 | 0x12F8 | 已修正（实读：同一个类、同一个父窗口） |
| 答题面板 题号/选中/模式/文本框 | boss_quiz.py、boss_quiz_peek.py、答题器 | | 0x1A4/0x1AC/0x1B4/0x1CC | 0x3D4/0x3DC/0x3E4/0x3FC | 已修正（静态+实读：题号、已答下标都对） |
| 答题面板 可见 / 父窗口 | 同上 | | 0x1C / 0x104 | 不变 | 已核实可用（静态+实读） |
| ui+NPC 对话框 | world.py `UI_DIALOG` | CUINpcDialogWnd | 0xE90 | 0x10C0 | 已修正（静态+实读，类名对） |
| 对话框控件列表 / 控件名 / 文本 | world.py | +0xEC/+0xF0、+0x3C、文本控件 +0x108 | — | 不变 | 已核实可用（静态+实读：读到文本控件和 159 字的文本；当时没有打开的 NPC 对话） |
| ui+飞鞋面板 | world.py `UI_SHOE_PANEL` | CUIEquipDlg | 0xD84 | 0xFB4 | 已修正（静态+实读） |
| 飞鞋记录点 地图 / 坐标 | world.py `SHOE_MAP` / `SHOE_XY` | | 0x438 / 0x43C | 0x678 / 0x67C | 已修正（静态+实读：(181, 648, 1716)） |
| ui+队伍对象 | world.py `UI_TEAM` | CPlayerTeamMgr | 0xDA0 | 0xFD0 | 已修正（静态+实读：5 人名单） |
| 队伍 名单 / 最后邀请人 | world.py | +0xC / +0xA8 | — | 不变 | 已核实可用（实读：邀请人 = 队长的角色号） |
| ui+0x848 连接 | （记忆里的事实） | | 0x848 | 不变 | 已核实可用（实读） |
| 战斗站位数组 | world.py `BATTLE_FIGHTERS`、答题器 | 20 个 × 0x510 | 0x1DC0 | 0x1DC8 | 已修正（静态：所有 0x510 步长的地方都 +8） |
| 战斗 自己位置 / 阵营 / 宠物位置 | world.py | | 0x917C/0x9178/0x9180 | 0x9184/0x9180/0x9188 | 已修正（静态+实读：17/12、16/11 合理） |
| 站位内 SP / 死亡 / 类型 | world.py | +0xF4 / +0xCC / +0 | — | 不变 | 已核实可用（静态：站位内部布局一致；实读 SP 0/1） |
| 会话 地图/等级/天赋/经验/邀请字节 | world.py、expwatch | 0x688 / 0xF00 / 0xEFC / 0xEF0 / 0x135C | — | 不变 | 已核实可用（静态+实读） |
| 场景行 索引/首/尾/行长/实体/标志 | world.py | 0x24928 / 0xE34 / 0xE38 / 0x2A8 / +8 / +0x148 | — | 不变 | 已核实可用（静态+实读） |
| 实体运动坐标 | world.py `ENTITY_MOTION` | +0x18C | — | 不变 | 已核实可用（实读：和整数坐标一致） |
| 玩家角色号 | world.py `PLAYER_CHAR_ID` | +0x34C | — | 不变 | 已核实可用（实读） |
| 背包 / 金币 / 装备 | world.py | +0x16B0 表，+0x88 / +0x8818 / +0x8800 / +0x8828 | — | 不变 | 已核实可用（静态+实读） |
| 技能 / 宠物 / 任务树 | world.py | P+0x1B8A8 / 0x1B98C / 0x1B9A0 / 0x1B94C / 0x1B95C | — | 不变 | 已核实可用（静态+实读） |
| 自身 buff 树 | research/jingu/buff.py | session+0x1D264 | — | 不变 | 已核实可用（静态） |
| 建角/删角 会话上下文字段 | protocol.py | +0x1C/+0x20/+0x74/+0x90/+0x150 | — | 不变 | 已核实可用（静态：组包函数指令一致；实读：上下文唯一找到） |
| 登录 账号输入框 | login_dll.cpp | [登录+0x40]+? → 文本 +0x11C | +0x180 | **+0x3B0** | 已修正（静态+实读：+0x3B0 是 TWndEditCtrl） |
| 选角 选中下标 | login_dll.cpp | [[选角+0x118]+0x31C]+? | +0x1A8 | **+0x3D8** | 已修正（静态：CRoleSelectDlg 的方法里逐条对上）；**没实读**（要在选角画面才有） |
| 自动巡逻面板 | 只在记忆笔记里 | ui+0xD28，字段 +0x444… | 0xD28 | 0xF58（字段不变） | 已修正（静态）；仓库代码没用到 |

### 包号 / 协议

建角 0x0002、删角 0x0003、邀请 0x0030、卖 0x0055、装备 0x0047、邮件 tap 0x4411、DLL 命令 106 等：
**包号和包体格式没变**（组包函数和 2.100 指令一致，只有界面字段挪了）。DLL 命令号是我们自己定的，和游戏版本无关。

## 改了哪些文件

- `batch_provision/provisioner/world.py`、`game.py`、`memory.py`、`factory/delete.py`：常量改成 2.101，注释里留着 2.100 的值。
- `batch_provision/native/login_dll.cpp`、`network.inc`：全局地址、发包函数、编码表、登录框 +0x3B0、选角下标 +0x3D8。
- `batch_provision/native/launcher.cpp`：只接受 2.101 的哈希（旧版本会被拒绝，避免拿错地址跑）。
- **重新编译了** `batch_provision/bin/launcher.exe`、`bin/provision_native.dll`；旧的备份成
  `bin/launcher_2.100_backup.exe`、`bin/provision_native_2.100_final_backup.dll`。
- `batch_provision/research/shitu/boss_quiz.py`、`boss_quiz_peek.py`、`monitor.py`、`shoe_dagewang.py`：答题面板 / 飞鞋偏移。
- `batch_provision/provisioner/doctor.py`：一键检查环境会跑特征码扫描。
- 新增 `batch_provision/provisioner/addrscan.py` + `tests/test_addrscan.py`；`tests/test_doctor_hash.py` 改成只认 2.101。
- 答题器源码 `大冒险2_自动答题器_原生无感关窗版/src/`：`dll/game_addrs.h`（集中所有地址）、`dll/quizbot_hook.cpp` 和
  `controller/main.cpp`（原来写死的 0x10C4 / 0x1AC / 0x1DC0 改成用 game_addrs.h 的常量）、`native_unlock.h`、
  `tools/native_unlock_test.cpp`（只改提示文字）。已经编译到 `src/build/`，自带离线测试全过；2026-10-29 已替换包里的
  `启动答题器.exe` 和 `quizbot_hook.dll`（旧版备份在 `backup_2.100_20261029/`）。

## 还没核实的

1. **函数调用没有在线上实测**（走路、寻路、点 NPC、选对话、出招、放技能、组队、发包、答题提交）。证据是静态的：
   每个函数和 2.100 指令一条条对得上，只有地址变。要实测得开一个测试号窗口（launcher + DLL 注入），
   按 testrun 流程跑一遍；我没有动你开着的 5 个窗口。
2. **登录 / 选角 / 进游戏没实跑**：选角下标 +0x3D8 只有静态证据（选角画面才有那个对象）。
3. **答题器新版已部署但没在线上跑过**：包里的 `启动答题器.exe` / `quizbot_hook.dll` 已换成 2.101 版，
   第一次用管理员权限启动后，先看一道题能不能自动答对。`backup_2.100_*` 里的旧版在 2.101 上**不要用**。
4. 答题器里一个从没发布、默认关闭的"本场最低血量"功能还用着 2.98 时代的三个地址（0x5166DC、0x10070、0x100D0），
   没核实，也没改（不影响现在的功能）。答题器 battle_profit.csv 里的等级（+0xEAC）和地图（+0x2E4）从 2.98 起就不对，没改。
5. 实读时 波大臀圆 的窗口正开着一道战斗答题（大熊猫那题），等人回答。

## 下次更新怎么办

```
cd batch_provision
python -X utf8 -m provisioner.addrscan
```

它会列出每个地址"代码里的值 / 扫描到的值 / 一致还是不对 / 没找到"，以及 C++ 源码、答题器、研究脚本里哪些副本要改。
改完后：在 launcher.cpp 换新哈希、跑 `native\build.ps1` 和答题器 `src\build.ps1`、跑单元测试，再在一个测试窗口上只读核对。
**更新前先把旧 exe 复制一份留着**，这次就是靠上次留下的 2.100 副本才能逐条对照。
