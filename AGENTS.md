# 给接手的 AI（Claude、Codex、Gemini …）

更新：2026-11-05。先读这一页，再读 `docs/ARCHITECTURE.md`（仓库里有哪几条产品线、哪些能力是共用的）。

## 1. 这是什么

《什么什么大冒险2》（客户端 2.101，Windows）的自动化：料理生产、师徒带新号到 41 级出师（勇者 / 元素使）、满爆方士带到 70 级、
抓一级宝宝。代码只在 Windows 上连游戏；在 Linux / 云端只能跑单元测试（见第 4 节）。

## 2. 开工前

1. 看 `docs/ARCHITECTURE.md` 第 3 节「共用能力目录」：要做的事多半已经有现成函数。**不要再写一份。**
2. 改共用模块前查谁在用：`grep -rn <模块名> batch_provision 抓宠一级宝宝`。满爆方士项目
   （`batch_provision/projects/fullcrit_mage_leveling_70/`）复用了 `research/shitu/` 的大部分模块。
3. 某条产品线特有的行为用开关（环境变量 / 配置），默认保持旧行为。现有开关：`SHITU_TRASH`（师徒线丢葫芦、卖武器）、
   `SHITU_JOB`（战士 = 勇者线，术士 = 元素使线）、`SHITU_TIDY`（元素使不穿武器 / 新手装）。

## 3. 硬规矩

- **别动大号（师傅 / 队长）的东西**：卖、丢、脱装备只对小号（徒弟）。`sell_tradable` 按 `MASTERS` 名单跳过师傅；新代码也要这样。
- **用户正在跑产线**：改动要能单独上线；`line/route.py` 按文件名调用脚本，改名、搬文件会让正在跑的队出错。
- 勇者线路线有「指纹」测试（`tests/test_job_route.py` 的 `BRAVE_FINGERPRINTS`）：**有意**改勇者路线时要同步更新指纹，并在注释里写原因；
  改元素使线不应该改到它。
- 每一步从逍遥村重来都要能走通（`tests/test_restart_from_home.py`）：新步骤开头要先回城、坐 PP鸡，或用自己会从村里出发的脚本。
- 拿任务物品 / 奖励的步骤前面要腾背包（`U space N`）；后段任务步以 `U need QID N` 结尾（`tests/test_line.py` 会查）。
- 代码注释写英文，带日期和来源（「user 2026-11-05: …」「2026-10-28 live: …」）；给用户看的文档、日志用中文。
- 不要把账号、密码写进仓库（`local.toml`、师傅账号文件都在用户本机）。
- **游戏更新后**按 `docs/GAME_UPDATE.md` 做：`addrscan` 找地址、`addrscan --save` 存地址档案、表 B 的封包实测。游戏 exe 不能放进仓库（仓库是公开的）。新加一个自己拼包体的动作，要登记进那一页的表 B。
- 新的产品线入口启动时调用 `provisioner.quizbot.ensure()`（答题器没开就启动；一台电脑一个，不要自己再启动第二个）。

## 4. 测试（Linux / 云端）

游戏接口在 Windows 上用 `ctypes.WinDLL`；在 Linux 上先换成假的再跑：

```bash
cd batch_provision
python3 -c "
import ctypes, unittest.mock as m, sys, unittest
ctypes.WinDLL = m.MagicMock(); ctypes.windll = m.MagicMock(); ctypes.WINFUNCTYPE = m.MagicMock()
r = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_line'))
sys.exit(not r.wasSuccessful())"
```

- **一个文件一个文件跑**，每个加超时（`timeout 60`）。`tests.test_r4_util_windows` 在假接口下会死循环，跳过。
- 在 Linux 上本来就过不了的（Windows 进程检查）：`test_factory_relogin`、`test_factory_supervisor`、`test_state_lock`。
- Windows 上直接：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`（在 `batch_provision/` 下）。

## 5. 改完以后

- 跑相关测试；改了路线就跑 `test_line`、`test_job_route`、`test_restart_from_home`。
- **更新文档**：共用能力有变化 → `docs/ARCHITECTURE.md` 第 3 节；师徒线行为有变化 → `docs/SHITU_LINE.md`；师傅要准备的东西有变化 →
  `docs/SHITU_MASTER_GUIDE.md`；脚本增删 → `batch_provision/research/shitu/README.md`。
- 告诉用户：改了什么、为什么、怎么验证（「下一批看日志里有没有 …」），以及**要拉最新 main、重启产线总控才生效**。

## 6. 文档在哪

见 `docs/ARCHITECTURE.md` 第 7 节「文档地图」。
