// Source-level reconstruction of mxbl3.105 login only.
// No imports of the author's DLL or any previous project input/login module.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include "shared.h"
#include <cstring>

static HWND window;
static WNDPROC previous;
static Status* status;
static uintptr_t base;
static LONG running;
static HMODULE self_module;

static DWORD read32(uintptr_t address) {
    DWORD value=0; SIZE_T done=0;
    if (!ReadProcessMemory(GetCurrentProcess(), (void*)address, &value, 4, &done) || done!=4)
        return 0;
    return value;
}
static bool write_bytes(uintptr_t address, const void* value, size_t length) {
    SIZE_T done=0;
    return WriteProcessMemory(GetCurrentProcess(), (void*)address, value, length, &done) && done==length;
}
static void fail(DWORD error) { status->error=error; InterlockedExchange(&status->stage,-1); }
static void stage(LONG value) { InterlockedExchange(&status->stage,value); }
static bool wait_nonzero(uintptr_t address, DWORD timeout) {
    DWORD start=GetTickCount();
    while (!read32(address)) {
        if (GetTickCount()-start>=timeout) return false;
        Sleep(200);
    }
    return true;
}
static uintptr_t chain(uintptr_t root, DWORD first, DWORD second) {
    // DLL 100117C0 -> 10011CE0 -> 100088D0:
    // value = *(*(*root + first) + second). These are OFFSETS, not coordinates.
    uintptr_t a=read32(root); if(!a) return 0;
    uintptr_t b=read32(a+first); if(!b) return 0;
    return read32(b+second);
}
static void enter() {
    PostMessageW(window,WM_KEYDOWN,VK_RETURN,0);
    ++status->enter_messages;
}
// Select role_index (0..3) on the selection screen and press Enter until the
// world pointer appears (author's loop). Used by the login thread and by the
// controller's "enter" command (105) after it has checked the roster.
static bool enter_world(uintptr_t selector,DWORD role_index) {
    const uintptr_t world_flag=base+0x6aab34;   // 2.101 (2.100: 0x6959e8, 2.98/2.99: 0x64b1ac)
    status->role_index=role_index;
    stage(6);
    if(!write_bytes(selector+0x3d8,&role_index,4)) { fail(108); return false; }
    Sleep(40);
    enter();
    stage(7);
    // Preserve author's selected-index + repeated Enter loop.
    for(unsigned i=0;i<200;++i) {
        if(!write_bytes(selector+0x3d8,&role_index,4)) { fail(109); return false; }
        enter();
        if(read32(world_flag)) {
            status->finished=GetTickCount();
            stage(8); // original world pointer appeared; not visual proof!
            return true;
        }
        Sleep(200);
    }
    fail(110);
    return false;
}
static DWORD WINAPI enter_thread(void* parameter) {
    enter_world(status->selector_object,(DWORD)(uintptr_t)parameter);
    return 0;
}
static DWORD WINAPI login_thread(void* parameter) {
    Login72 packet=*(Login72*)parameter;
    SecureZeroMemory(parameter,sizeof(Login72));
    HeapFree(GetProcessHeap(),0,parameter);
    status->started=GetTickCount();
    status->role_index=packet.role_index;
    // Address initialization: original DLL 10004250..100042D6.
    // 2.101 globals (2.100: 0x6959e0 / 0x6959e8 / 0x6959e4; 2.98/2.99: 0x64b1a4 / 0x64b1ac / 0x64b1a8), located 2026-10-29.
    // 2.101 window classes grew 0x230 bytes from +0x174: UILoginNormal's account edit +0x180 -> +0x3b0 and
    // CRoleSelectDlg's selected index +0x1a8 -> +0x3d8 (edit text +0x11c and the 0x118/0x31c chain unchanged).
    const uintptr_t login_flag=base+0x6aab2c;
    const uintptr_t world_flag=base+0x6aab34;
    const uintptr_t selection_root=base+0x6aab30;
    stage(2);
    if(!wait_nonzero(login_flag,30000)) { fail(101); goto done; }
    {
        const uintptr_t object=chain(login_flag,0x40,0x3b0);
        status->account_object=(DWORD)object;
        if(!object) { fail(102); goto done; }
        char first=0; SIZE_T n=0;
        if(!ReadProcessMemory(GetCurrentProcess(),(void*)(object+0x11c),&first,1,&n) || n!=1) { fail(103); goto done; }
        // Original 10012949: Enter only when existing account text is empty.
        if(!first) enter();
        stage(3);
        // Same destination and strcpy_s semantics (up to terminating NUL).
        if(!write_bytes(object+0x11c,packet.account,strlen(packet.account)+1)) { fail(104); goto done; }
        Sleep(100);
    }
    stage(4);
    for(size_t i=0;packet.password[i];++i) {
        Sleep(40);
        DWORD_PTR ignored=0;
        // Same WM_CHAR target and signed byte as the original SendMessageW.
        // Timeout wrapper prevents a permanently hung target blocking forever.
        if(!SendMessageTimeoutW(window,WM_CHAR,(WPARAM)(int)(signed char)packet.password[i],0,
                                SMTO_ABORTIFHUNG,2000,&ignored)) { fail(105); goto done; }
    }
    SecureZeroMemory(packet.password,sizeof(packet.password));
    Sleep(40);
    enter();
    stage(5);
    // Original polls *(world_flag + 0xC), max 200 x 200ms.
    if(!wait_nonzero(world_flag+0xc,40000)) { fail(106); goto done; }
    PostMessageW(window,WM_KEYUP,VK_DOWN,0);
    Sleep(200);
    PostMessageW(window,WM_KEYUP,VK_DOWN,0);
    Sleep(200);
    {
        // The selection UI object can appear a little after the login flag when the
        // machine is busy (seen with 8 clients starting: error 107). Poll up to 10 s.
        uintptr_t selector=0;
        for(unsigned i=0;i<50&&!(selector=chain(selection_root,0x118,0x31c));++i)Sleep(200);
        status->selector_object=(DWORD)selector;
        if(!selector) { fail(107); goto done; }
        if(packet.reserved[0]==1) {status->finished=GetTickCount();stage(9);goto done;}
        enter_world(selector,packet.role_index);
    }
done:
    SecureZeroMemory(&packet,sizeof(packet));
    // Deliberately never accept another login in this process; no hidden retry.
    return 0;
}
#include "network.inc"
static LRESULT CALLBACK game_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
    if(msg==WM_COPYDATA) {
        auto* copy=(COPYDATASTRUCT*)lp;
        if(copy && copy->dwData>=100 && copy->dwData<=107) return provision_command(copy);
        if(copy && copy->dwData==13) {
            if(copy->cbData!=sizeof(Login72)||!copy->lpData) return FALSE;
            const auto* input=(const Login72*)copy->lpData;
            if(!memchr(input->account,0,16)||!memchr(input->password,0,16)||
               !input->account[0]||!input->password[0]||input->role_index>3) return FALSE;
            if(InterlockedCompareExchange(&running,1,0)!=0) return FALSE;
            auto* packet=(Login72*)HeapAlloc(GetProcessHeap(),0,sizeof(Login72));
            if(!packet) { fail(111); return FALSE; }
            memcpy(packet,input,sizeof(Login72));
            HANDLE thread=CreateThread(nullptr,0,login_thread,packet,0,nullptr);
            if(!thread) { SecureZeroMemory(packet,sizeof(Login72));HeapFree(GetProcessHeap(),0,packet);fail(112);return FALSE; }
            CloseHandle(thread);
            return TRUE;
        }
    }
    return CallWindowProcW(previous,hwnd,msg,wp,lp);
}
static BOOL CALLBACK find_window(HWND hwnd,LPARAM) {
    DWORD pid=0;GetWindowThreadProcessId(hwnd,&pid);
    if(pid==GetCurrentProcessId() && GetWindow(hwnd,GW_OWNER)==nullptr && IsWindowVisible(hwnd)) {
        wchar_t title[256]={};GetWindowTextW(hwnd,title,256);
        if(wcsstr(title,L"什么什么大冒险2")) { window=hwnd;return FALSE; }
    }
    return TRUE;
}
static DWORD WINAPI initialize(void*) {
    wchar_t name[96];mapping_name(name,GetCurrentProcessId());
    HANDLE map=OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,name);
    if(!map) return 1;
    status=(Status*)MapViewOfFile(map,FILE_MAP_ALL_ACCESS,0,0,sizeof(Status));
    if(!status) return 2;
    base=(uintptr_t)GetModuleHandleW(nullptr);
    status->game_base=(DWORD)base;
    for(unsigned i=0;i<150&&!window;++i) {EnumWindows(find_window,0);if(!window)Sleep(200);}
    if(!window){fail(113);return 3;}
    status->hwnd=(DWORD)(uintptr_t)window;
    SetLastError(0);
    previous=(WNDPROC)SetWindowLongPtrW(window,GWLP_WNDPROC,(LONG_PTR)game_proc);
    if(!previous){fail(114);return 4;}
    stage(1);
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,void*) {
    if(reason==DLL_PROCESS_ATTACH){self_module=module;DisableThreadLibraryCalls(module);HANDLE t=CreateThread(nullptr,0,initialize,nullptr,0,nullptr);if(t)CloseHandle(t);}
    return TRUE;
}
