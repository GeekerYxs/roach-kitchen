# roach-kitchen

《什么什么大冒险2》（客户端 2.101，Windows）自动化。几条产品线共用一套游戏能力，结构见 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**。
接手的 AI 先读 **[AGENTS.md](AGENTS.md)**。

## 产品线

| 做什么 | 怎么启动 | 说明 |
|---|---|---|
| **小强料理**：工位化生产「美味小强料理」（调度员、古井队长、海岸队长、收货人 + 小号流水） | `batch_provision/一键总大脑.cmd` | [FACTORY_DESIGN.md](docs/FACTORY_DESIGN.md)、[batch_provision/README.md](batch_provision/README.md) |
| **师徒 → 勇者**：师傅每批带 4 个新号，1 级 → 41 级出师，每号约 48 万金币 | `cd batch_provision/research/shitu && python -X utf8 -m line` | [SHITU_LINE.md](docs/SHITU_LINE.md)、[师傅要准备什么](docs/SHITU_MASTER_GUIDE.md) |
| **师徒 → 元素使**：同一条产线，`line.toml` 里写 `job = "术士"` 的队 | 同上 | `batch_provision/research/shitu/YUANSU_NOTES.md` |
| **满爆方士带到 70 级**：无任务练级 | `batch_provision/projects/fullcrit_mage_leveling_70/run_level_to_70.py` | [该项目 README](batch_provision/projects/fullcrit_mage_leveling_70/README.md) |
| **抓一级宝宝** | `抓宠一级宝宝/runner.py` | [抓宠一级宝宝](抓宠一级宝宝/README.md) |

## 工具

- 部署到新电脑（准备哪些大号、16 核 32 GB 怎么配、启动顺序）：[DEPLOY.md](docs/DEPLOY.md)
- 游戏更新以后（每周）：按 [GAME_UPDATE.md](docs/GAME_UPDATE.md) 改地址、查封包；每个版本的地址档案在 `batch_provision/provisioner/addr_versions/`
- 答题器（战斗题 + boss 题，自动注入每个新开的游戏窗口，顺带解锁游戏自带辅助工具）：[功能、源码与编译](大冒险2_自动答题器_原生无感关窗版/src/README.md)
- Boss 开打题：题号 2601～3000 共 400 题全齐，答案已并入答题器；规律和协议见 `batch_provision/research/shitu/BOSS_QUIZ.md`，
  采集记录 [BOSS_QUESTION_COLLECTION_20261030.md](docs/BOSS_QUESTION_COLLECTION_20261030.md)
- 战斗记录（每场一行：怪物、经验 / 潜能、掉落、阵亡逃跑、双倍；报表）：[BATTLELOG.md](docs/BATTLELOG.md)

所有文档的索引：[docs/ARCHITECTURE.md 第 7 节](docs/ARCHITECTURE.md#7-文档地图)。
