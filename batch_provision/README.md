# 批量登录 + 建角

**本机配置**：游戏路径、本机小号号段、全部密码只写在 `local.toml`（不上传 GitHub，模板 `local.example.toml`），
它会覆盖各个 `*.toml` 里的同名设置。新电脑部署见 `../docs/DEPLOY.md`，先双击 `一键检查环境.cmd`。

改 `config.toml` → 双击 `一键建角.cmd`。每个账号：原生登录到选角界面 → 挂网络观察 → 用游戏自己的发送函数发 0x0002 建角包（mw01r1..mw01r4）→ 等 0x4003 回包 → 正常退出并重登，刷新选角列表、核验角色名 → 停在选角界面。全程不模拟键鼠。

## 进游戏（另一个工具）

改 `enter.toml` → 双击 `一键进游戏.cmd`。每个账号：登录到选角界面 → 读选角列表，确认目标槽有角色 → DLL 命令 105 选槽并回车直到世界指针出现 → 读自己角色对象的 ID（`[base+0x638578]+0x34C`）必须等于选中角色的 ID，同时记录地图（`[[base+0x6390F4]]+0x688`）和坐标。窗口全部保留，账号数不能超过 `max_windows`。日志 `logs/enter_*.log`，汇总 `logs/enter_summary_*.json`。

## 新手出村（环节 3）

先 `一键进游戏.cmd`，再双击 `一键新手出村.cmd`。不需要密码：接管所有带本工具 DLL、已在游戏世界里的窗口；只处理在菜鸟训练营(271)的角色，已在逍遥村(1)的直接算完成。每个窗口一个循环：读状态 → `novice.decide()` 决定下一步 → 最多做一个动作。中途中断，重新运行会按当前状态接着走。

- 寻路：官方寻路到 (2694,477)，距新手传送师(NPC32, (2656,528)) ≤80 就停下点 NPC，对话框里选「逍遥村」。
- 战斗：像官方自动战斗一样，每次自己的蓄力点(战斗单位+0xF4)变化就发一次逃跑（SendFightCmdPacket 动作 8）。SP0 时发的那次无效，0→1 那次生效。
- 单元测试：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`（22 个，不需要游戏）。

DLL 命令 106 = 在游戏窗口线程调用任意游戏函数（RVA + 寄存器 + 栈参数），游戏知识全部在 Python（`game.py` 动作、`world.py` 读状态）。以后加新动作不用再改 DLL、不用重开游戏。

## 目录

| 路径 | 作用 |
|---|---|
| `config.toml` | 账号、密码、几开、每号角色数等全部参数 |
| `provisioner/config.py` | 读配置、校验 |
| `provisioner/native.py` | launcher.exe / DLL 命令 / 关闭进程；所有退出码和 DLL 错误码的中文含义 |
| `provisioner/memory.py` | 只读内存：定位会话上下文、扫描角色名 |
| `provisioner/protocol.py` | 组建角包、解码服务器回包 |
| `provisioner/login.py` | 两个工具共用：启动节流（间隔 + 内存）、登录重试、读选角列表 |
| `provisioner/worker.py` | 建角：单账号流程（每步日志） |
| `provisioner/enter.py` + `enter.toml` | 进游戏：单账号流程 + 并发入口 |
| `provisioner/world.py` | 游戏内只读：角色 ID、坐标、地图 |
| `provisioner/state.py` | `state/<账号>.json` 记录已建角色和 ID（不含密码） |
| `factory/phase.py` | 料理工位化生产：由小号当前状态推出它所处的阶段（纯函数，设计见 `../docs/FACTORY_DESIGN.md`） |
| `factory/meat.py` + `一键吃小肉林.cmd` | 工序 1：到村吃小肉林（背包数量 1→0 核验） |
| `factory/shoe.py` + `一键记录飞鞋.cmd` | 工序 2：站稳后记录飞鞋（客户端记录点 = 当前位置核验） |
| `factory/gold.py` + `一键发金币.cmd` | 工序 3：调度员给村里金币不足 190 的小号 500 金币，逐笔串行，只看小号余额够不够（不对账） |
| `stations.toml` + `一键登录工位.cmd`（`factory/stations.py`） | 常驻工位角色（调度员/古井/海岸/收货人）的账号、密码、槽位；登录后登记到 factory.db。同一角色已开在非本工具窗口时拒绝登录（防挤号） |
| `factory/runner.py`、`factory/config.py`、`factory.toml` | 工序共用：找窗口、并发、汇总；配置 |
| `factory/db.py` | `factory.db`（SQLite）：小号、工位、事件；排队、认领租约、失败 3 次隔离 |
| `provisioner/__main__.py` | 并发调度、汇总 |
| `native/` | launcher.cpp / login_dll.cpp 源码，`build.ps1` 编译到 `bin/` |
| `logs/run_*.log` | 完整日志（DEBUG 级，含每个收包）；`summary_*.json` 每号结果 |
| `runtime/` | 每进程的启动结果、tap 抓包（排查用） |

## 安全规则

- 登录后先读服务器下发的选角列表（会话上下文 +0x90 的 vector，每项 0x6C 字节：+0 角色ID，+4 等级，+0x14 名字），日志逐槽列出。已存在的跳过；空槽不够时（账号里有其他程序建的角色）多出来的不建，记为 `no_slot` 并列出占槽角色。
- 建角回包 0x4003 的 result：0 成功，2 角色槽已满。
- 等回包超时 = 结果不确定，该账号停止后续建角；下次运行先扫列表再决定。
- 登录失败（建角之前）会杀进程重试 `login_retries` 次；建角阶段的失败不会自动重试。

## 来源

由 `D:\Codes\OpenAiCodex\game_smsm2\mxbl_login_native\provision` 重构。改动：DLL 每进程允许 4 次建角（原来 1 次）；launcher 增加 `--result`（每进程独立结果文件，可并发）、`--inject-delay`，失败时也写结果；去掉截图比对空槽。
