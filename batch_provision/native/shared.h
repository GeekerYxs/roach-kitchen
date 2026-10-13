#pragma once
#include <windows.h>
#include <stdint.h>

// Original EXE 00406859..00406963, DLL 10014551..100145DA.
struct Login72 {
    char account[16];
    char password[16];
    char reserved[32];
    uint32_t server_index;
    uint32_t role_index;
};
static_assert(sizeof(Login72) == 72, "Original IPC layout");
// Added read-only diagnostics. No credentials in this mapping.
struct Status {
    volatile LONG stage;
    DWORD error;
    DWORD hwnd;
    DWORD account_object;
    DWORD selector_object;
    DWORD role_index;
    DWORD enter_messages;
    DWORD game_base;
    DWORD started;
    DWORD finished;
    DWORD call_count;   // generic game-function calls executed (command 106)
    DWORD call_result;  // EAX returned by the last one
};
// Command 106: call a game function on the window thread. All game knowledge
// (which RVA, which registers/arguments) lives in the Python controller.
struct CallRequest {
    uint32_t rva;
    uint32_t eax, ecx, edx, ebx, esi, edi;
    uint32_t argc;       // 0..8, pushed right-to-left; ESP is restored afterwards,
    uint32_t args[8];    // so cdecl / stdcall / custom ABIs all work
};
static_assert(sizeof(CallRequest) == 64, "IPC layout");
inline void mapping_name(wchar_t* out, DWORD pid) {
    wsprintfW(out, L"Local\\MXBLLoginReplica_%lu", pid);
}
