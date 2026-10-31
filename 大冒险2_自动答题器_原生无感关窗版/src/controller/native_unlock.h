// controller/native_unlock.h — 解锁游戏自带辅助工具的战斗、采集和自动任务界面（仅进程内补丁）。
//
// 来源：D:\Codes\Gemini_Prj\smsm2_game\战斗辅助原生界面解锁工具（2.97 版，Gemini 写的）。按项目规矩只拿事实：
// 两段特征码和补丁字节。2026-10-28 在 2.100 的 WAATClient.exe 磁盘文件里核对过：两段特征码在 .text 里各只出现一次，
// 战斗 RVA 0x61B40、采集 RVA 0x6188F（2.101；2.100 是 0x5F570 / 0x5F2BF，2.97 是 0x5EA20 / 0x5E76F），写进了 game_addrs.h。
//
// 原理（CUIFuzhu 每帧刷新控件时检查身上有没有辅助卡 0x400，没有就整页 SetEnable(0) 并显示「（待激活）」）：
//   战斗: 75 04 jne / 33 db xor ebx,ebx / eb 03 jmp / 83 c3 18 add ebx,0x18
//         -> bb 01 00 00 00 mov ebx,1 / 90 nop / 83 c3 18      （ebx 恒非 0 = 整页启用）
//   采集: 75 06 jne / 33 c0 / 33 ff xor edi,edi / eb 05 jmp / 8d 79 18 lea edi,[ecx+0x18]
//         -> 33 c0 / 6a 01 5f (edi=1) / eb 06 / 90 / 8d 79 18   （跳转目标和原来一样，edi 恒非 0）
//   任务: 75 04 jne / 33 f6 xor esi,esi / eb 03 jmp / 8d 71 18 lea esi,[ecx+0x18]
//         -> be 01 00 00 00 / 90 90 90 90  （esi=1，跳过原来的 lea）
// 只改客户端界面的启用判断；保存设置时发给服务器的还是游戏自己的包。
//
// 定位顺序：game_addrs.h 里的 RVA -> 整个模块扫描特征码（游戏小更新挪了地址也能找到）。已经是补丁后的字节 = 已解锁。
// 纯函数 find_patch / patch_state 不碰进程，离线测试在 tools/native_unlock_test.cpp。
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace nu {

struct PatchSpec {
    const char* name;                    // 日志里的名字
    uint32_t rva;                        // 当前版本的地址（0 = 只扫描）
    std::vector<uint8_t> orig;           // 原版特征码
    std::vector<uint8_t> patched;        // 打完补丁后同一位置的字节（同长度）
    size_t write_len;                    // 实际要写的前几个字节
};

inline std::vector<PatchSpec> default_specs(uint32_t fight_rva, uint32_t gather_rva, uint32_t task_rva) {
    return {
        {"战斗辅助", fight_rva, {0x75, 0x04, 0x33, 0xDB, 0xEB, 0x03, 0x83, 0xC3, 0x18},
                                {0xBB, 0x01, 0x00, 0x00, 0x00, 0x90, 0x83, 0xC3, 0x18}, 6},
        {"自动采集", gather_rva, {0x75, 0x06, 0x33, 0xC0, 0x33, 0xFF, 0xEB, 0x05, 0x8D, 0x79, 0x18},
                                 {0x33, 0xC0, 0x6A, 0x01, 0x5F, 0xEB, 0x06, 0x90, 0x8D, 0x79, 0x18}, 8},
        {"自动任务", task_rva, {0x75, 0x04, 0x33, 0xF6, 0xEB, 0x03, 0x8D, 0x71, 0x18, 0x83, 0xBB, 0xC8, 0x03, 0x00, 0x00, 0x00},
                               {0xBE, 0x01, 0x00, 0x00, 0x00, 0x90, 0x90, 0x90, 0x90, 0x83, 0xBB, 0xC8, 0x03, 0x00, 0x00, 0x00}, 9},
    };
}

enum class State { Original, Patched, Unknown };

inline State patch_state(const uint8_t* p, size_t n, const PatchSpec& s) {
    if (n < s.orig.size()) return State::Unknown;
    if (memcmp(p, s.orig.data(), s.orig.size()) == 0) return State::Original;
    if (memcmp(p, s.patched.data(), s.patched.size()) == 0) return State::Patched;
    return State::Unknown;
}

// 在 buf 里找第一个原版或补丁后的特征码。-> 偏移（找不到 = -1），state 写出是哪一种。
// 两种都只认唯一出现：出现两次以上不打（不知道哪个是真的），返回 -2。
inline long long find_patch(const uint8_t* buf, size_t n, const PatchSpec& s, State& state) {
    long long hit = -1;
    State hit_state = State::Unknown;
    for (size_t i = 0; i + s.orig.size() <= n; i++) {
        State st = patch_state(buf + i, n - i, s);
        if (st == State::Unknown) continue;
        if (hit >= 0) { state = State::Unknown; return -2; }
        hit = (long long)i;
        hit_state = st;
    }
    state = hit_state;
    return hit;
}

#ifdef _WIN32
#include <windows.h>
#include <cstdio>
// 给一个游戏进程打三个补丁。-> 一行日志，例如「战斗辅助: 已解锁(+0x5F570) | 自动采集: 已解锁(+0x5F2BF)」；all_ok = 三个都处于解锁状态。
inline std::string unlock_process(HANDLE h, uintptr_t base, uint32_t mod_size, const std::vector<PatchSpec>& specs,
                                  bool& all_ok) {
    all_ok = true;
    std::string out;
    std::vector<uint8_t> image;          // 整个模块，只在 RVA 没对上时才读
    for (const PatchSpec& s : specs) {
        if (!out.empty()) out += " | ";
        out += s.name;
        uintptr_t addr = 0;
        State st = State::Unknown;
        if (s.rva) {
            std::vector<uint8_t> b(s.orig.size());
            SIZE_T got = 0;
            if (ReadProcessMemory(h, (LPCVOID)(base + s.rva), b.data(), b.size(), &got) && got == b.size()) {
                st = patch_state(b.data(), b.size(), s);
                if (st != State::Unknown) addr = base + s.rva;
            }
        }
        if (!addr) {
            if (image.empty() && mod_size) {
                image.assign(mod_size, 0);
                for (uint32_t off = 0; off < mod_size; off += 0x1000) {   // 逐页读，读不了的页留 0
                    SIZE_T got = 0;
                    ReadProcessMemory(h, (LPCVOID)(base + off), image.data() + off, (std::min)(0x1000u, mod_size - off), &got);
                }
            }
            long long off = image.empty() ? -1 : find_patch(image.data(), image.size(), s, st);
            if (off == -2) { out += ": 特征码出现多次，没打"; all_ok = false; continue; }
            if (off < 0) { out += ": 没找到特征码（游戏版本变了？）"; all_ok = false; continue; }
            addr = base + (uintptr_t)off;
        }
        char rva[32];
        snprintf(rva, sizeof rva, "(+0x%X)", (unsigned)(addr - base));
        if (st == State::Patched) { out += std::string(": 已解锁") + rva; continue; }
        DWORD old = 0;
        SIZE_T put = 0;
        bool ok = VirtualProtectEx(h, (LPVOID)addr, s.write_len, PAGE_EXECUTE_READWRITE, &old) &&
                  WriteProcessMemory(h, (LPVOID)addr, s.patched.data(), s.write_len, &put) && put == s.write_len;
        if (old) VirtualProtectEx(h, (LPVOID)addr, s.write_len, old, &old);
        FlushInstructionCache(h, (LPCVOID)addr, s.write_len);
        out += ok ? std::string(": 解锁成功") + rva : std::string(": 写入失败") + rva;
        all_ok = all_ok && ok;
    }
    return out;
}
#endif

}  // namespace nu
