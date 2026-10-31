# roach-kitchen

什么什么大冒险2「美味小强料理」自动生产线（工位化：调度员、古井队长、海岸队长、收货人 + 小号流水）。

- 代码与一键工具：`batch_provision/`（说明见 `batch_provision/README.md`）
- 部署到新电脑（照着做即可：准备哪些大号、16 核 32 GB 怎么配、启动顺序）：`docs/DEPLOY.md`
- 设计：`docs/FACTORY_DESIGN.md`
- 师徒产线（1 级新号 → 41 级出师，约 48 万金币/号）：`docs/SHITU_LINE.md`；新架构 v5 一键 `python -X utf8 -m line`（在 `batch_provision/research/shitu/` 下，第 8 节）
- 战斗记录（每场战斗一行：怪物等级和名字、经验 / 潜能 / 宠物经验、掉落、阵亡逃跑、四种双倍、金币背包答题；6.4 万场历史 + 等级差曲线和最快路线报表）：`docs/BATTLELOG.md`；技术细节 `batch_provision/battlelog/README.md`
- 答题器（战斗题 + boss 题，顺带解锁游戏自带辅助工具的战斗辅助、自动采集和自动任务界面）：[功能、源码与编译说明](大冒险2_自动答题器_原生无感关窗版/src/README.md)
- Boss 开打题：题号 2601～3000 共 400 题全齐，答案已并入答题器（正确下标 = (题号−2601)÷100，2026-10-30 两轮实测 31/31、29/29 通过）；规律和协议见 `batch_provision/research/shitu/BOSS_QUIZ.md`，采集记录见 [`docs/BOSS_QUESTION_COLLECTION_20261030.md`](docs/BOSS_QUESTION_COLLECTION_20261030.md)
