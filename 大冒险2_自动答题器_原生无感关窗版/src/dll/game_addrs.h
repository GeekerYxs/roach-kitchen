// game_addrs.h — 游戏客户端 WAATClient.exe 的地址（RVA，相对模块基址），DLL 和控制器共用。
// 当前版本：2.101（2026-10-29）。旧值写在注释里，换版本时只改这一个文件。
// 2.101 的值：拿 2.100 和 2.101 的 exe 逐条指令对照找到，并在 5 个开着的 2.101 窗口上只读核对过；
// batch_provision/provisioner/addrscan.py 能用特征码在新 exe 里重新找出这些地址（python -m provisioner.addrscan）。
// 2.101 的界面窗口类从 +0x174 起整体变大 0x230，所以 UI 根对象上的面板指针和面板里的字段都挪了。
#pragma once
#include <cstdint>

namespace ga {

constexpr uint32_t RVA_UI           = 0x6AAB34;  // [base+RVA] -> UI 根对象            (2.100: 0x6959E8, 2.98: 0x6390EC)
constexpr uint32_t RVA_PLAYER0      = 0x6AAB2C;  // 角色名 +0xC84 / 账号 +0xB7C          (2.100: 0x6959E0, 2.98: 0x6390E4)
constexpr uint32_t RVA_BATTLE       = 0x6AAB38;  // 战斗对象                              (2.100: 0x6959EC, 2.98: 0x6390F0)
constexpr uint32_t RVA_SESSION      = 0x6AAB3C;  // 等级 +0xEAC                           (2.100: 0x6959F0, 2.98: 0x6390F4)
constexpr uint32_t RVA_PLAYER_PTR   = 0x6A9F00;  // 地图号链                              (2.100: 0x694DC0, 2.98: 0x638578)
constexpr uint32_t RVA_CODEC_ENC    = 0x57EFA0;  // 编码表指针数组（表内容和 2.100 一样）  (2.100: 0x571EE4, 2.98: 0x515D6C)
constexpr uint32_t RVA_CODEC_DEC    = 0x57EFC8;  // 解码表指针数组                        (2.100: 0x571F0C, 2.98: 0x515D94)
constexpr uint32_t RVA_QUIZ_SUBMIT  = 0x2293A0;  // thiscall(panel)：按 QUIZ_CHOSEN 发答案 (2.100: 0x224330, 2.98: 0x220950)
constexpr uint32_t RVA_CLOSE_DIALOG = 0x3D1B50;  // thiscall(parent, panel, 0)：关窗        (2.100: 0x3C7E50, 2.98: 0x391860)
// 辅助工具界面解锁补丁的位置（controller/native_unlock.h；2026-10-29 用特征码在 2.101 exe 里核对，各只出现一次；
// 地址不对时 native_unlock 会自己按特征码找）
constexpr uint32_t RVA_UNLOCK_FIGHT  = 0x61B40;  // 战斗辅助页「（待激活）」判断           (2.100: 0x5F570, 2.97: 0x5EA20)
constexpr uint32_t RVA_UNLOCK_GATHER = 0x6188F;  // 自动采集页「（待激活）」判断           (2.100: 0x5F2BF, 2.97: 0x5E76F)

// 两个答题面板（同一个界面类），见 batch_provision/research/shitu/BOSS_QUIZ.md
constexpr uint32_t UI_QUIZ_BATTLE = 0x12F4;  // "Question"：战斗里的题 0x46F4 / 0x1F04       (2.100: 0x10C4)
constexpr uint32_t UI_QUIZ_MAP    = 0x12F8;  // "QuestionOnMap"：boss 开打时的题 0x46F5 / 0x1F05 (2.100: 0x10C8)
constexpr uint32_t QUIZ_VISIBLE   = 0x1C;    // 1 = 面板开着
constexpr uint32_t QUIZ_PARENT    = 0x104;   // CloseDialog 的 parent
constexpr uint32_t QUIZ_QNO       = 0x3D4;   // 题号                  (2.100: 0x1A4)
constexpr uint32_t QUIZ_CHOSEN    = 0x3DC;   // 选中的下标（0 开始）  (2.100: 0x1AC)
constexpr uint32_t QUIZ_MAP_MODE  = 0x3E4;   // 1 = 发答案时走 0x1F05 (2.100: 0x1B4)

// 战斗对象里的 20 个站位，每个 0x510 字节，+0 = 类型（0 / 0xFFFFFFFF = 空）
constexpr uint32_t BATTLE_FIGHTERS = 0x1DC8;  // (2.100: 0x1DC0)
constexpr uint32_t FIGHTER_SIZE    = 0x510;

}  // namespace ga
