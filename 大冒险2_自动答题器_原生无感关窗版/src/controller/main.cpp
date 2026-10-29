// controller/main.cpp — 大冒险2 自动答题与原生无感关窗控制器 (原生单文件免安装运行版)
// 特性：
// 1. 纯 C++17 编写，静态链接，100% 独立单文件运行（目标电脑无需安装 Python 或任何第三方环境）
// 2. 完美适配 Windows 11 / Windows 10 控制台，全量采用 Win32 原生 WriteConsoleW 输出，杜绝任何 GBK/UTF-8 乱码
// 3. 自动多开发现与注入守护（自动为所有 WAATClient.exe 注入 quizbot_hook.dll）
// 4. 内置 221 道精选题库与动态算术求解引擎，自适应乱序选项文本匹配
// 5. 联动游戏主 UI 线程原生 CloseDialog (基址 + RVA_CLOSE_DIALOG) 瞬间关窗，零延迟、不抢鼠标、无残留
// 6. 每个游戏窗口解锁自带「辅助工具」的战斗辅助页和自动采集页（native_unlock.h，内存补丁；--no-unlock 关掉）
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <set>
#include <map>
#include <mutex>
#include <thread>
#include <chrono>
#include <regex>
#include <atomic>
#include <sstream>

#include "../dll/bank_data.h"
#include "../dll/game_addrs.h"
#include "../dll/map_names.h"
#include "boss_quiz.h"
#include "native_unlock.h"

// ---------------- 编码转换与原生 Unicode 控制台日志 ----------------
static std::mutex g_log_mtx;

static std::wstring u8_to_ws(const std::string& u8) {
    if (u8.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, u8.c_str(), (int)u8.size(), NULL, 0);
    if (n <= 0) return L"";
    std::wstring ws(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, u8.c_str(), (int)u8.size(), &ws[0], n);
    return ws;
}

static void write_output_w(HANDLE h, const wchar_t* str, DWORD len) {
    DWORD mode = 0;
    if (GetConsoleMode(h, &mode)) {
        DWORD written = 0;
        WriteConsoleW(h, str, len, &written, NULL);
    } else {
        int u8_len = WideCharToMultiByte(CP_UTF8, 0, str, (int)len, NULL, 0, NULL, NULL);
        if (u8_len > 0) {
            std::string u8(u8_len, 0);
            WideCharToMultiByte(CP_UTF8, 0, str, (int)len, &u8[0], u8_len, NULL, NULL);
            DWORD written = 0;
            WriteFile(h, u8.data(), (DWORD)u8.size(), &written, NULL);
        }
    }
}

static void log_info_w(const wchar_t* tag, WORD col, const wchar_t* fmt, ...) {
    std::lock_guard<std::mutex> lk(g_log_mtx);
    SYSTEMTIME t; GetLocalTime(&t);
    wchar_t buf[2048];
    va_list ap; va_start(ap, fmt);
    vswprintf(buf, sizeof(buf)/sizeof(wchar_t), fmt, ap);
    va_end(ap);

    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);

    wchar_t time_buf[32];
    swprintf(time_buf, sizeof(time_buf)/sizeof(wchar_t), L"[%02u:%02u:%02u] ", t.wHour, t.wMinute, t.wSecond);
    SetConsoleTextAttribute(hOut, 8); // 灰色时间
    write_output_w(hOut, time_buf, (DWORD)wcslen(time_buf));

    SetConsoleTextAttribute(hOut, col);
    wchar_t tag_buf[64];
    swprintf(tag_buf, sizeof(tag_buf)/sizeof(wchar_t), L"[%ls] ", tag);
    write_output_w(hOut, tag_buf, (DWORD)wcslen(tag_buf));

    SetConsoleTextAttribute(hOut, 7);
    write_output_w(hOut, buf, (DWORD)wcslen(buf));
    write_output_w(hOut, L"\n", 1);
}

// ---------------- 游戏角色名称与账号缓存与跨进程获取 (MSVC std::string 内存结构解析) ----------------
struct ClientInfo {
    std::wstring role_name;
    std::wstring account;
};

static std::mutex g_name_mtx;
static std::map<DWORD, ClientInfo> g_pid_to_info;

static void cache_client_info(DWORD pid, const std::wstring& role_name, const std::wstring& account) {
    if (role_name.empty() && account.empty()) return;
    std::lock_guard<std::mutex> lk(g_name_mtx);
    auto& info = g_pid_to_info[pid];
    if (!role_name.empty()) info.role_name = role_name;
    if (!account.empty()) info.account = account;
}

static std::wstring read_remote_msvc_string(HANDLE h, uint32_t addr) {
    uint32_t str_size = 0, str_res = 0;
    if (!ReadProcessMemory(h, (void*)(addr + 16), &str_size, 4, NULL)) return L"";
    if (!ReadProcessMemory(h, (void*)(addr + 20), &str_res, 4, NULL)) return L"";
    if (str_size == 0 || str_size > 64) return L"";

    char buf[64] = {0};
    if (str_res < 16) {
        if (!ReadProcessMemory(h, (void*)addr, buf, str_size, NULL)) return L"";
    } else {
        uint32_t ptr = 0;
        if (!ReadProcessMemory(h, (void*)addr, &ptr, 4, NULL) || !ptr) return L"";
        if (!ReadProcessMemory(h, (void*)ptr, buf, str_size, NULL)) return L"";
    }

    if (buf[0] != 0) {
        int wlen = MultiByteToWideChar(936, 0, buf, (int)str_size, NULL, 0);
        if (wlen > 0) {
            std::wstring ws(wlen, 0);
            MultiByteToWideChar(936, 0, buf, (int)str_size, &ws[0], wlen);
            return ws;
        }
    }
    return L"";
}

static void query_process_client_info(DWORD pid, std::wstring& out_role, std::wstring& out_account) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snap == INVALID_HANDLE_VALUE) return;

    MODULEENTRY32W me; me.dwSize = sizeof(me);
    uintptr_t base = 0;
    if (Module32FirstW(snap, &me)) {
        do {
            if (_wcsicmp(me.szModule, L"WAATClient.exe") == 0) {
                base = (uintptr_t)me.modBaseAddr;
                break;
            }
        } while (Module32NextW(snap, &me));
    }
    CloseHandle(snap);
    if (!base) return;

    HANDLE h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!h) return;

    uint32_t p0 = 0;
    if (ReadProcessMemory(h, (void*)(base + ga::RVA_PLAYER0), &p0, 4, NULL) && p0) {
        // +0xC84: 游戏内真实角色名 (如"伏地魔1")
        out_role = read_remote_msvc_string(h, p0 + 0xC84);
        // +0xB7C: 登录账号名 (如"qooqp6")
        out_account = read_remote_msvc_string(h, p0 + 0xB7C);
    }
    CloseHandle(h);
}

static std::wstring get_client_tag(DWORD pid) {
    ClientInfo info;
    {
        std::lock_guard<std::mutex> lk(g_name_mtx);
        auto it = g_pid_to_info.find(pid);
        if (it != g_pid_to_info.end()) {
            info = it->second;
        }
    }
    if (info.role_name.empty()) {
        query_process_client_info(pid, info.role_name, info.account);
        if (!info.role_name.empty() || !info.account.empty()) {
            cache_client_info(pid, info.role_name, info.account);
        }
    }

    wchar_t buf[256];
    if (!info.role_name.empty()) {
        if (!info.account.empty() && info.account != info.role_name) {
            swprintf(buf, sizeof(buf)/sizeof(wchar_t), L"[角色: %ls (账号: %ls, pid %lu)]",
                     info.role_name.c_str(), info.account.c_str(), pid);
        } else {
            swprintf(buf, sizeof(buf)/sizeof(wchar_t), L"[角色: %ls (pid %lu)]",
                     info.role_name.c_str(), pid);
        }
    } else if (!info.account.empty()) {
        swprintf(buf, sizeof(buf)/sizeof(wchar_t), L"[账号: %ls (pid %lu)]",
                 info.account.c_str(), pid);
    } else {
        swprintf(buf, sizeof(buf)/sizeof(wchar_t), L"[pid %lu]", pid);
    }
    return buf;
}

// ---------------- 查找客户端与注入 ----------------
static std::wstring get_app_dir() {
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    wchar_t* slash = wcsrchr(path, L'\\');
    if (slash) *slash = 0;
    return path;
}

// ---------------- 战斗收益与怪物数量实时监控 (控制器独立内存采集与双轨静默记录) ----------------
static uintptr_t get_game_mod_base(DWORD pid) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    MODULEENTRY32W me; me.dwSize = sizeof(me);
    uintptr_t base = 0;
    if (Module32FirstW(snap, &me)) {
        do {
            if (_wcsicmp(me.szModule, L"WAATClient.exe") == 0) {
                base = (uintptr_t)me.modBaseAddr;
                break;
            }
        } while (Module32NextW(snap, &me));
    }
    CloseHandle(snap);
    return base;
}

struct ClientLiveState {
    HANDLE hProcess = NULL;
    uintptr_t mod_base = 0;
    int live_monsters = 0;
    int last_positive_monsters = 0;
};
static std::mutex g_state_mtx;
static std::map<DWORD, ClientLiveState> g_client_states;

static void battle_tracker_thread() {
    while (true) {
        std::map<DWORD, std::pair<HANDLE, uintptr_t>> targets;
        {
            std::lock_guard<std::mutex> lk(g_state_mtx);
            for (auto& kv : g_client_states) {
                if (kv.second.hProcess && kv.second.mod_base) {
                    targets[kv.first] = {kv.second.hProcess, kv.second.mod_base};
                }
            }
        }

        for (auto& item : targets) {
            DWORD pid = item.first;
            HANDLE h = item.second.first;
            uintptr_t base = item.second.second;

            uint32_t battle = 0;
            if (ReadProcessMemory(h, (void*)(base + ga::RVA_BATTLE), &battle, 4, NULL) && battle) {
                uint8_t raw[10 * ga::FIGHTER_SIZE];
                if (ReadProcessMemory(h, (void*)(battle + ga::BATTLE_FIGHTERS), raw, sizeof(raw), NULL)) {
                    int cnt = 0;
                    for (int s = 0; s < 10; s++) {
                        uint32_t kind = *(uint32_t*)(raw + s * ga::FIGHTER_SIZE);
                        if (kind != 0 && kind != 0xFFFFFFFF) {
                            cnt++;
                        }
                    }
                    std::lock_guard<std::mutex> lk(g_state_mtx);
                    auto it = g_client_states.find(pid);
                    if (it != g_client_states.end()) {
                        it->second.live_monsters = cnt;
                        if (cnt > 0) {
                            it->second.last_positive_monsters = cnt;
                        }
                    }
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    }
}

static std::mutex g_csv_mtx;

static void write_csv_record(const std::wstring& csv_path, const SYSTEMTIME& t, DWORD pid,
                             const std::wstring& role_name, const std::wstring& account,
                             int map_id, const std::string& map_name, int level, int monsters,
                             long long char_exp, long long pet_exp) {
    bool is_new = (GetFileAttributesW(csv_path.c_str()) == INVALID_FILE_ATTRIBUTES);
    HANDLE f = CreateFileW(csv_path.c_str(), FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return;

    if (is_new || GetFileSize(f, NULL) == 0) {
        const unsigned char bom[] = {0xEF, 0xBB, 0xBF};
        DWORD wrote = 0;
        WriteFile(f, bom, sizeof(bom), &wrote, nullptr);
        const char header[] = "时间,PID,角色名,账号,地图ID,地图名,角色等级,怪物数量,角色结算经验,宠物结算经验\r\n";
        WriteFile(f, header, (DWORD)strlen(header), &wrote, nullptr);
    }

    std::string u8_role, u8_acc;
    int rlen = WideCharToMultiByte(CP_UTF8, 0, role_name.c_str(), (int)role_name.size(), NULL, 0, NULL, NULL);
    if (rlen > 0) { u8_role.resize(rlen); WideCharToMultiByte(CP_UTF8, 0, role_name.c_str(), (int)role_name.size(), &u8_role[0], rlen, NULL, NULL); }
    int alen = WideCharToMultiByte(CP_UTF8, 0, account.c_str(), (int)account.size(), NULL, 0, NULL, NULL);
    if (alen > 0) { u8_acc.resize(alen); WideCharToMultiByte(CP_UTF8, 0, account.c_str(), (int)account.size(), &u8_acc[0], alen, NULL, NULL); }

    char line[1024];
    int n = snprintf(line, sizeof(line),
        "%04u-%02u-%02u %02u:%02u:%02u,%lu,%s,%s,%d,%s,%d,%d,%lld,%lld\r\n",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond,
        pid, u8_role.c_str(), u8_acc.c_str(), map_id, map_name.c_str(), level, monsters, char_exp, pet_exp);
    if (n > 0) {
        DWORD wrote = 0;
        WriteFile(f, line, (DWORD)n, &wrote, nullptr);
    }
    CloseHandle(f);
}

static void write_txt_log_record(const std::wstring& log_path, const SYSTEMTIME& t,
                                 const std::wstring& role_name, int level, int map_id,
                                 const std::string& map_name, int monsters,
                                 long long char_exp, long long pet_exp) {
    HANDLE f = CreateFileW(log_path.c_str(), FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return;

    std::string u8_role;
    int rlen = WideCharToMultiByte(CP_UTF8, 0, role_name.c_str(), (int)role_name.size(), NULL, 0, NULL, NULL);
    if (rlen > 0) { u8_role.resize(rlen); WideCharToMultiByte(CP_UTF8, 0, role_name.c_str(), (int)role_name.size(), &u8_role[0], rlen, NULL, NULL); }

    char line[1024];
    int n = snprintf(line, sizeof(line),
        "%04u-%02u-%02u %02u:%02u:%02u.%03u [BATTLE] 角色=%s 等级=%d 地图=%d(%s) 怪物数=%d 角色经验=%lld 宠物经验=%lld\r\n",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds,
        u8_role.c_str(), level, map_id, map_name.c_str(), monsters, char_exp, pet_exp);
    if (n > 0) {
        DWORD wrote = 0;
        WriteFile(f, line, (DWORD)n, &wrote, nullptr);
    }
    CloseHandle(f);
}

static void record_battle_profit(DWORD pid, long long char_exp, long long pet_exp,
                                 int json_monsters = -1, int json_level = -1,
                                 int json_map_id = -1, const std::string& json_map_name = "") {
    std::lock_guard<std::mutex> lk(g_csv_mtx);

    SYSTEMTIME t; GetLocalTime(&t);
    std::wstring app_dir = get_app_dir();
    std::wstring log_dir = app_dir + L"\\logs";
    CreateDirectoryW(log_dir.c_str(), nullptr);

    ClientInfo info;
    {
        std::lock_guard<std::mutex> n_lk(g_name_mtx);
        info = g_pid_to_info[pid];
    }
    if (info.role_name.empty()) {
        query_process_client_info(pid, info.role_name, info.account);
        cache_client_info(pid, info.role_name, info.account);
    }

    int level = (json_level > 0) ? json_level : 0;
    int map_id = (json_map_id >= 0) ? json_map_id : 0;
    int monsters = (json_monsters >= 0) ? json_monsters : 0;
    std::string map_name = !json_map_name.empty() ? json_map_name : "";

    HANDLE h = NULL;
    uintptr_t base = 0;
    bool need_close = false;
    {
        std::lock_guard<std::mutex> s_lk(g_state_mtx);
        auto it = g_client_states.find(pid);
        if (it != g_client_states.end()) {
            h = it->second.hProcess;
            base = it->second.mod_base;
            if (monsters <= 0) {
                monsters = it->second.last_positive_monsters;
                if (monsters <= 0) monsters = it->second.live_monsters;
            }
            it->second.last_positive_monsters = 0;
        }
    }

    if (level <= 0 || map_id == 0 || monsters <= 0) {
        if (!h) {
            h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
            if (h) need_close = true;
        }
        if (!base) {
            base = get_game_mod_base(pid);
        }

        if (h && base) {
            if (level <= 0) {
                uint32_t p0 = 0;
                if (ReadProcessMemory(h, (void*)(base + ga::RVA_SESSION), &p0, 4, NULL) && p0) {
                    ReadProcessMemory(h, (void*)(p0 + 0x0EAC), &level, 4, NULL);
                }
            }

            if (map_id == 0) {
                uint32_t p1 = 0, p2 = 0;
                if (ReadProcessMemory(h, (void*)(base + ga::RVA_PLAYER_PTR), &p1, 4, NULL) && p1) {
                    if (ReadProcessMemory(h, (void*)(p1 + 4), &p2, 4, NULL) && p2) {
                        ReadProcessMemory(h, (void*)(p2 + 0x2E4), &map_id, 4, NULL);
                    }
                }
            }

            if (monsters <= 0) {
                uint32_t battle = 0;
                if (ReadProcessMemory(h, (void*)(base + ga::RVA_BATTLE), &battle, 4, NULL) && battle) {
                    uint8_t raw[10 * ga::FIGHTER_SIZE];
                    if (ReadProcessMemory(h, (void*)(battle + ga::BATTLE_FIGHTERS), raw, sizeof(raw), NULL)) {
                        for (int s = 0; s < 10; s++) {
                            uint32_t kind = *(uint32_t*)(raw + s * ga::FIGHTER_SIZE);
                            if (kind != 0 && kind != 0xFFFFFFFF) monsters++;
                        }
                    }
                }
            }
        }

        if (need_close && h) CloseHandle(h);
    }

    if (map_name.empty() || map_name == "未知地图") {
        map_name = get_map_name(map_id);
    }

    // 1. 写入 app_dir\logs\battle_profit.csv
    write_csv_record(log_dir + L"\\battle_profit.csv", t, pid, info.role_name, info.account,
                     map_id, map_name, level, monsters, char_exp, pet_exp);

    // 2. 写入 app_dir\logs\quizbot_<pid>.log
    wchar_t pid_log_name[64];
    swprintf(pid_log_name, sizeof(pid_log_name)/sizeof(wchar_t), L"\\quizbot_%lu.log", pid);
    write_txt_log_record(log_dir + pid_log_name, t, info.role_name, level, map_id, map_name, monsters, char_exp, pet_exp);

    // 3. 同时同步一份到工作区根目录下的 logs (双保底)
    wchar_t exe_path[MAX_PATH];
    GetModuleFileNameW(nullptr, exe_path, MAX_PATH);
    wchar_t* s1 = wcsrchr(exe_path, L'\\');
    if (s1) {
        *s1 = 0;
        wchar_t* s2 = wcsrchr(exe_path, L'\\');
        if (s2) {
            std::wstring parent_logs = std::wstring(exe_path, s2) + L"\\logs";
            DWORD attr = GetFileAttributesW(parent_logs.c_str());
            if (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY)) {
                write_csv_record(parent_logs + L"\\battle_profit.csv", t, pid, info.role_name, info.account,
                                 map_id, map_name, level, monsters, char_exp, pet_exp);
                write_txt_log_record(parent_logs + pid_log_name, t, info.role_name, level, map_id, map_name, monsters, char_exp, pet_exp);
            }
        }
    }
}

static std::vector<DWORD> find_game_pids() {
    std::vector<DWORD> out;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;
    PROCESSENTRY32W e; e.dwSize = sizeof e;
    if (Process32FirstW(snap, &e)) {
        do {
            if (_wcsicmp(e.szExeFile, L"WAATClient.exe") == 0) {
                out.push_back(e.th32ProcessID);
            }
        } while (Process32NextW(snap, &e));
    }
    CloseHandle(snap);
    return out;
}

static bool is_module_injected(DWORD pid, const wchar_t* dll_name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snap == INVALID_HANDLE_VALUE) return false;
    MODULEENTRY32W m; m.dwSize = sizeof m;
    bool found = false;
    if (Module32FirstW(snap, &m)) {
        do {
            if (_wcsicmp(m.szModule, dll_name) == 0) { found = true; break; }
        } while (Module32NextW(snap, &m));
    }
    CloseHandle(snap);
    return found;
}

static bool enable_debug_privilege() {
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken)) {
        return false;
    }
    LUID luid;
    if (!LookupPrivilegeValueW(NULL, L"SeDebugPrivilege", &luid)) {
        CloseHandle(hToken);
        return false;
    }
    TOKEN_PRIVILEGES tp;
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    BOOL ok = AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(tp), NULL, NULL);
    DWORD err = GetLastError();
    CloseHandle(hToken);
    return ok && (err == ERROR_SUCCESS);
}

static bool inject_dll(DWORD pid, const std::wstring& dll_path) {
    if (is_module_injected(pid, L"quizbot_hook.dll")) {
        return true;
    }
    HANDLE h = OpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
    if (!h) {
        h = OpenProcess(
            PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
            FALSE, pid);
    }
    if (!h) {
        DWORD err = GetLastError();
        log_info_w(L"注入", 12, L"OpenProcess 失败 (%ls, 错误码=%lu)", get_client_tag(pid).c_str(), err);
        if (err == 5) {
            log_info_w(L"权限", 12, L"提示: 由于权限不足 (Error 5 拒绝访问)，请以管理员身份运行本程序！");
        }
        return false;
    }

    SIZE_T len = (dll_path.size() + 1) * sizeof(wchar_t);
    void* remote = VirtualAllocEx(h, nullptr, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote) {
        log_info_w(L"注入", 12, L"VirtualAllocEx 失败 (%ls, 错误码=%lu)", get_client_tag(pid).c_str(), GetLastError());
        CloseHandle(h);
        return false;
    }

    if (!WriteProcessMemory(h, remote, dll_path.c_str(), len, nullptr)) {
        log_info_w(L"注入", 12, L"WriteProcessMemory 失败 (%ls, 错误码=%lu)", get_client_tag(pid).c_str(), GetLastError());
        VirtualFreeEx(h, remote, 0, MEM_RELEASE);
        CloseHandle(h);
        return false;
    }

    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    auto LLA = (LPTHREAD_START_ROUTINE)GetProcAddress(k32, "LoadLibraryW");
    HANDLE th = CreateRemoteThread(h, nullptr, 0, LLA, remote, 0, nullptr);
    if (!th) {
        log_info_w(L"注入", 12, L"CreateRemoteThread 失败 (%ls, 错误码=%lu)", get_client_tag(pid).c_str(), GetLastError());
        VirtualFreeEx(h, remote, 0, MEM_RELEASE);
        CloseHandle(h);
        return false;
    }

    WaitForSingleObject(th, 6000);
    DWORD code = 0;
    GetExitCodeThread(th, &code);
    CloseHandle(th);
    VirtualFreeEx(h, remote, 0, MEM_RELEASE);
    CloseHandle(h);

    bool ok = (code != 0);
    if (ok) {
        log_info_w(L"注入", 10, L"成功为客户端 %ls 注入核心模块 quizbot_hook.dll", get_client_tag(pid).c_str());
    } else {
        log_info_w(L"注入", 12, L"客户端 %ls 注入失败 (LoadLibrary 返回 NULL)", get_client_tag(pid).c_str());
    }
    return ok;
}

// ---------------- 智能答题求解引擎 ----------------
static std::string trim_stem(const std::string& s) {
    std::string out = s;
    size_t i = 0;
    while (i < out.size() && (out[i] >= '0' && out[i] <= '9')) i++;
    if (i < out.size() && (out[i] == '.' || out[i] == ' ' || (unsigned char)out[i] == 0xa1)) {
        while (i < out.size() && (out[i] == '.' || out[i] == ' ' || (unsigned char)out[i] == 0xa1 || (unsigned char)out[i] == 0xa2)) i++;
        out = out.substr(i);
    }
    while (!out.empty() && (out.back() == '?' || out.back() == ' ' || out.back() == '\n' || out.back() == '\r')) {
        out.pop_back();
    }
    return out;
}

static int solve_math(const std::string& stem, const std::vector<std::string>& options, std::string& why) {
    std::regex re("(\\d+)\\s*([\\+\\-\\*/×÷]|等于|乘以|除以)\\s*(\\d+)");
    std::smatch m;
    if (std::regex_search(stem, m, re)) {
        long long a = std::stoll(m[1].str());
        std::string op = m[2].str();
        long long b = std::stoll(m[3].str());
        long long res = 0;
        bool valid = true;
        if (op == "+" || op.find("加") != std::string::npos) res = a + b;
        else if (op == "-" || op.find("减") != std::string::npos) res = a - b;
        else if (op == "*" || op == "×" || op.find("乘") != std::string::npos) res = a * b;
        else if ((op == "/" || op == "÷" || op.find("除") != std::string::npos) && b != 0) res = a / b;
        else valid = false;

        if (valid) {
            std::string res_str = std::to_string(res);
            for (size_t i = 0; i < options.size(); i++) {
                if (options[i].find(res_str) != std::string::npos) {
                    why = "算术计算(" + std::to_string(a) + op + std::to_string(b) + "=" + res_str + ")";
                    return (int)i;
                }
                if (res == 42 && (options[i].find("肆拾贰") != std::string::npos || options[i].find("四十二") != std::string::npos)) {
                    why = "算术计算(42:肆拾贰)"; return (int)i;
                }
                if (res == 100 && (options[i].find("壹佰") != std::string::npos || options[i].find("一百") != std::string::npos)) {
                    why = "算术计算(100:壹佰)"; return (int)i;
                }
                if (res == 10 && (options[i].find("拾") != std::string::npos || options[i].find("十") != std::string::npos)) {
                    why = "算术计算(10:拾)"; return (int)i;
                }
                if (res == 12 && (options[i].find("拾贰") != std::string::npos || options[i].find("十二") != std::string::npos)) {
                    why = "算术计算(12:拾贰)"; return (int)i;
                }
                if (res == 7 && (options[i].find("柒") != std::string::npos || options[i].find("七") != std::string::npos)) {
                    why = "算术计算(7:柒)"; return (int)i;
                }
                if (res == 3 && (options[i].find("叁") != std::string::npos || options[i].find("三") != std::string::npos)) {
                    why = "算术计算(3:叁)"; return (int)i;
                }
                if (res == 4 && (options[i].find("肆") != std::string::npos || options[i].find("四") != std::string::npos)) {
                    why = "算术计算(4:肆)"; return (int)i;
                }
                if (res == 5 && (options[i].find("伍") != std::string::npos || options[i].find("五") != std::string::npos)) {
                    why = "算术计算(5:伍)"; return (int)i;
                }
                if (res == 8 && (options[i].find("捌") != std::string::npos || options[i].find("八") != std::string::npos)) {
                    why = "算术计算(8:捌)"; return (int)i;
                }
                if (res == 20 && (options[i].find("贰拾") != std::string::npos || options[i].find("二十") != std::string::npos)) {
                    why = "算术计算(20:贰拾)"; return (int)i;
                }
            }
        }
    }
    return -1;
}

static int solve_question(const std::string& raw_stem, const std::vector<std::string>& options, std::string& why) {
    if (options.empty()) return 0;
    std::string stem = trim_stem(raw_stem);
    const auto& bank = get_embedded_bank();

    // 1. 题库检索 (支持题干子串匹配与答案文本自适应匹配)
    for (const auto& entry : bank) {
        if (entry.stem.empty()) continue;
        if (stem.find(entry.stem) != std::string::npos || entry.stem.find(stem) != std::string::npos ||
            (entry.stem.size() >= 8 && stem.find(entry.stem.substr(0, 8)) != std::string::npos)) {

            // 优先根据答案文本在选项中匹配 (免疫游戏洗牌乱序)
            if (!entry.answer.empty()) {
                for (size_t i = 0; i < options.size(); i++) {
                    if (options[i].find(entry.answer) != std::string::npos || entry.answer.find(options[i]) != std::string::npos) {
                        why = "题库命中(文本: " + entry.answer + ")";
                        return (int)i;
                    }
                }
            }

            // 备用索引匹配
            if (entry.fallback_opt >= 0 && entry.fallback_opt < (int)options.size()) {
                why = "题库命中(历史索引: " + std::to_string(entry.fallback_opt) + ")";
                return entry.fallback_opt;
            }
        }
    }

    // 2. 算术计算求解
    int math_opt = solve_math(stem, options, why);
    if (math_opt >= 0 && math_opt < (int)options.size()) {
        return math_opt;
    }

    // 3. 兜底默认选择第 1 项
    why = "未知题目(默认兜底)";
    return 0;
}

// ---------------- boss 题（0x46F5）：查题号表 -> 排除干扰项 -> 表里没有就弹窗问人；答对自动记表 ----------------
// 题库文件：data\boss_bank.tsv、data\boss_decoys.txt（格式见 boss_quiz.h）。
static const DWORD MAP_ANSWER_DELAY_MS = 1500;   // 题库命中后等多久再答（人手答大约 4~10 秒）

struct MapPending {
    uint32_t qno = 0;
    std::string stem;
    std::vector<std::string> options;
};
static std::mutex g_boss_mtx;                       // 管 g_boss、g_map_pending
static bq::Bank g_boss;
static std::map<DWORD, MapPending> g_map_pending;   // 每个窗口现在开着的那道 boss 题
static std::mutex g_pipe_mtx;                       // 管 g_pipes 和往管道写
static std::map<DWORD, HANDLE> g_pipes;

static std::wstring boss_file(const wchar_t* name) { return get_app_dir() + L"\\data\\" + name; }

static bool read_file_w(const std::wstring& path, std::string& out) {
    FILE* f = _wfopen(path.c_str(), L"rb");
    if (!f) return false;
    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) out.append(buf, n);
    fclose(f);
    return true;
}

static bool write_file_w(const std::wstring& path, const std::string& data) {
    std::wstring tmp = path + L".tmp";
    FILE* f = _wfopen(tmp.c_str(), L"wb");
    if (!f) return false;
    bool ok = fwrite(data.data(), 1, data.size(), f) == data.size();
    ok = (fclose(f) == 0) && ok;
    return ok && MoveFileExW(tmp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING);
}

static void load_boss_bank() {
    std::lock_guard<std::mutex> lk(g_boss_mtx);
    std::string a, b;
    if (read_file_w(boss_file(L"boss_bank.tsv"), a)) {
        std::istringstream in(a);
        bq::parse_bank_tsv(g_boss, in);
    }
    if (read_file_w(boss_file(L"boss_decoys.txt"), b)) {
        std::istringstream in(b);
        bq::parse_decoys(g_boss, in);
    }
    log_info_w(L"系统", 10, L"已加载 boss 题库: %zu 道（干扰项 %zu 个），表里没有的题会弹窗问你",
               g_boss.entries.size(), g_boss.decoys.size());
}

static void save_boss_bank_locked() {
    std::ostringstream a, b;
    bq::write_bank_tsv(g_boss, a);
    bq::write_decoys(g_boss, b);
    if (!write_file_w(boss_file(L"boss_bank.tsv"), a.str()) || !write_file_w(boss_file(L"boss_decoys.txt"), b.str()))
        log_info_w(L"boss答题", 12, L"[警告] 题库文件写不进去：%ls", boss_file(L"boss_bank.tsv").c_str());
}

static bool pipe_send(DWORD pid, const std::string& cmd) {
    std::lock_guard<std::mutex> lk(g_pipe_mtx);
    auto it = g_pipes.find(pid);
    if (it == g_pipes.end()) return false;
    DWORD wrote = 0;
    return WriteFile(it->second, cmd.data(), (DWORD)cmd.size(), &wrote, nullptr) && wrote == cmd.size();
}

// 题还开着才发（用户可能已经自己点了）。
static void send_map_answer(DWORD pid, uint32_t qno, int opt) {
    {
        std::lock_guard<std::mutex> lk(g_boss_mtx);
        auto it = g_map_pending.find(pid);
        if (it == g_map_pending.end() || it->second.qno != qno) {
            log_info_w(L"boss答题", 7, L"%ls 题号 %u 已经答过了，不再发", get_client_tag(pid).c_str(), qno);
            return;
        }
    }
    char cmd[128];
    snprintf(cmd, sizeof cmd, "{\"cmd\":\"answer\",\"kind\":\"map\",\"qno\":%u,\"opt\":%d}\n", qno, opt);
    if (!pipe_send(pid, cmd))
        log_info_w(L"boss答题", 12, L"%ls 管道已断开，题号 %u 没发出去", get_client_tag(pid).c_str(), qno);
}

static void handle_map_question(DWORD pid, uint32_t qno, const std::string& stem, const std::vector<std::string>& options) {
    bq::Decision d;
    {
        std::lock_guard<std::mutex> lk(g_boss_mtx);
        g_map_pending[pid] = MapPending{qno, stem, options};
        d = bq::decide(g_boss, qno, stem, options);
    }
    std::wstring tag = get_client_tag(pid);
    std::wstring w_opts;
    for (size_t i = 0; i < options.size(); i++) w_opts += L"\n    " + u8_to_ws(options[i]);
    log_info_w(L"boss题目", 14, L"%ls 题号 %u：%ls%ls", tag.c_str(), qno, u8_to_ws(stem).c_str(), w_opts.c_str());

    // 静默：不弹窗。题库命中 > 排除干扰项的建议 > 猜（见 bq::decide 的 guess），一律自动答。
    int opt = d.guess;
    if (opt < 0) {
        log_info_w(L"boss决策", 12, L"%ls 题号 %u 没有选项可选，请手动答", tag.c_str(), qno);
        return;
    }
    const wchar_t* kind = d.opt >= 0 ? L"题库" : d.suggest >= 0 ? L"排除法" : L"[猜的]";
    log_info_w(L"boss决策", d.opt >= 0 ? 11 : d.suggest >= 0 ? 14 : 12, L"%ls %ls 选第 %d 项（%ls）-> %ls", tag.c_str(),
               kind, opt + 1, u8_to_ws(options[opt]).c_str(), u8_to_ws(d.why).c_str());
    std::thread([pid, qno, opt] {
        Sleep(MAP_ANSWER_DELAY_MS);
        send_map_answer(pid, qno, opt);
    }).detach();
}

static long long json_int(const std::string& line, const char* key) {
    auto p = line.find(key);
    return p == std::string::npos ? -1 : atoll(line.c_str() + p + strlen(key));
}

static void handle_map_result(DWORD pid, const std::string& line) {
    uint32_t qno = (uint32_t)json_int(line, "\"qno\":");
    int opt = (int)json_int(line, "\"opt\":");
    bool pass = line.find("\"pass\":true") != std::string::npos;
    bool manual = line.find("\"by\":\"manual\"") != std::string::npos;
    std::wstring tag = get_client_tag(pid);
    std::lock_guard<std::mutex> lk(g_boss_mtx);
    auto it = g_map_pending.find(pid);
    if (!pass) {
        log_info_w(L"boss答题", 12, L"%ls [注意] 题号 %u 选第 %d 项后服务器没说通过，没有记表（原话见日志）",
                   tag.c_str(), qno, opt + 1);
        return;
    }
    if (it == g_map_pending.end() || it->second.qno != qno) {
        log_info_w(L"boss答题", 10, L"%ls 题号 %u 测试通过（没有题目缓存，不记表）", tag.c_str(), qno);
        return;
    }
    const MapPending& m = it->second;
    if (opt >= 0 && opt < (int)m.options.size()) {
        if (bq::record_pass(g_boss, qno, m.stem, m.options, opt)) {
            save_boss_bank_locked();
            log_info_w(L"boss答题", 10, L"%ls 题号 %u 测试通过（%ls答的：%ls），已记进题库，现在共 %zu 道",
                       tag.c_str(), qno, manual ? L"你手动" : L"自动", u8_to_ws(m.options[opt]).c_str(), g_boss.entries.size());
        } else {
            log_info_w(L"boss答题", 10, L"%ls 题号 %u 测试通过（%ls答的）", tag.c_str(), qno, manual ? L"你手动" : L"自动");
        }
    } else {
        log_info_w(L"boss答题", 14, L"%ls 题号 %u 测试通过，但读不到选了哪项，没记表", tag.c_str(), qno);
    }
    g_map_pending.erase(it);
}

// ---------------- 管道客户端通信线程 ----------------
static std::mutex g_session_mtx;
static std::set<DWORD> g_active_sessions;

static void client_session_thread(DWORD pid) {
    char pipe_name[64];
    snprintf(pipe_name, sizeof(pipe_name), "\\\\.\\pipe\\quizbot_v2_%lu", pid);

    HANDLE h = INVALID_HANDLE_VALUE;
    for (int retry = 0; retry < 60; retry++) {
        h = CreateFileA(pipe_name, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (h != INVALID_HANDLE_VALUE) break;
        DWORD err = GetLastError();
        if (err == 231) WaitNamedPipeA(pipe_name, 500);
        else Sleep(300);
    }

    if (h == INVALID_HANDLE_VALUE) {
        log_info_w(L"管道", 12, L"无法连接客户端 %ls 管道 (等待超时)", get_client_tag(pid).c_str());
        std::lock_guard<std::mutex> lk(g_session_mtx);
        g_active_sessions.erase(pid);
        return;
    }

    {
        std::lock_guard<std::mutex> lk(g_session_mtx);
        g_active_sessions.insert(pid);
    }

    {
        HANDLE hProc = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
        uintptr_t mod_base = get_game_mod_base(pid);
        std::lock_guard<std::mutex> lk(g_state_mtx);
        g_client_states[pid] = {hProc, mod_base, 0, 0};
    }

    {
        std::lock_guard<std::mutex> lk(g_pipe_mtx);
        g_pipes[pid] = h;
    }
    log_info_w(L"管道", 10, L"已建立与客户端 %ls 的双向监听通道", get_client_tag(pid).c_str());

    char buf[4096];
    std::string line_buf;
    DWORD read_bytes = 0;

    while (true) {
        DWORD avail = 0;
        if (!PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr)) break;
        if (avail == 0) {
            Sleep(25);
            continue;
        }

        DWORD to_read = (avail < sizeof(buf) - 1) ? avail : (sizeof(buf) - 1);
        if (!ReadFile(h, buf, to_read, &read_bytes, nullptr) || read_bytes == 0) break;

        buf[read_bytes] = 0;
        line_buf.append(buf, read_bytes);

        size_t pos = 0;
        while ((pos = line_buf.find('\n')) != std::string::npos) {
            std::string line = line_buf.substr(0, pos);
            line_buf.erase(0, pos + 1);
            if (line.empty()) continue;

            // 提取事件中的角色名与账号并缓存
            std::string u8_name, u8_account;
            auto p_name = line.find("\"name\":\"");
            if (p_name != std::string::npos) {
                size_t s_start = p_name + 8;
                size_t s_end = line.find("\"", s_start);
                if (s_end != std::string::npos && s_end > s_start) {
                    u8_name = line.substr(s_start, s_end - s_start);
                }
            }
            auto p_acc = line.find("\"account\":\"");
            if (p_acc != std::string::npos) {
                size_t s_start = p_acc + 11;
                size_t s_end = line.find("\"", s_start);
                if (s_end != std::string::npos && s_end > s_start) {
                    u8_account = line.substr(s_start, s_end - s_start);
                }
            }
            if (!u8_name.empty() || !u8_account.empty()) {
                cache_client_info(pid, u8_to_ws(u8_name), u8_to_ws(u8_account));
            }

            if (line.find("\"type\":\"question\"") != std::string::npos) {
                uint32_t qno = 0;
                auto p_qno = line.find("\"qno\":");
                if (p_qno != std::string::npos) qno = (uint32_t)atoi(line.c_str() + p_qno + 6);

                std::string stem;
                auto p_stem = line.find("\"stem\":\"");
                if (p_stem != std::string::npos) {
                    size_t cur = p_stem + 8;
                    while (cur < line.size()) {
                        if (line[cur] == '\\' && cur + 1 < line.size()) {
                            stem += line[cur + 1];
                            cur += 2;
                        } else if (line[cur] == '"') {
                            break;
                        } else {
                            stem += line[cur];
                            cur++;
                        }
                    }
                }

                std::vector<std::string> options;
                auto p_opt = line.find("\"options\":[");
                if (p_opt != std::string::npos) {
                    size_t cur = p_opt + 11;
                    while (cur < line.size() && line[cur] != ']') {
                        size_t q1 = line.find('"', cur);
                        if (q1 == std::string::npos || q1 > line.find(']', cur)) break;
                        size_t opt_cur = q1 + 1;
                        std::string opt_s;
                        while (opt_cur < line.size()) {
                            if (line[opt_cur] == '\\' && opt_cur + 1 < line.size()) {
                                opt_s += line[opt_cur + 1];
                                opt_cur += 2;
                            } else if (line[opt_cur] == '"') {
                                break;
                            } else {
                                opt_s += line[opt_cur];
                                opt_cur++;
                            }
                        }
                        options.push_back(opt_s);
                        cur = opt_cur + 1;
                    }
                }

                if (line.find("\"kind\":\"map\"") != std::string::npos) {
                    handle_map_question(pid, qno, stem, options);
                    continue;
                }

                std::string why;
                int opt = solve_question(stem, options, why);
                std::string opt_text = (opt >= 0 && opt < (int)options.size()) ? options[opt] : "未知";

                std::wstring w_stem = u8_to_ws(stem);
                std::wstring w_opt_text = u8_to_ws(opt_text);
                std::wstring w_why = u8_to_ws(why);

                std::wstring tag = get_client_tag(pid);
                log_info_w(L"收到题目", 14, L"%ls 题目: %ls", tag.c_str(), w_stem.c_str());
                log_info_w(L"智能决策", 11, L"%ls 决策: 选项 %d (%ls) -> %ls",
                           tag.c_str(), opt + 1, w_opt_text.c_str(), w_why.c_str());

                char cmd[256];
                snprintf(cmd, sizeof(cmd), "{\"cmd\":\"answer\",\"qno\":%u,\"opt\":%d}\n", qno, opt);
                pipe_send(pid, cmd);
            }
            else if (line.find("\"type\":\"map_result\"") != std::string::npos) {
                handle_map_result(pid, line);
            }
            else if (line.find("\"type\":\"map_sent\"") != std::string::npos) {
                bool raw = line.find("\"method\":\"raw\"") != std::string::npos;
                log_info_w(L"boss答题", 10, L"%ls 已提交题号 %lld 第 %lld 项%ls", get_client_tag(pid).c_str(),
                           json_int(line, "\"qno\":"), json_int(line, "\"opt\":") + 1,
                           raw ? L"（面板 3 秒没就绪，直接发的包，答题框可能还留在屏幕上）" : L"");
            }
            else if (line.find("\"type\":\"map_fail\"") != std::string::npos) {
                log_info_w(L"boss答题", 12, L"%ls [失败] 题号 %lld 没提交出去，请手动答", get_client_tag(pid).c_str(),
                           json_int(line, "\"qno\":"));
            }
            else if (line.find("\"type\":\"dismissed\"") != std::string::npos) {
                log_info_w(L"原生关窗", 10, L"%ls [OK] 原生 CloseDialog 瞬间销毁答题弹窗完毕！(零延迟·无感关闭)", get_client_tag(pid).c_str());
            }
            else if (line.find("\"type\":\"dismiss_failed\"") != std::string::npos) {
                log_info_w(L"关窗提示", 14, L"%ls [INFO] 未检测到可见弹窗或弹窗已关闭", get_client_tag(pid).c_str());
            }
            else if (line.find("\"type\":\"sys\"") != std::string::npos) {
                if (line.find("测试通过") != std::string::npos) {
                    log_info_w(L"答题通过", 10, L"%ls [CONGRATS] 服务器判定测试通过，奖励已发放！", get_client_tag(pid).c_str());
                } else if (line.find("金币") != std::string::npos) {
                    log_info_w(L"获得金币", 14, L"%ls 获得系统奖励金币", get_client_tag(pid).c_str());
                }
            }
            else if (line.find("\"type\":\"settle\"") != std::string::npos) {
                long long exp = 0;
                auto p_exp = line.find("\"exp\":");
                if (p_exp != std::string::npos) exp = atoll(line.c_str() + p_exp + 6);

                long long pet_exp = 0;
                auto p_pexp = line.find("\"pet_exp\":");
                if (p_pexp != std::string::npos) pet_exp = atoll(line.c_str() + p_pexp + 10);

                int monsters = -1;
                auto p_mon = line.find("\"monsters\":");
                if (p_mon != std::string::npos) monsters = atoi(line.c_str() + p_mon + 11);

                int level = -1;
                auto p_lvl = line.find("\"level\":");
                if (p_lvl != std::string::npos) level = atoi(line.c_str() + p_lvl + 8);

                int map_id = -1;
                auto p_map = line.find("\"map_id\":");
                if (p_map != std::string::npos) map_id = atoi(line.c_str() + p_map + 9);

                std::string map_name;
                auto p_mname = line.find("\"map_name\":\"");
                if (p_mname != std::string::npos) {
                    size_t s_start = p_mname + 12;
                    size_t s_end = line.find("\"", s_start);
                    if (s_end != std::string::npos) map_name = line.substr(s_start, s_end - s_start);
                }

                // 静默写入 battle_profit.csv 及各客户端 quizbot_<pid>.log (控制台不输出任何字符)
                record_battle_profit(pid, exp, pet_exp, monsters, level, map_id, map_name);
            }

        }
    }

    {
        std::lock_guard<std::mutex> lk(g_pipe_mtx);
        g_pipes.erase(pid);
        CloseHandle(h);
    }
    {
        std::lock_guard<std::mutex> lk(g_boss_mtx);
        g_map_pending.erase(pid);
    }
    log_info_w(L"管道", 12, L"客户端 %ls 已断开连接", get_client_tag(pid).c_str());
    {
        std::lock_guard<std::mutex> lk(g_session_mtx);
        g_active_sessions.erase(pid);
    }
    {
        std::lock_guard<std::mutex> lk(g_state_mtx);
        auto it = g_client_states.find(pid);
        if (it != g_client_states.end()) {
            if (it->second.hProcess) CloseHandle(it->second.hProcess);
            g_client_states.erase(it);
        }
    }
}

// ---------------- 检查并自动清理残留旧版答题器 ----------------
static void kill_stale_controllers() {
    DWORD my_pid = GetCurrentProcessId();
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return;
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (pe.th32ProcessID != my_pid && pe.th32ProcessID != 0) {
                if (_wcsicmp(pe.szExeFile, L"启动答题器.exe") == 0 ||
                    _wcsicmp(pe.szExeFile, L"quizbot.exe") == 0) {
                    HANDLE h = OpenProcess(PROCESS_TERMINATE, FALSE, pe.th32ProcessID);
                    if (h) {
                        TerminateProcess(h, 0);
                        CloseHandle(h);
                        log_info_w(L"进程守护", 14, L"检测到旧版答题器残留 (pid %lu)，已自动清理释放管道独占资源", pe.th32ProcessID);
                    }
                }
            }
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
}

// ---------------- 辅助工具界面解锁（native_unlock.h） ----------------
// -> true = 两页都已解锁（或这个进程不用再试）。游戏刚启动时模块可能还没映射全，没成功的下个周期再试。
static bool unlock_native_ui(DWORD pid) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snap == INVALID_HANDLE_VALUE) return false;
    MODULEENTRY32W me; me.dwSize = sizeof(me);
    uintptr_t base = 0; uint32_t size = 0;
    if (Module32FirstW(snap, &me)) {
        do {
            if (_wcsicmp(me.szModule, L"WAATClient.exe") == 0) { base = (uintptr_t)me.modBaseAddr; size = me.modBaseSize; break; }
        } while (Module32NextW(snap, &me));
    }
    CloseHandle(snap);
    if (!base) return false;
    HANDLE h = OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!h) {
        log_info_w(L"解锁", 12, L"%ls 打不开进程 (错误码=%lu)", get_client_tag(pid).c_str(), GetLastError());
        return false;
    }
    bool all_ok = false;
    std::string msg = nu::unlock_process(h, base, size, nu::default_specs(ga::RVA_UNLOCK_FIGHT, ga::RVA_UNLOCK_GATHER), all_ok);
    CloseHandle(h);
    log_info_w(L"解锁", all_ok ? 10 : 12, L"%ls 辅助工具 %ls", get_client_tag(pid).c_str(), u8_to_ws(msg).c_str());
    return all_ok;
}

// ---------------- 主入口 ----------------
int main(int argc, char** argv) {
    bool do_unlock = true;
    for (int i = 1; i < argc; i++)
        if (strcmp(argv[i], "--no-unlock") == 0) do_unlock = false;
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    SetConsoleTitleW(L"大冒险2.0 自动答题器 (原生CloseDialog无感关窗·独立免安装版)");

    // 启用 Windows 调试特权 (SeDebugPrivilege)，解决权限拒绝 (Error 5) 注入失败
    enable_debug_privilege();

    // 自动清理旧版残留的答题器进程，释放 Named Pipe 管道独占资源
    kill_stale_controllers();

    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);

    SetConsoleTextAttribute(hOut, 11);
    const wchar_t banner[] =
        L"===============================================================================\n"
        L"  《什么什么大冒险2.0》自动答题与原生无感关窗辅助 (独立免安装·多开版)\n"
        L"  - 架构: 游戏主 UI 线程原生 CloseDialog 销毁弹窗 (零延迟、不抢鼠标、无残留)\n"
        L"  - 题库: 221 道精选离线官方级题库，智能自适应乱序选项文本匹配\n"
        L"  - 特性: 纯原生 Win32 单文件运行，无需 Python，无需任何第三方运行环境\n"
        L"===============================================================================\n\n";
    write_output_w(hOut, banner, (DWORD)wcslen(banner));
    SetConsoleTextAttribute(hOut, 7);

    std::wstring app_dir = get_app_dir();
    std::wstring dll_path = app_dir + L"\\quizbot_hook.dll";
    if (GetFileAttributesW(dll_path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        dll_path = app_dir + L"\\build\\quizbot_hook.dll";
    }

    if (GetFileAttributesW(dll_path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        log_info_w(L"错误", 12, L"找不到核心模块 quizbot_hook.dll，请确保文件存在！");
        wprintf(L"\n按任意键退出...\n");
        getchar();
        return 1;
    }

    log_info_w(L"系统", 10, L"核心模块已定位: %ls", dll_path.c_str());
    log_info_w(L"系统", 10, L"已加载内置题库: %zu 道精选题目", get_embedded_bank().size());
    load_boss_bank();
    log_info_w(L"守护", 14, L"正在监控 WAATClient.exe 游戏客户端 (支持自动多开并发)...");

    // 启动后台战斗状态采集与收益监控线程
    std::thread(battle_tracker_thread).detach();

    std::set<DWORD> managed_pids;
    std::map<DWORD, int> unlock_tries;     // pid -> 解锁试了几次（成功后记成 -1）
    log_info_w(L"解锁", 14, do_unlock ? L"辅助工具界面解锁: 开（战斗辅助 + 自动采集；启动参数 --no-unlock 关掉）"
                                        : L"辅助工具界面解锁: 关（--no-unlock）");

    while (true) {
        std::vector<DWORD> pids = find_game_pids();

        for (DWORD pid : pids) {
            bool need_connect = false;
            {
                std::lock_guard<std::mutex> lk(g_session_mtx);
                need_connect = (g_active_sessions.find(pid) == g_active_sessions.end());
            }

            if (need_connect) {
                if (managed_pids.find(pid) == managed_pids.end()) {
                    log_info_w(L"检测", 11, L"发现游戏客户端 %ls，正在注入核心模块...", get_client_tag(pid).c_str());
                    if (!inject_dll(pid, dll_path)) {
                        log_info_w(L"注入", 12, L"%ls 注入未完成，将在下个周期自动重试...", get_client_tag(pid).c_str());
                        continue;
                    }
                    managed_pids.insert(pid);
                }
                {
                    std::lock_guard<std::mutex> lk(g_session_mtx);
                    g_active_sessions.insert(pid);
                }
                std::thread(client_session_thread, pid).detach();
            }
        }


        for (DWORD pid : pids) {
            if (!do_unlock || managed_pids.find(pid) == managed_pids.end()) continue;
            int& n = unlock_tries[pid];
            if (n < 0 || n >= 10) continue;            // 已解锁 / 试了 10 次（约 15 秒）还不行就不再刷屏
            n = unlock_native_ui(pid) ? -1 : n + 1;
        }

        std::set<DWORD> alive(pids.begin(), pids.end());
        for (auto it = managed_pids.begin(); it != managed_pids.end(); ) {
            if (alive.find(*it) == alive.end()) {
                log_info_w(L"状态", 8, L"游戏客户端 %ls 已退出", get_client_tag(*it).c_str());
                {
                    std::lock_guard<std::mutex> lk(g_name_mtx);
                    g_pid_to_info.erase(*it);
                }
                unlock_tries.erase(*it);
                it = managed_pids.erase(it);
            } else {
                ++it;
            }
        }

        Sleep(1500);
    }

    return 0;
}
