# testrun：游戏更新后的最小全流程测试

用测试小号 mvp01..mvp06（专门用来测代码更新）跑一遍每道工序，数据库是独立的 `state/test_factory.db`，不碰本机的 factory.db。

准备：在本目录建 `local.toml`（含密码，已被 .gitignore 排除），内容：`[game] exe`、`[accounts]`（prefix = "mvp"，start/count 选一个空号）、`[passwords]`（四个工位账号）。工位列表在 `stations.toml`。生产机必须先停（工位号两边同时登会互相挤）。

在 batch_provision 目录按顺序运行，每道通过再跑下一道：

```
python -X utf8 -m provisioner testrun/config.toml              # 建角（每号 2 个）
python -X utf8 -m provisioner.enter testrun/enter.toml         # 进第 1 个角色（先关掉建角留下的窗口）
python -X utf8 -m provisioner.novice testrun/novice.toml       # 新手出村（对话）
python -X utf8 -m factory.stations testrun/stations.toml       # 登录 4 个工位
python -X utf8 -m factory.meat testrun/factory.toml
python -X utf8 -m factory.shoe testrun/factory.toml
python -X utf8 -m factory.gold testrun/factory.toml
python -X utf8 -m factory.wellteam testrun/factory.toml
python -X utf8 -m factory.welltrain testrun/factory.toml       # 约 6 分钟
python -X utf8 -m factory.transport testrun/factory.toml       # PP 鸡对话
python -X utf8 -m factory.quest testrun/factory.toml           # 海子对话
python -X utf8 -m factory.coast testrun/factory.toml           # 约 12 分钟
python -X utf8 -m factory.handin testrun/factory.toml
python -X utf8 -m factory.receiver testrun/factory.toml
python -X utf8 -m factory.wipe testrun/wipe.toml 1 1 --yes     # 用完必须删除（号段 1..1 = mvp01）
```

wipe 在最后一次工位心跳 120 秒内会拒绝（以为总大脑在跑），等 2 分钟再删。

2026-10-15（客户端 2.98）全部通过：建角 25 s，新手 0.3 s，带练 2→11 级 365 s，传送 13.5 s，接任务 7.3 s，刷怪 748 s，交任务 1.3 s，收料理 3.4 s。

2026-10-15 收货人加了收金币（mvp02）：料理 7→8 用 2.8 s，接着金币 1753 全部收回（收货人 81859→83612，分毫不差）用 2.8 s；重跑不再发交易。
