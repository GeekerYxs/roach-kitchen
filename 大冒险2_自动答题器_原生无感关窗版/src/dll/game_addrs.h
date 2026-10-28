// game_addrs.h — 游戏客户端 WAATClient.exe 的地址（RVA，相对模块基址），DLL 和控制器共用。
// 当前版本：2.100。2.98 的旧值写在注释里，换版本时只改这一个文件。
// 2.100 的值来自仓库提交 8c94697（把 2.98 编译产物里的这些数字逐个改成 2.100，已在线上跑过）。
#pragma once
#include <cstdint>

namespace ga {

constexpr uint32_t RVA_UI           = 0x6959E8;  // [base+RVA] -> UI 根对象            (2.98: 0x6390EC)
constexpr uint32_t RVA_PLAYER0      = 0x6959E0;  // 角色名 +0xC84 / 账号 +0xB7C          (2.98: 0x6390E4)
constexpr uint32_t RVA_BATTLE       = 0x6959EC;  // 战斗对象                              (2.98: 0x6390F0)
constexpr uint32_t RVA_SESSION      = 0x6959F0;  // 等级 +0xEAC                           (2.98: 0x6390F4)
constexpr uint32_t RVA_PLAYER_PTR   = 0x694DC0;  // 地图号链                              (2.98: 0x638578)
constexpr uint32_t RVA_CODEC_ENC    = 0x571EE4;  // 编码表指针数组                        (2.98: 0x515D6C)
constexpr uint32_t RVA_CODEC_DEC    = 0x571F0C;  // 解码表指针数组                        (2.98: 0x515D94)
constexpr uint32_t RVA_QUIZ_SUBMIT  = 0x224330;  // thiscall(panel)：按 +0x1AC 发答案     (2.98: 0x220950)
constexpr uint32_t RVA_CLOSE_DIALOG = 0x3C7E50;  // thiscall(parent, panel, 0)：关窗        (2.98: 0x391860)

// 两个答题面板（同一个界面类），见 batch_provision/research/shitu/BOSS_QUIZ.md
constexpr uint32_t UI_QUIZ_BATTLE = 0x10C4;  // "Question"：战斗里的题 0x46F4 / 0x1F04
constexpr uint32_t UI_QUIZ_MAP    = 0x10C8;  // "QuestionOnMap"：boss 开打时的题 0x46F5 / 0x1F05
constexpr uint32_t QUIZ_VISIBLE   = 0x1C;    // 1 = 面板开着
constexpr uint32_t QUIZ_PARENT    = 0x104;   // CloseDialog 的 parent
constexpr uint32_t QUIZ_QNO       = 0x1A4;   // 题号
constexpr uint32_t QUIZ_CHOSEN    = 0x1AC;   // 选中的下标（0 开始）
constexpr uint32_t QUIZ_MAP_MODE  = 0x1B4;   // 1 = 发答案时走 0x1F05

}  // namespace ga
