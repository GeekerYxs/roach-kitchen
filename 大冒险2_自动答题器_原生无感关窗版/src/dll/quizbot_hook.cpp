// quizbot_hook.cpp — 大冒险2 自动答题与进程内静默消除弹窗 Hook DLL (x86)
// =============================================================================
// 核心架构原则：
// 1. 网络层 100% 原始透传：
//    - hook_recv 收到多少字节原封不动返回给游戏，绝不拦截、绝不扣留、绝不超时伪造
//    - 旁路复制入站数据，流式解帧识别 0x46F4 (题目下发)、0x46F5 (boss 开打时的题)、0x46FF (系统提示)、0x472A (战斗结算)
//    - 0x46F5 的答案走游戏自己的提交函数（面板 [ui+0x10C8]，发 0x1F05），见 answer_map_quiz
//    - 收到题目推入管道，控制器决策后下发 answer 命令，经游戏主 Socket 直接发包 0x1F04
//    - 服务器秒级判定答对（测试通过 + 金币奖励），彻底避免 30 秒超时掉线
// 2. 进程内虚拟鼠标静默关窗 (MinHook + DirectInput/GetCursorPos)：
//    - 游戏本地 UI 引擎在收到 0x46F4 后会弹出防外挂答题框
//    - DLL 读取内存 UI 状态 (*(*(base+RVA_UI)+0x10C4)) 检测答题框是否激活 (+0x1C != 0)
//    - 获取答题框精确坐标 (+0x20 Left, +0x24 Top)，计算选项位置
//    - 激活进程内虚拟光标 Hook (GetCursorPos) + DirectInput (GetDeviceState)
//    - 模拟点击任一选项，触发游戏 UI 关闭流程，实现全后台静默关闭，不抢焦点、不移物理鼠标
// =============================================================================
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define DIRECTINPUT_VERSION 0x0800

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <dinput.h>
#include <cstdio>
#include <cstdarg>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <deque>
#include <map>
#include <atomic>

#include "quiz_protocol.h"
#include "game_addrs.h"
#include "map_names.h"
#include "minhook/MinHook.h"

using qp::Tables;
using qp::Question;

// 临界区 RAII 包装
struct CSLock {
    CRITICAL_SECTION& cs;
    CSLock(CRITICAL_SECTION& c) : cs(c) { EnterCriticalSection(&cs); }
    ~CSLock() { LeaveCriticalSection(&cs); }
};

// ---------------- 全局状态 ----------------
static Tables       g_tb;
static HMODULE      g_self = nullptr;
static std::string  g_logdir;
static std::atomic<DWORD> g_recv_bytes{0};
static std::atomic<DWORD> g_frames{0};
static std::atomic<DWORD> g_questions{0};

// 旁路嗅探缓冲
struct SockBuf { std::vector<uint8_t> data; };
static std::map<SOCKET, SockBuf> g_rbuf;
static CRITICAL_SECTION g_sockmtx;
static HANDLE g_wake_event = NULL;

static std::atomic<SOCKET> g_main_sock{INVALID_SOCKET};
static std::atomic<HWND>   g_main_hwnd{NULL};

// ---------------- 进程内虚拟鼠标状态 ----------------
static std::atomic<bool> g_vclick_mode{false};
static std::atomic<int>  g_vclick_down{0};
static std::atomic<LONG> g_vclick_x{0};
static std::atomic<LONG> g_vclick_y{0};
static std::atomic<LONG> g_vclick_count{0};

// 原 API 指针
static BOOL (WINAPI *real_cursor)(LPPOINT) = NULL;
static SHORT (WINAPI *real_async)(int) = NULL;
static HWND (WINAPI *real_active)(VOID) = NULL;
static HWND (WINAPI *real_foreground)(VOID) = NULL;
static HWND (WINAPI *real_focus)(VOID) = NULL;
static HRESULT (WINAPI *real_di_state)(LPDIRECTINPUTDEVICE8A, DWORD, LPVOID) = NULL;

// ---------------- 日志系统 ----------------
static CRITICAL_SECTION g_logmtx;
static void logline(const char* fmt, ...) {
    CSLock lk(g_logmtx);
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%s\\quizbot_%u.log",
                g_logdir.c_str(), GetCurrentProcessId());
    HANDLE f = CreateFileA(path, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return;
    char line[2048];
    SYSTEMTIME t; GetLocalTime(&t);
    int n = _snprintf_s(line, sizeof line, _TRUNCATE,
            "%04u-%02u-%02u %02u:%02u:%02u.%03u ",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list ap; va_start(ap, fmt);
    int m = _vsnprintf_s(line + n, sizeof line - n, _TRUNCATE, fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    if (m < 0) m = 0;
    n += m;
    if (n < (int)sizeof line - 2) { line[n++] = '\r'; line[n++] = '\n'; }
    DWORD wrote = 0;
    WriteFile(f, line, n, &wrote, nullptr);
    CloseHandle(f);
}

// ---------------- 编码转换 ----------------
static std::string gbk_to_utf8(const std::string& gbk) {
    if (gbk.empty()) return {};
    int w = MultiByteToWideChar(936, 0, gbk.data(), (int)gbk.size(), nullptr, 0);
    if (w <= 0) return {};
    std::wstring ws(w, L'\0');
    MultiByteToWideChar(936, 0, gbk.data(), (int)gbk.size(), &ws[0], w);
    int u = WideCharToMultiByte(CP_UTF8, 0, ws.data(), w, nullptr, 0, nullptr, nullptr);
    if (u <= 0) return {};
    std::string out(u, '\0');
    WideCharToMultiByte(CP_UTF8, 0, ws.data(), w, &out[0], u, nullptr, nullptr);
    return out;
}

static std::string jesc(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
        case '"':  out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n";  break;
        case '\r': out += "\\r";  break;
        case '\t': out += "\\t";  break;
        default:
            if (c < 0x20) { char b[8]; _snprintf_s(b, sizeof b, _TRUNCATE, "\\u%04x", c); out += b; }
            else out += (char)c;
        }
    }
    return out;
}

// ---------------- 管道：事件队列 + 异步写线程 ----------------
static HANDLE g_pipe = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_wmtx;
static CRITICAL_SECTION g_connmtx;
static std::deque<std::string> g_eq;
static std::atomic<bool> g_stop{false};

static void push_event(std::string line) {
    CSLock lk(g_wmtx);
    if (g_eq.size() > 512) g_eq.pop_front();
    g_eq.push_back(std::move(line));
    if (g_wake_event) SetEvent(g_wake_event);
}

static DWORD WINAPI writer_thread(LPVOID) {
    while (!g_stop.load()) {
        std::string line;
        {
            CSLock lk(g_wmtx);
            if (!g_eq.empty()) { line = std::move(g_eq.front()); g_eq.pop_front(); }
        }
        if (line.empty()) {
            if (g_wake_event) WaitForSingleObject(g_wake_event, 50);
            else Sleep(10);
            continue;
        }
        bool ok = false;
        {
            CSLock lk(g_connmtx);
            if (g_pipe != INVALID_HANDLE_VALUE) {
                DWORD wrote = 0;
                ok = WriteFile(g_pipe, line.data(), (DWORD)line.size(), &wrote, nullptr) != 0;
            }
        }
        if (!ok) Sleep(20);
    }
    return 0;
}

// ---------------- 查找游戏主窗口 ----------------
struct WindowEnumCtx { DWORD pid; HWND hwnd; };
static BOOL CALLBACK EnumWindowsCb(HWND h, LPARAM lp) {
    auto* c = (WindowEnumCtx*)lp;
    DWORD p = 0;
    GetWindowThreadProcessId(h, &p);
    if (p == c->pid && IsWindowVisible(h)) {
        HWND parent = GetParent(h);
        if (parent == NULL || parent == GetDesktopWindow()) {
            RECT rc;
            if (GetClientRect(h, &rc)) {
                int w = rc.right - rc.left;
                int hgt = rc.bottom - rc.top;
                if (w >= 400 && hgt >= 300) {
                    c->hwnd = h;
                    return FALSE;
                }
            }
        }
        wchar_t title[256];
        if (GetWindowTextW(h, title, 256) > 0) {
            if (wcsstr(title, L"大冒险") || wcsstr(title, L"冒险")) {
                c->hwnd = h;
                return FALSE;
            }
        }
    }
    return TRUE;
}

static HWND find_main_hwnd() {
    HWND cached = g_main_hwnd.load();
    if (cached && IsWindow(cached) && IsWindowVisible(cached)) return cached;

    WindowEnumCtx ctx = { GetCurrentProcessId(), NULL };
    EnumWindows(EnumWindowsCb, (LPARAM)&ctx);

    if (ctx.hwnd) g_main_hwnd.store(ctx.hwnd);
    return ctx.hwnd;
}

// ---------------- 游戏主 UI 线程原生关窗与答题执行机制 ----------------
static std::atomic<int> g_pending_native_opt{-1};

// ---------------- 游戏底层原生 CloseDialog 瞬间销毁题框核心函数 ----------------
static bool invoke_native_dismiss_internal(int opt) {
    if (opt < 0 || opt > 3) opt = 0;

    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return false;
    uint32_t ui = *(uint32_t*)(base + ga::RVA_UI);
    if (!ui) return false;
    uint32_t q = *(uint32_t*)(ui + 0x10c4);
    if (!q) return false;

    uint32_t active = *(uint32_t*)(q + 0x1c);
    if (active == 0) return false; // 弹窗尚未激活显示

    logline("[NATIVE-DISMISS] Dialog active! q=0x%X active=%u opt=%d", q, active, opt);

    // 1. 设置选项索引并触发游戏原生选择逻辑 (OnOptionSelected)
    *(uint32_t*)(q + 0x1ac) = (uint32_t)opt;
    typedef void (__thiscall *FnSelect)(void*);
    ((FnSelect)(base + ga::RVA_QUIZ_SUBMIT))((void*)q);
    logline("[NATIVE-DISMISS] OnOptionSelected(0x%X) executed", q);

    // 2. 游戏原生 CloseDialog 瞬间销毁题框 (零延迟、不移鼠标、无残留)
    uint32_t parent = *(uint32_t*)(q + 0x104);
    if (parent) {
        typedef void (__thiscall *FnClose)(void* pParent, void* pDialog, int flag);
        ((FnClose)(base + ga::RVA_CLOSE_DIALOG))((void*)parent, (void*)q, 0);
        logline("[NATIVE-DISMISS] CloseDialog(parent=0x%X, q=0x%X, 0) executed", parent, q);
    }

    uint32_t still_active = *(uint32_t*)(q + 0x1c);
    logline("[NATIVE-DISMISS] Post dismiss active flag: %u", still_active);
    return (still_active == 0);
}


// ---------------- boss 题（0x46F5，面板 QuestionOnMap = [ui+0x10C8]） ----------------
// 只走游戏自己的提交函数：写 +0x1AC 下标 -> thiscall RVA_QUIZ_SUBMIT(panel) -> CloseDialog。
// 面板 +0x1B4 = 1 时提交函数发的就是 0x1F05，和用户手动点选完全一样，只发一次。
static std::atomic<uint32_t> g_map_qno{0};          // 正在等答案的 boss 题号（0 = 没有）
static std::atomic<int>      g_map_sent_opt{-1};    // 我们替它答的下标（-1 = 还没答 / 用户手动答）
static std::atomic<int>      g_pending_map_opt{-1}; // 等 UI 线程执行的下标
static std::atomic<uint32_t> g_pending_map_qno{0};

static uint32_t map_panel() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t ui = *(uint32_t*)(base + ga::RVA_UI);
    if (!ui || IsBadReadPtr((void*)(ui + ga::UI_QUIZ_MAP), 4)) return 0;
    uint32_t q = *(uint32_t*)(ui + ga::UI_QUIZ_MAP);
    if (!q || IsBadReadPtr((void*)q, 0x1C0)) return 0;
    return q;
}

// 面板开着、题号对得上、是 0x1F05 模式，才提交。返回 true = 已提交。
static bool invoke_native_map_answer(uint32_t qno, int opt) {
    uint32_t q = map_panel();
    if (!q) return false;
    uint32_t visible = *(uint32_t*)(q + ga::QUIZ_VISIBLE);
    uint32_t panel_qno = *(uint32_t*)(q + ga::QUIZ_QNO);
    uint32_t mode = *(uint32_t*)(q + ga::QUIZ_MAP_MODE);
    if (visible == 0 || panel_qno != qno || mode != 1) return false;

    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    logline("[MAP-ANSWER] panel=0x%X qno=%u opt=%d -> submit", q, qno, opt);
    *(uint32_t*)(q + ga::QUIZ_CHOSEN) = (uint32_t)opt;
    typedef void (__thiscall *FnSubmit)(void*);
    ((FnSubmit)(base + ga::RVA_QUIZ_SUBMIT))((void*)q);

    uint32_t parent = *(uint32_t*)(q + ga::QUIZ_PARENT);
    if (parent) {
        typedef void (__thiscall *FnClose)(void* pParent, void* pDialog, int flag);
        ((FnClose)(base + ga::RVA_CLOSE_DIALOG))((void*)parent, (void*)q, 0);
    }
    logline("[MAP-ANSWER] submitted, visible after close=%u", *(uint32_t*)(q + ga::QUIZ_VISIBLE));
    return true;
}

// 谁先拿到待办谁执行（UI 线程钩子或工作线程），保证同一题只提交一次。
static bool try_pending_map_answer() {
    int opt = g_pending_map_opt.exchange(-1);
    if (opt < 0) return false;
    uint32_t qno = g_pending_map_qno.load();
    if (invoke_native_map_answer(qno, opt)) {
        g_map_sent_opt.store(opt);
        push_event("{\"type\":\"map_sent\",\"qno\":" + std::to_string(qno) +
                   ",\"opt\":" + std::to_string(opt) + ",\"method\":\"native\"}\n");
        return true;
    }
    int none = -1;
    g_pending_map_opt.compare_exchange_strong(none, opt);   // 面板还没就绪，放回去下次再试
    return false;
}

static void execute_ui_thread_dismiss() {
    try_pending_map_answer();
    int opt = g_pending_native_opt.load();
    if (opt < 0) return;

    if (invoke_native_dismiss_internal(opt)) {
        g_pending_native_opt.store(-1);
        push_event("{\"type\":\"dismissed\",\"active\":0,\"opt\":" + std::to_string(opt) +
                   ",\"method\":\"frame_closedialog\"}\n");
    }
}

// ---------------- 进程内虚拟光标与输入 Hook 函数 ----------------
static BOOL WINAPI agent_cursor(LPPOINT point) {
    execute_ui_thread_dismiss();
    if (g_vclick_mode.load() && point) {
        point->x = g_vclick_x.load();
        point->y = g_vclick_y.load();
        return TRUE;
    }
    return real_cursor ? real_cursor(point) : FALSE;
}

static SHORT WINAPI agent_async(int key) {
    execute_ui_thread_dismiss();
    if (g_vclick_mode.load() && key == VK_LBUTTON) {
        return g_vclick_down.load() ? (SHORT)0x8001 : 0;
    }
    return real_async ? real_async(key) : 0;
}

static HWND WINAPI agent_active(VOID) {
    execute_ui_thread_dismiss();
    if (g_vclick_mode.load()) {
        HWND h = find_main_hwnd();
        if (h) return h;
    }
    return real_active ? real_active() : NULL;
}

static HWND WINAPI agent_foreground(VOID) {
    execute_ui_thread_dismiss();
    if (g_vclick_mode.load()) {
        HWND h = find_main_hwnd();
        if (h) return h;
    }
    return real_foreground ? real_foreground() : NULL;
}

static HWND WINAPI agent_focus(VOID) {
    execute_ui_thread_dismiss();
    if (g_vclick_mode.load()) {
        HWND h = find_main_hwnd();
        if (h) return h;
    }
    return real_focus ? real_focus() : NULL;
}

static HRESULT WINAPI agent_di_state(LPDIRECTINPUTDEVICE8A device, DWORD size, LPVOID data) {
    execute_ui_thread_dismiss();
    HRESULT hr = real_di_state ? real_di_state(device, size, data) : DIERR_NOTACQUIRED;
    if (!g_vclick_mode.load()) return hr;

    if (size == 256) {
        if (FAILED(hr) && data) {
            ZeroMemory(data, size);
            return DI_OK;
        }
    } else if (size == sizeof(DIMOUSESTATE) || size == sizeof(DIMOUSESTATE2)) {
        if (data) {
            if (FAILED(hr)) ZeroMemory(data, size);
            ((DIMOUSESTATE*)data)->rgbButtons[0] = g_vclick_down.load() ? 0x80 : 0;
            return DI_OK;
        }
    }
    return hr;
}

// ---------------- 进程内关闭弹窗核心逻辑 ----------------
static void perform_inprocess_dismiss(int opt_index) {
    g_pending_native_opt.store(opt_index);

    HWND hwnd = find_main_hwnd();
    if (hwnd) {
        PostMessageA(hwnd, WM_NULL, 0, 0);
    }

    bool closed = false;
    // 循环高频轮询等待题框激活（最多等待 3 秒，每 25ms 检查一次）
    // 一旦答题弹窗在客户端内存中就绪，立即在 25ms 内瞬间调用原生 CloseDialog 销毁
    for (int i = 0; i < 120; i++) {
        // 1. 检查是否已被渲染帧 Hook 先行执行关闭
        if (g_pending_native_opt.load() < 0) {
            closed = true;
            break;
        }

        // 2. 当前工作线程直接尝试调用原生关窗
        if (invoke_native_dismiss_internal(opt_index)) {
            g_pending_native_opt.store(-1);
            closed = true;
            push_event("{\"type\":\"dismissed\",\"active\":0,\"opt\":" + std::to_string(opt_index) +
                       ",\"method\":\"direct_closedialog\"}\n");
            break;
        }

        Sleep(25);
    }

    g_pending_native_opt.store(-1);

    if (closed) {
        logline("[DISMISS] Native CloseDialog completed successfully! (seamless, 0ms lag)");
        g_vclick_count++;
    } else {
        logline("[DISMISS] Native CloseDialog timed out after 3000ms");
        push_event("{\"type\":\"dismiss_failed\",\"active\":1,\"opt\":" + std::to_string(opt_index) + "}\n");
    }
}


static DWORD WINAPI dismiss_worker(LPVOID param) {
    int opt = (int)(intptr_t)param;
    perform_inprocess_dismiss(opt);
    return 0;
}

extern "C" __declspec(dllexport) int DismissQuiz(int opt) {
    if (opt < 0 || opt > 3) opt = 0;
    HANDLE th = CreateThread(NULL, 0, dismiss_worker, (LPVOID)(intptr_t)opt, 0, NULL);
    if (th) {
        WaitForSingleObject(th, 2000);
        CloseHandle(th);
        return 0;
    }
    return -1;
}

// ---------------- 答题发送（纯网络发包） ----------------
extern "C" __declspec(dllexport) int SendQuizAnswer(uint32_t qno, uint8_t opt) {
    if (!g_tb.valid) return -1;
    SOCKET s = g_main_sock.load();
    if (s == INVALID_SOCKET) { logline("[SEND-ANSWER] no main sock"); return -2; }
    std::vector<uint8_t> wire = qp::build_answer(g_tb, qno, opt);

    int (WINAPI *p_send_fn)(SOCKET, const char*, int, int) =
        (int (WINAPI *)(SOCKET, const char*, int, int))GetProcAddress(GetModuleHandleA("ws2_32.dll"), "send");
    if (!p_send_fn) return -3;

    int r = SOCKET_ERROR;
    for (int attempt = 0; attempt < 50; attempt++) {
        r = p_send_fn(s, (const char*)wire.data(), (int)wire.size(), 0);
        if (r != SOCKET_ERROR) break;
        int err = WSAGetLastError();
        if (err != WSAEWOULDBLOCK && err != WSAEINPROGRESS) {
            logline("[SEND-ANSWER] send err=%d sock=%llu", err, (unsigned long long)s);
            push_event("{\"type\":\"sendfail\",\"qno\":" + std::to_string(qno) +
                       ",\"opt\":" + std::to_string(opt) + ",\"err\":" + std::to_string(err) + "}\n");
            return -4;
        }
        Sleep(2);
    }
    if (r == SOCKET_ERROR) {
        push_event("{\"type\":\"sendfail\",\"qno\":" + std::to_string(qno) +
                   ",\"opt\":" + std::to_string(opt) + ",\"err\":\"wouldblock_timeout\"}\n");
        return -5;
    }
    logline("[SEND-ANSWER] qno=%u opt=%u ret=%d sock=%llu", qno, opt, r, (unsigned long long)s);
    push_event("{\"type\":\"sent\",\"qno\":" + std::to_string(qno) +
               ",\"opt\":" + std::to_string(opt) + "}\n");

    // 发送答案后，异步触发进程内点击消除弹窗
    HANDLE th = CreateThread(NULL, 0, dismiss_worker, (LPVOID)(intptr_t)opt, 0, NULL);
    if (th) CloseHandle(th);

    return r;
}

// boss 题作答工作线程：最多等 3 秒让面板就绪并走原生提交；还不行就直接发 0x1F05 包（面板会留在屏幕上）。
static DWORD WINAPI map_answer_worker(LPVOID) {
    HWND hwnd = find_main_hwnd();
    if (hwnd) PostMessageA(hwnd, WM_NULL, 0, 0);
    for (int i = 0; i < 120; i++) {
        if (g_pending_map_opt.load() < 0) return 0;     // 已被 UI 线程执行
        if (try_pending_map_answer()) return 0;
        Sleep(25);
    }
    int opt = g_pending_map_opt.exchange(-1);
    if (opt < 0) return 0;
    uint32_t qno = g_pending_map_qno.load();
    SOCKET s = g_main_sock.load();
    if (!g_tb.valid || s == INVALID_SOCKET) {
        logline("[MAP-ANSWER] panel never ready and no socket, qno=%u not answered", qno);
        push_event("{\"type\":\"map_fail\",\"qno\":" + std::to_string(qno) + ",\"err\":\"no_panel_no_sock\"}\n");
        return 0;
    }
    std::vector<uint8_t> wire = qp::build_map_answer(g_tb, qno, (uint8_t)opt);
    int (WINAPI *p_send_fn)(SOCKET, const char*, int, int) =
        (int (WINAPI *)(SOCKET, const char*, int, int))GetProcAddress(GetModuleHandleA("ws2_32.dll"), "send");
    int r = p_send_fn ? p_send_fn(s, (const char*)wire.data(), (int)wire.size(), 0) : SOCKET_ERROR;
    logline("[MAP-ANSWER] panel not ready after 3 s, raw 0x1F05 qno=%u opt=%d ret=%d", qno, opt, r);
    if (r == SOCKET_ERROR) {
        push_event("{\"type\":\"map_fail\",\"qno\":" + std::to_string(qno) + ",\"err\":\"send\"}\n");
        return 0;
    }
    g_map_sent_opt.store(opt);
    push_event("{\"type\":\"map_sent\",\"qno\":" + std::to_string(qno) +
               ",\"opt\":" + std::to_string(opt) + ",\"method\":\"raw\"}\n");
    return 0;
}

static void answer_map_quiz(uint32_t qno, int opt) {
    if (opt < 0 || opt > 3) return;
    if (g_map_qno.load() != qno) {
        logline("[MAP-ANSWER] ignored: qno=%u is not the open boss quiz (%u)", qno, g_map_qno.load());
        return;
    }
    g_pending_map_qno.store(qno);
    g_pending_map_opt.store(opt);
    HANDLE th = CreateThread(NULL, 0, map_answer_worker, NULL, 0, NULL);
    if (th) CloseHandle(th);
}

// ---------------- 游戏角色名称与账号获取 (MSVC std::string 内存结构解析) ----------------
static std::string read_msvc_string(uint32_t addr) {
    if (!addr || IsBadReadPtr((void*)addr, 24)) return "";
    uint32_t str_size = *(uint32_t*)(addr + 16);
    uint32_t str_res  = *(uint32_t*)(addr + 20);
    if (str_size == 0 || str_size > 64) return "";

    const char* str_ptr = nullptr;
    if (str_res < 16) {
        str_ptr = (const char*)addr;
    } else {
        str_ptr = *(const char**)addr;
    }
    if (!str_ptr || IsBadReadPtr(str_ptr, str_size)) return "";
    return std::string(str_ptr, str_size);
}

static std::string get_character_name() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return "";
    uint32_t p0 = *(uint32_t*)(base + ga::RVA_PLAYER0);
    if (!p0 || IsBadReadPtr((void*)p0, 4)) return "";

    // 优先读取游戏内真实角色名 (+0xC84，例如“伏地魔1”)
    std::string role = read_msvc_string(p0 + 0xC84);
    if (!role.empty()) return role;

    // 备用读取登录账号名 (+0xB7C，例如“qooqp6”)
    return read_msvc_string(p0 + 0xB7C);
}

static std::string get_account_name() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return "";
    uint32_t p0 = *(uint32_t*)(base + ga::RVA_PLAYER0);
    if (!p0 || IsBadReadPtr((void*)p0, 4)) return "";
    return read_msvc_string(p0 + 0xB7C);
}

// ---------------- 战斗与收益监控数据读取 ----------------
static std::atomic<int> g_battle_monsters{0};
static std::atomic<int> g_last_battle_monsters{0};
static std::atomic<int> g_battle_min_hp{0};
static std::atomic<int> g_battle_max_hp{0};
static std::atomic<int> g_last_battle_min_hp{0};
static std::atomic<int> g_last_battle_max_hp{0};
static std::atomic<int> g_in_battle{0};
static std::atomic<int> g_battle_index{0};

// 本场最低血量（10-09 加的，从没发布过）：要调游戏函数 0x10070 / 0x100D0 并读 0x5166DC，
// 这三个都是 2.98 的地址，2.100 里在哪还没核实，调错会让游戏崩溃，所以默认关掉，返回 0。
#ifndef QB_ENABLE_MIN_HP
#define QB_ENABLE_MIN_HP 0
#endif

static int get_character_hp() {
#if QB_ENABLE_MIN_HP
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t game_obj = *(uint32_t*)(base + 0x5166DC);
    if (!game_obj || IsBadReadPtr((void*)game_obj, 0x20)) return 0;
    typedef int (__thiscall *fn_get_hp_t)(void*);
    fn_get_hp_t fn = (fn_get_hp_t)(base + 0x10070);
    return fn((void*)game_obj);
#else
    return 0;
#endif
}

static int get_character_hp_max() {
#if QB_ENABLE_MIN_HP
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t game_obj = *(uint32_t*)(base + 0x5166DC);
    if (!game_obj || IsBadReadPtr((void*)game_obj, 0x20)) return 0;
    typedef int (__thiscall *fn_get_hp_max_t)(void*);
    fn_get_hp_max_t fn = (fn_get_hp_max_t)(base + 0x100D0);
    return fn((void*)game_obj);
#else
    return 0;
#endif
}

static int scan_enemy_count() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t battle = *(uint32_t*)(base + ga::RVA_BATTLE);
    if (!battle || IsBadReadPtr((void*)battle, 0x8600)) return 0;

    int cnt = 0;
    for (int s = 0; s < 10; s++) {
        uint32_t kind = *(uint32_t*)(battle + 0x1DC0 + s * 0x510);
        if (kind != 0 && kind != 0xFFFFFFFF) {
            cnt++;
        }
    }
    return cnt;
}

static DWORD WINAPI battle_monitor_thread(LPVOID) {
    while (!g_stop.load()) {
        int cnt = scan_enemy_count();
        if (cnt > 0) {
            int hp = get_character_hp();
            int max_hp = get_character_hp_max();
            if (!g_in_battle.load()) {
                g_in_battle.store(1);
                g_battle_index++;
                g_battle_min_hp.store(hp > 0 ? hp : 999999);
                g_battle_max_hp.store(max_hp);
            } else {
                if (hp > 0 && hp < g_battle_min_hp.load()) {
                    g_battle_min_hp.store(hp);
                }
                if (max_hp > g_battle_max_hp.load()) {
                    g_battle_max_hp.store(max_hp);
                }
            }
            g_battle_monsters.store(cnt);
            g_last_battle_monsters.store(cnt);
        } else {
            if (g_in_battle.load()) {
                g_in_battle.store(0);
                g_last_battle_min_hp.store(g_battle_min_hp.load());
                g_last_battle_max_hp.store(g_battle_max_hp.load());
            }
            g_battle_monsters.store(0);
        }
        Sleep(100);
    }
    return 0;
}

static int get_character_level() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t p0 = *(uint32_t*)(base + ga::RVA_SESSION);
    if (!p0 || IsBadReadPtr((void*)p0, 0x1000)) return 0;
    return *(int32_t*)(p0 + 0x0EAC);
}

static int get_current_map_id() {
    uint8_t* base = (uint8_t*)GetModuleHandleA(NULL);
    if (!base) return 0;
    uint32_t p1 = *(uint32_t*)(base + ga::RVA_PLAYER_PTR);
    if (!p1 || IsBadReadPtr((void*)p1, 8)) return 0;
    uint32_t p2 = *(uint32_t*)(p1 + 4);
    if (!p2 || IsBadReadPtr((void*)p2, 0x300)) return 0;
    return *(int32_t*)(p2 + 0x2E4);
}

static void log_battle_profit_csv(const char* cname_u8, const char* aname_u8,
                                  int map_id, const char* map_name,
                                  int level, int monsters,
                                  int32_t char_exp, int32_t pet_exp) {
    CSLock lk(g_logmtx);
    char path[MAX_PATH];
    _snprintf_s(path, sizeof path, _TRUNCATE, "%s\\battle_profit.csv", g_logdir.c_str());

    bool is_new = false;
    DWORD attr = GetFileAttributesA(path);
    if (attr == INVALID_FILE_ATTRIBUTES) {
        is_new = true;
    }

    HANDLE f = CreateFileA(path, FILE_APPEND_DATA,
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

    char line[1024];
    SYSTEMTIME t; GetLocalTime(&t);
    int n = _snprintf_s(line, sizeof line, _TRUNCATE,
            "%04u-%02u-%02u %02u:%02u:%02u,%u,%s,%s,%d,%s,%d,%d,%d,%d\r\n",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond,
            GetCurrentProcessId(),
            cname_u8 ? cname_u8 : "",
            aname_u8 ? aname_u8 : "",
            map_id,
            map_name ? map_name : "",
            level,
            monsters,
            char_exp,
            pet_exp);
    if (n > 0) {
        DWORD wrote = 0;
        WriteFile(f, line, (DWORD)n, &wrote, nullptr);
    }
    CloseHandle(f);
}

#if QB_ENABLE_MIN_HP
static void log_battle_min_hp(const char* cname_u8, const char* aname_u8,
                              int map_id, const char* map_name,
                              int min_hp, int max_hp, int monsters) {
    CSLock lk(g_logmtx);
    char path_log[MAX_PATH];
    char path_csv[MAX_PATH];
    _snprintf_s(path_log, sizeof path_log, _TRUNCATE, "%s\\battle_min_hp.log", g_logdir.c_str());
    _snprintf_s(path_csv, sizeof path_csv, _TRUNCATE, "%s\\battle_min_hp.csv", g_logdir.c_str());

    SYSTEMTIME t; GetLocalTime(&t);
    double rate = (max_hp > 0) ? (min_hp * 100.0 / max_hp) : 0.0;
    int bidx = g_battle_index.load();

    // 1. 写独立文本日志 battle_min_hp.log
    HANDLE f1 = CreateFileA(path_log, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f1 != INVALID_HANDLE_VALUE) {
        if (GetFileSize(f1, NULL) == 0) {
            const unsigned char bom[] = {0xEF, 0xBB, 0xBF};
            DWORD wrote = 0;
            WriteFile(f1, bom, sizeof(bom), &wrote, nullptr);
            const char header[] = "=====================================================================================\r\n  《什么什么大冒险2.0》多开战斗每场人物最低 HP 监测独立日志\r\n=====================================================================================\r\n\r\n";
            WriteFile(f1, header, (DWORD)strlen(header), &wrote, nullptr);
        }
        char line[512];
        int n = _snprintf_s(line, sizeof line, _TRUNCATE,
            "[%04u-%02u-%02u %02u:%02u:%02u] [PID %5u | %-6s] 第 %3d 场结束 | ★最低HP: %5d / %5d (%5.1f%%) | 怪物数: %d | 地图: %s\r\n",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond,
            GetCurrentProcessId(), cname_u8 ? cname_u8 : "", bidx,
            min_hp, max_hp, rate, monsters, map_name ? map_name : "");
        if (n > 0) {
            DWORD wrote = 0;
            WriteFile(f1, line, (DWORD)n, &wrote, nullptr);
        }
        CloseHandle(f1);
    }

    // 2. 写独立表格 battle_min_hp.csv
    HANDLE f2 = CreateFileA(path_csv, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f2 != INVALID_HANDLE_VALUE) {
        if (GetFileSize(f2, NULL) == 0) {
            const unsigned char bom[] = {0xEF, 0xBB, 0xBF};
            DWORD wrote = 0;
            WriteFile(f2, bom, sizeof(bom), &wrote, nullptr);
            const char header[] = "时间,PID,角色名,账号,地图ID,地图名,战斗场次,本场最低HP,满血上限,最低HP比例(%),怪物数\r\n";
            WriteFile(f2, header, (DWORD)strlen(header), &wrote, nullptr);
        }
        char line[512];
        int n = _snprintf_s(line, sizeof line, _TRUNCATE,
            "%04u-%02u-%02u %02u:%02u:%02u,%u,%s,%s,%d,%s,%d,%d,%d,%.1f,%d\r\n",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond,
            GetCurrentProcessId(), cname_u8 ? cname_u8 : "", aname_u8 ? aname_u8 : "",
            map_id, map_name ? map_name : "", bidx, min_hp, max_hp, rate, monsters);
        if (n > 0) {
            DWORD wrote = 0;
            WriteFile(f2, line, (DWORD)n, &wrote, nullptr);
        }
        CloseHandle(f2);
    }
}
#endif

// boss 题有结果了：答对时报出题号和下标，控制器据此记表（用户手动答的也一样，下标从面板 +0x1AC 读）。
// 答错时服务器说什么还没见过，带 错/失败/不正确 字样的提示先当作答错报出去。
static void report_map_result(const std::string& utf8) {
    uint32_t qno = g_map_qno.load();
    if (!qno) return;
    bool pass = utf8.find(u8"测试通过") != std::string::npos;
    bool fail = !pass && (utf8.find(u8"错") != std::string::npos || utf8.find(u8"失败") != std::string::npos ||
                          utf8.find(u8"不正确") != std::string::npos);
    if (!pass && !fail) return;
    int opt = g_map_sent_opt.load();
    const char* who = "bot";
    if (opt < 0) {
        who = "manual";
        uint32_t q = map_panel();
        // 手动点选时面板在服务器回话之前就关了；面板还开着说明这条提示不是 boss 题的（比如战斗题通过）
        if (q && *(uint32_t*)(q + ga::QUIZ_VISIBLE) != 0) return;
        if (q && *(uint32_t*)(q + ga::QUIZ_QNO) == qno) opt = *(int32_t*)(q + ga::QUIZ_CHOSEN);
    }
    logline("[MAP-RESULT] qno=%u opt=%d by=%s pass=%d text=%s", qno, opt, who, pass ? 1 : 0, utf8.c_str());
    push_event("{\"type\":\"map_result\",\"qno\":" + std::to_string(qno) + ",\"opt\":" + std::to_string(opt) +
               ",\"by\":\"" + who + "\",\"pass\":" + (pass ? "true" : "false") +
               ",\"text\":\"" + jesc(utf8) + "\"}\n");
    if (pass) g_map_qno.store(0);
    g_map_sent_opt.store(-1);
}

// ---------------- 协议帧处理（旁路嗅探） ----------------
static void handle_frame(SOCKET s, uint16_t op, uint16_t inv,
                         const uint8_t* body, size_t len) {
    g_frames++;

    // 战斗结算（0x472A）：前4字节为角色实体ID(dwCharID)，+4为角色经验，+20为宠物经验
    if (op == 0x472A && len >= 8) {
        std::vector<uint8_t> plain(len);
        qp::decode_s2c(g_tb, op, inv, body, len, plain.data());
        uint32_t char_id = (uint32_t)(plain[0] | (plain[1] << 8) |
                                      (plain[2] << 16) | ((uint32_t)plain[3] << 24));
        int32_t char_exp = (int32_t)(plain[4] | (plain[5] << 8) |
                                      (plain[6] << 16) | ((uint32_t)plain[7] << 24));
        int32_t pet_exp = 0;
        if (len >= 24) {
            pet_exp = (int32_t)(plain[20] | (plain[21] << 8) |
                                (plain[22] << 16) | ((uint32_t)plain[23] << 24));
            if (pet_exp < 0 || pet_exp > 10000000) pet_exp = 0;
        }

        int monsters = g_last_battle_monsters.load();
        if (monsters <= 0) {
            monsters = scan_enemy_count();
        }
        g_last_battle_monsters.store(0);

        int level = get_character_level();
        int map_id = get_current_map_id();
        const char* map_name = get_map_name(map_id);

        std::string cname_gbk = get_character_name();
        std::string aname_gbk = get_account_name();
        std::string cname_u8 = gbk_to_utf8(cname_gbk);
        std::string aname_u8 = gbk_to_utf8(aname_gbk);

        int min_hp = g_last_battle_min_hp.load();
        int max_hp = g_last_battle_max_hp.load();
        if (min_hp <= 0) {
            min_hp = get_character_hp();
            max_hp = get_character_hp_max();
        }

        logline("[BATTLE] 角色=%s 等级=%d 地图=%d(%s) 怪物数=%d 角色经验=%d 宠物经验=%d 本场最低HP=%d/%d",
                cname_u8.c_str(), level, map_id, map_name, monsters, char_exp, pet_exp, min_hp, max_hp);
        logline("[SETTLE] char_id=%u name=%s account=%s exp=%d pet_exp=%d len=%zu",
                char_id, cname_gbk.c_str(), aname_gbk.c_str(), char_exp, pet_exp, len);

        log_battle_profit_csv(cname_u8.c_str(), aname_u8.c_str(),
                              map_id, map_name, level, monsters, char_exp, pet_exp);
#if QB_ENABLE_MIN_HP
        log_battle_min_hp(cname_u8.c_str(), aname_u8.c_str(),
                          map_id, map_name, min_hp, max_hp, monsters);
#endif

        push_event("{\"type\":\"settle\",\"char_id\":" + std::to_string(char_id) +
                   ",\"name\":\"" + jesc(cname_u8) + "\"" +
                   ",\"account\":\"" + jesc(aname_u8) + "\"" +
                   ",\"map_id\":" + std::to_string(map_id) +
                   ",\"map_name\":\"" + jesc(map_name) + "\"" +
                   ",\"level\":" + std::to_string(level) +
                   ",\"monsters\":" + std::to_string(monsters) +
                   ",\"min_hp\":" + std::to_string(min_hp) +
                   ",\"max_hp\":" + std::to_string(max_hp) +
                   ",\"exp\":" + std::to_string(char_exp) +
                   ",\"pet_exp\":" + std::to_string(pet_exp) + "}\n");
    }



    // 答题下发（0x46F4）
    if (op == qp::OP_QUESTION) {
        std::vector<uint8_t> plain(len);
        qp::decode_s2c(g_tb, op, inv, body, len, plain.data());
        Question q = qp::parse_question(plain.data(), plain.size());
        g_main_sock.store(s);
        g_questions++;
        if (q.parse_ok) {
            std::string cname = get_character_name();
            std::string aname = get_account_name();
            std::string ev = "{\"type\":\"question\",\"sock\":" + std::to_string((uint64_t)s) +
                ",\"name\":\"" + jesc(gbk_to_utf8(cname)) + "\"" +
                ",\"account\":\"" + jesc(gbk_to_utf8(aname)) + "\"" +
                ",\"qno\":" + std::to_string(q.qno) +
                ",\"field_a\":" + std::to_string(q.field_a) +
                ",\"stem\":\"" + jesc(gbk_to_utf8(q.stem)) + "\",\"options\":[";
            for (size_t i = 0; i < q.options.size(); i++) {
                if (i) ev += ",";
                ev += "\"" + jesc(gbk_to_utf8(q.options[i])) + "\"";
            }
            ev += "]}";
            logline("[QUESTION] %s", ev.c_str());
            push_event(std::move(ev) + "\n");
        } else {
            logline("[QUESTION] parse FAIL qno=%u err=%s plainlen=%u",
                    q.qno, q.err.c_str(), (unsigned)len);
            push_event("{\"type\":\"question_bad\",\"qno\":" + std::to_string(q.qno) +
                       ",\"err\":\"" + q.err + "\"}\n");
        }
    } else if (op == qp::OP_MAP_QUESTION) {
        // boss「开打」时的题（0x46F5）：和 0x46F4 一样推给控制器，多带 kind=map 和 char_id
        std::vector<uint8_t> plain(len);
        qp::decode_s2c(g_tb, op, inv, body, len, plain.data());
        uint32_t char_id = 0;
        Question q = qp::parse_map_question(plain.data(), plain.size(), &char_id);
        g_main_sock.store(s);
        g_questions++;
        if (q.parse_ok) {
            g_map_qno.store(q.qno);
            g_map_sent_opt.store(-1);
            std::string ev = "{\"type\":\"question\",\"kind\":\"map\",\"sock\":" + std::to_string((uint64_t)s) +
                ",\"name\":\"" + jesc(gbk_to_utf8(get_character_name())) + "\"" +
                ",\"account\":\"" + jesc(gbk_to_utf8(get_account_name())) + "\"" +
                ",\"char_id\":" + std::to_string(char_id) +
                ",\"qno\":" + std::to_string(q.qno) +
                ",\"stem\":\"" + jesc(gbk_to_utf8(q.stem)) + "\",\"options\":[";
            for (size_t i = 0; i < q.options.size(); i++) {
                if (i) ev += ",";
                ev += "\"" + jesc(gbk_to_utf8(q.options[i])) + "\"";
            }
            ev += "]}";
            logline("[MAP-QUESTION] %s", ev.c_str());
            push_event(std::move(ev) + "\n");
        } else {
            logline("[MAP-QUESTION] parse FAIL qno=%u err=%s plainlen=%u", q.qno, q.err.c_str(), (unsigned)len);
            push_event("{\"type\":\"question_bad\",\"kind\":\"map\",\"qno\":" + std::to_string(q.qno) +
                       ",\"err\":\"" + q.err + "\"}\n");
        }
    } else if (op == qp::OP_SYSPROMPT) {
        std::vector<uint8_t> plain(len);
        qp::decode_s2c(g_tb, op, inv, body, len, plain.data());
        std::string gbk;
        if (qp::parse_sysprompt(plain.data(), plain.size(), gbk)) {
            std::string utf8 = gbk_to_utf8(gbk);
            push_event("{\"type\":\"sys\",\"op\":18263,\"text\":\"" + jesc(utf8) + "\"}\n");
            logline("[SYS] %s", utf8.c_str());
            report_map_result(utf8);
        }
    } else if (op == qp::OP_CURRENCY) {
        std::vector<uint8_t> plain(len);
        qp::decode_s2c(g_tb, op, inv, body, len, plain.data());
        uint32_t a = 0, b = 0;
        if (len >= 8) { memcpy(&a, plain.data(), 4); memcpy(&b, plain.data() + 4, 4); }
        push_event("{\"type\":\"currency\",\"a\":" + std::to_string(a) +
                   ",\"b\":" + std::to_string(b) + "}\n");
    }
}

// ---------------- 原网接口 ----------------
static int (WINAPI *p_recv)(SOCKET, char*, int, int) = nullptr;
static int (WINAPI *p_send)(SOCKET, const char*, int, int) = nullptr;
static int (WINAPI *p_WSASend)(SOCKET, LPWSABUF, DWORD, LPDWORD, DWORD,
                               LPWSAOVERLAPPED, LPWSAOVERLAPPED_COMPLETION_ROUTINE) = nullptr;
static int (WINAPI *p_connect)(SOCKET, const struct sockaddr*, int) = nullptr;
static int (WINAPI *p_closesocket)(SOCKET) = nullptr;

static void on_recv_data_bypass(SOCKET s, const uint8_t* data, int len) {
    if (len <= 0 || !g_tb.valid) return;
    g_recv_bytes += (DWORD)len;
    CSLock lk(g_sockmtx);
    auto& buf = g_rbuf[s].data;
    buf.insert(buf.end(), data, data + len);
    if (buf.size() > (4u + (size_t)qp::MAX_BODY) * 8) { buf.clear(); return; }
    bool bad = false;
    size_t consumed = qp::parse_stream(buf, buf.size(),
        [&](uint16_t op, uint16_t inv, size_t off, size_t blen) {
            handle_frame(s, op, inv, buf.data() + off, blen);
        }, bad);
    if (bad) { buf.clear(); return; }
    buf.erase(buf.begin(), buf.begin() + (long)consumed);
}

// ---------------- hook_recv 100% 原始透传旁路 ----------------
static int WINAPI hook_recv(SOCKET s, char* buf, int len, int flags) {
    int r0 = p_recv(s, buf, len, flags);
    if (r0 > 0) {
        on_recv_data_bypass(s, (const uint8_t*)buf, r0);
    } else if (r0 == SOCKET_ERROR && WSAGetLastError() != WSAEWOULDBLOCK) {
        logline("[NET-E] sock=%llu r=%d err=%d", (unsigned long long)s, r0, WSAGetLastError());
    }
    return r0;
}

static bool looks_like_game_frame(const char* buf, int len) {
    if (len < 4) return false;
    uint16_t inv, op;
    memcpy(&inv, buf, 2); memcpy(&op, buf + 2, 2);
    uint16_t blen = qp::body_len(inv);
    return blen <= qp::MAX_BODY;
}

static int WINAPI hook_send(SOCKET s, const char* buf, int len, int flags) {
    if (looks_like_game_frame(buf, len)) {
        uint16_t op; memcpy(&op, buf + 2, 2);
        if (op == 0xF001 || op == 0x47C0 || op == 0x4101) {
            SOCKET old = g_main_sock.load();
            if (old != s) {
                g_main_sock.store(s);
                logline("[MAIN-SOCK] identified game world sock %llu (send op=%04X)",
                        (unsigned long long)s, op);
            }
        }
    }
    return p_send(s, buf, len, flags);
}

static int WINAPI hook_WSASend(SOCKET s, LPWSABUF bufs, DWORD cnt, LPDWORD sent,
                               DWORD flags, LPWSAOVERLAPPED ov, LPWSAOVERLAPPED_COMPLETION_ROUTINE cr) {
    if (cnt >= 1 && bufs && bufs[0].len >= 4) {
        if (looks_like_game_frame(bufs[0].buf, (int)bufs[0].len)) {
            uint16_t op; memcpy(&op, bufs[0].buf + 2, 2);
            if (op == 0xF001 || op == 0x47C0 || op == 0x4101) {
                SOCKET old = g_main_sock.load();
                if (old != s) {
                    g_main_sock.store(s);
                    logline("[MAIN-SOCK] identified game world sock %llu (WSASend op=%04X)",
                            (unsigned long long)s, op);
                }
            }
        }
    }
    return p_WSASend(s, bufs, cnt, sent, flags, ov, cr);
}

static int WINAPI hook_connect(SOCKET s, const struct sockaddr* name, int namelen) {
    if (name && namelen >= (int)sizeof(sockaddr_in)) {
        auto* sin = (const sockaddr_in*)name;
        if (sin->sin_family == AF_INET) {
            uint16_t port = ntohs(sin->sin_port);
            logline("[CONNECT] sock %llu -> port %u", (unsigned long long)s, port);
            if (port == 8484) {
                g_main_sock.store(s);
            }
        }
    }
    return p_connect(s, name, namelen);
}

static int WINAPI hook_closesocket(SOCKET s) {
    {
        CSLock lk(g_sockmtx);
        g_rbuf.erase(s);
    }
    SOCKET cur = g_main_sock.load();
    if (cur == s) {
        g_main_sock.store(INVALID_SOCKET);
        logline("[CLOSE] main sock %llu closed", (unsigned long long)s);
    }
    return p_closesocket(s);
}

// ---------------- IAT Patch ----------------
struct IatRestore { FARPROC* entry = nullptr; FARPROC orig = nullptr; };
static std::vector<IatRestore> g_restore;

static bool patch_iat_by_addr(const char* func_name_ord, FARPROC target,
                              void* hook, void** orig) {
    uint8_t* base = (uint8_t*)GetModuleHandleA(nullptr);
    auto* dos = (IMAGE_DOS_HEADER*)base;
    auto* nt  = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    auto* dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir->VirtualAddress) return false;
    auto* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir->VirtualAddress);
    for (; imp->Name; imp++) {
        auto* thunk = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; thunk->u1.Function; thunk++) {
            if ((FARPROC)thunk->u1.Function != target) continue;
            FARPROC* entry = (FARPROC*)&thunk->u1.Function;
            DWORD oldp;
            if (!VirtualProtect(entry, sizeof(FARPROC), PAGE_READWRITE, &oldp)) continue;
            FARPROC original = *entry;
            *entry = (FARPROC)hook;
            VirtualProtect(entry, sizeof(FARPROC), oldp, &oldp);
            *(FARPROC*)orig = original;
            g_restore.push_back({entry, original});
            return true;
        }
    }
    return false;
}

static bool hook_ws2(const char* fn, void* hookfn, void** origp) {
    HMODULE w2 = GetModuleHandleA("ws2_32.dll");
    if (!w2) return false;
    FARPROC target = nullptr;
    if (fn[0] == '#') target = GetProcAddress(w2, (LPCSTR)(intptr_t)atoi(fn + 1));
    else              target = GetProcAddress(w2, fn);
    if (!target) return false;
    return patch_iat_by_addr(fn, target, hookfn, origp);
}

// ---------------- 管道服务线程 ----------------
static DWORD WINAPI pipe_thread(LPVOID) {
    char name[64];
    _snprintf_s(name, sizeof name, _TRUNCATE, "\\\\.\\pipe\\quizbot_v2_%u", GetCurrentProcessId());
    while (!g_stop.load()) {
        HANDLE p = CreateNamedPipeA(name,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES, 8192, 8192, 0, nullptr);
        if (p == INVALID_HANDLE_VALUE) {
            DWORD err = GetLastError();
            logline("[PIPE] CreateNamedPipeA failed err=%u", err);
            Sleep(500);
            continue;
        }
        if (!ConnectNamedPipe(p, nullptr) && GetLastError() != ERROR_PIPE_CONNECTED) {
            CloseHandle(p); Sleep(500); continue;
        }
        logline("[PIPE] controller connected");
        {
            CSLock lk(g_connmtx);
            g_pipe = p;
        }

        std::string cname = get_character_name();
        std::string aname = get_account_name();
        push_event("{\"type\":\"init\",\"pid\":" + std::to_string(GetCurrentProcessId()) +
                   ",\"name\":\"" + jesc(gbk_to_utf8(cname)) + "\"" +
                   ",\"account\":\"" + jesc(gbk_to_utf8(aname)) + "\"" +
                   ",\"codec_ok\":true,\"mode\":\"network_transparent_inprocess_click\"}\n");

        char buf[2048];
        std::string line;
        DWORD n = 0;
        while (!g_stop.load()) {
            DWORD avail = 0;
            if (!PeekNamedPipe(p, nullptr, 0, nullptr, &avail, nullptr)) break;
            if (avail == 0) {
                Sleep(10);
                continue;
            }
            DWORD to_read = avail < (DWORD)sizeof(buf) ? avail : (DWORD)sizeof(buf);
            if (!ReadFile(p, buf, to_read, &n, nullptr) || n == 0) break;
            line.append(buf, buf + n);
            size_t pos;
            while ((pos = line.find('\n')) != std::string::npos) {
                std::string cmd = line.substr(0, pos);
                line.erase(0, pos + 1);
                if (cmd.empty()) continue;
                if (cmd.find("\"ping\"") != std::string::npos) {
                    push_event("{\"type\":\"pong\",\"pid\":" +
                        std::to_string(GetCurrentProcessId()) + "}\n");
                } else if (cmd.find("\"stats\"") != std::string::npos) {
                    push_event("{\"type\":\"stats\",\"recv_bytes\":" +
                        std::to_string(g_recv_bytes.load()) + ",\"frames\":" +
                        std::to_string(g_frames.load()) + ",\"questions\":" +
                        std::to_string(g_questions.load()) + ",\"dismiss_clicks\":" +
                        std::to_string(g_vclick_count.load()) + "}\n");
                } else if (cmd.find("\"answer\"") != std::string::npos) {
                    auto grab = [&](const char* key) -> long long {
                        std::string k = key;
                        auto p1 = cmd.find(k);
                        if (p1 == std::string::npos) return -1;
                        return atoll(cmd.c_str() + p1 + k.size());
                    };
                    long long qno = grab("\"qno\":");
                    long long opt = grab("\"opt\":");
                    if (qno >= 0 && opt >= 0) {
                        if (cmd.find("\"kind\":\"map\"") != std::string::npos)
                            answer_map_quiz((uint32_t)qno, (int)opt);
                        else
                            SendQuizAnswer((uint32_t)qno, (uint8_t)opt);
                    }
                } else if (cmd.find("\"dismiss\"") != std::string::npos) {
                    auto grab = [&](const char* key) -> long long {
                        std::string k = key;
                        auto p1 = cmd.find(k);
                        if (p1 == std::string::npos) return -1;
                        return atoll(cmd.c_str() + p1 + k.size());
                    };
                    long long opt = grab("\"opt\":");
                    if (opt < 0) opt = 0;
                    HANDLE th = CreateThread(NULL, 0, dismiss_worker, (LPVOID)(intptr_t)opt, 0, NULL);
                    if (th) CloseHandle(th);
                } else if (cmd.find("\"unload\"") != std::string::npos) {
                    push_event("{\"type\":\"bye\"}\n");
                    g_stop.store(true);
                }
            }
        }
        logline("[PIPE] controller disconnected");
        {
            CSLock lk(g_connmtx);
            g_pipe = INVALID_HANDLE_VALUE;
        }
        DisconnectNamedPipe(p);
        CloseHandle(p);
    }
    return 0;
}

// ---------------- MinHook 初始化后台线程 ----------------
static DWORD WINAPI hook_init_thread(LPVOID) {
    if (MH_Initialize() != MH_OK) {
        logline("[HOOK-INIT] MH_Initialize failed");
        return 1;
    }

    // 1. Hook user32 输入与窗口函数
    HMODULE u32 = GetModuleHandleA("user32.dll");
    if (u32) {
        MH_CreateHook((LPVOID)GetProcAddress(u32, "GetCursorPos"), (LPVOID)agent_cursor, (LPVOID*)&real_cursor);
        MH_CreateHook((LPVOID)GetProcAddress(u32, "GetAsyncKeyState"), (LPVOID)agent_async, (LPVOID*)&real_async);
        MH_CreateHook((LPVOID)GetProcAddress(u32, "GetActiveWindow"), (LPVOID)agent_active, (LPVOID*)&real_active);
        MH_CreateHook((LPVOID)GetProcAddress(u32, "GetForegroundWindow"), (LPVOID)agent_foreground, (LPVOID*)&real_foreground);
        MH_CreateHook((LPVOID)GetProcAddress(u32, "GetFocus"), (LPVOID)agent_focus, (LPVOID*)&real_focus);
    }

    // 2. Hook DirectInput8 GetDeviceState
    // 等待 dinput8.dll 加载 (最长等待 10 秒)
    HMODULE dinput = nullptr;
    for (int retry = 0; retry < 100; retry++) {
        dinput = GetModuleHandleA("dinput8.dll");
        if (dinput) break;
        Sleep(100);
    }

    if (dinput) {
        auto make_di = (HRESULT (WINAPI *)(HINSTANCE, DWORD, REFIID, LPVOID*, LPUNKNOWN))
            GetProcAddress(dinput, "DirectInput8Create");
        const GUID iid_di8a = {0xBF798030, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
        const GUID guid_keyboard = {0x6F1D2B61, 0xD5A0, 0x11CF, {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}};

        LPDIRECTINPUT8A di = NULL;
        LPDIRECTINPUTDEVICE8A keyboard = NULL;
        if (make_di && SUCCEEDED(make_di(GetModuleHandleA(NULL), DIRECTINPUT_VERSION, iid_di8a, (LPVOID*)&di, NULL))) {
            if (SUCCEEDED(di->CreateDevice(guid_keyboard, &keyboard, NULL))) {
                LPVOID state_method = (*(void***)keyboard)[9];
                if (MH_CreateHook(state_method, (LPVOID)agent_di_state, (LPVOID*)&real_di_state) == MH_OK) {
                    logline("[HOOK-INIT] DirectInput GetDeviceState hooked successfully!");
                }
                keyboard->Release();
            }
            di->Release();
        }
    } else {
        logline("[HOOK-INIT] dinput8.dll not loaded, will rely on user32 hooks");
    }

    MH_EnableHook(MH_ALL_HOOKS);
    logline("[HOOK-INIT] All MinHook hooks enabled.");
    return 0;
}

// ---------------- 游戏内存读取解码表 ----------------
static bool rpm_self(uintptr_t addr, void* out, size_t n) {
    SIZE_T got = 0;
    HANDLE self = GetCurrentProcess();
    if (!ReadProcessMemory(self, (LPCVOID)addr, out, n, &got)) return false;
    return got == n;
}

static bool load_codec() {
    uintptr_t base = (uintptr_t)GetModuleHandleA(nullptr);
    uintptr_t enc_ptrs = base + ga::RVA_CODEC_ENC;
    uintptr_t dec_ptrs = base + ga::RVA_CODEC_DEC;
    for (int i = 0; i < 10; i++) {
        uintptr_t ep = 0, dp = 0;
        if (!rpm_self(enc_ptrs + i * 4, &ep, 4) || !rpm_self(dec_ptrs + i * 4, &dp, 4))
            return false;
        if (ep < 0x10000 || dp < 0x10000) return false;
        if (!rpm_self(ep, g_tb.enc[i], 256)) return false;
        if (!rpm_self(dp, g_tb.dec[i], 256)) return false;
    }
    if (!g_tb.check_bijection()) return false;
    g_tb.valid = true;
    return true;
}

// ---------------- DllMain ----------------
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = inst;
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_logmtx);
        InitializeCriticalSection(&g_sockmtx);
        InitializeCriticalSection(&g_wmtx);
        InitializeCriticalSection(&g_connmtx);
        g_wake_event = CreateEventA(nullptr, FALSE, FALSE, nullptr);

        char dllpath[MAX_PATH];
        GetModuleFileNameA(inst, dllpath, sizeof dllpath);
        char* slash = strrchr(dllpath, '\\');
        if (slash) {
            *slash = 0;
            char* prev_slash = strrchr(dllpath, '\\');
            if (prev_slash && _stricmp(prev_slash + 1, "build") == 0) {
                *prev_slash = 0;
            }
            g_logdir = std::string(dllpath) + "\\logs";
        } else {
            g_logdir = ".\\logs";
        }
        CreateDirectoryA(g_logdir.c_str(), nullptr);

        logline("[INIT] =========================================");
        logline("[INIT] quizbot_hook.dll (Transparent + In-Process Dismiss) loaded in PID %u", GetCurrentProcessId());

        // 读协议编解码表
        if (load_codec()) {
            logline("[INIT] Codec tables loaded successfully (bijection valid)");
        } else {
            logline("[INIT] WARNING: Codec tables load failed");
        }

        // IAT Hook ws2_32
        bool h1 = hook_ws2("#16", (void*)hook_recv, (void**)&p_recv);
        bool h2 = hook_ws2("#19", (void*)hook_send, (void**)&p_send);
        bool h3 = hook_ws2("WSASend", (void*)hook_WSASend, (void**)&p_WSASend);
        bool h4 = hook_ws2("#4", (void*)hook_connect, (void**)&p_connect);
        bool h5 = hook_ws2("#3", (void*)hook_closesocket, (void**)&p_closesocket);
        logline("[INIT] ws2_32 IAT hooks: recv=%d send=%d WSASend=%d connect=%d closesocket=%d",
                h1, h2, h3, h4, h5);

        // 启动 MinHook 初始化线程
        HANDLE h_mh = CreateThread(nullptr, 0, hook_init_thread, nullptr, 0, nullptr);
        if (h_mh) CloseHandle(h_mh);

        // 启动管道与写线程
        HANDLE h_pipe = CreateThread(nullptr, 0, pipe_thread, nullptr, 0, nullptr);
        if (h_pipe) CloseHandle(h_pipe);
        HANDLE h_writer = CreateThread(nullptr, 0, writer_thread, nullptr, 0, nullptr);
        if (h_writer) CloseHandle(h_writer);

        // 启动战斗怪物数量与状态监控线程
        HANDLE h_bmon = CreateThread(nullptr, 0, battle_monitor_thread, nullptr, 0, nullptr);
        if (h_bmon) CloseHandle(h_bmon);

    } else if (reason == DLL_PROCESS_DETACH) {
        if (!reserved) {
            g_stop.store(true);
            if (g_wake_event) SetEvent(g_wake_event);

            MH_DisableHook(MH_ALL_HOOKS);
            MH_Uninitialize();

            for (auto& r : g_restore) {
                DWORD oldp;
                if (VirtualProtect(r.entry, sizeof(FARPROC), PAGE_READWRITE, &oldp)) {
                    *r.entry = r.orig;
                    VirtualProtect(r.entry, sizeof(FARPROC), oldp, &oldp);
                }
            }
            if (g_pipe != INVALID_HANDLE_VALUE) CloseHandle(g_pipe);
            if (g_wake_event) CloseHandle(g_wake_event);
            DeleteCriticalSection(&g_logmtx);
            DeleteCriticalSection(&g_sockmtx);
            DeleteCriticalSection(&g_wmtx);
            DeleteCriticalSection(&g_connmtx);
        }
    }
    return TRUE;
}
