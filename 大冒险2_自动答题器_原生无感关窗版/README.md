# 大冒险2 自动答题器

本目录包含 Windows 可执行程序、DLL、题库，以及用于研究和重新编译的源码。当前源码适配客户端 **2.101**；客户端更新后需要重新核对地址及行为。

- [源码、实现链路与编译说明](src/README.md)：答题、界面解锁、已验证与待验证事项。
- `src/controller/main.cpp`：发现游戏进程、注入与多进程会话、处理题目和启动界面解锁。
- `src/controller/native_unlock.h`：战斗辅助、自动采集、自动任务三个界面判断的进程内补丁；`src/dll/game_addrs.h` 集中记录当前版本 RVA。
- `src/dll/quizbot_hook.cpp` 和 `src/dll/quiz_protocol.h`：注入模块、游戏事件和协议处理。
- `src/tools/`：题库生成和离线验证工具；`data/` 为题库数据。

双击 `启动答题器.exe` 启动现成程序；它还依赖本目录的 `quizbot_hook.dll`、`injector.exe` 和 `data/`。使用 `--no-unlock` 启动可禁用三个辅助界面补丁。自动任务解锁只表示界面控件可用，不会自动勾选、启动或完成任务；任务执行和服务器结果应另行核验。

从源码编译请按 [源码说明](src/README.md) 运行 `src/build.ps1`。脚本将产物放在 `src/build/`，不会覆盖正在运行的版本。`使用说明.txt` 是早期版本的说明，题库和功能以本文件及源码说明为准。
