#include "shared.h"
#include <shellapi.h>
#include <wincrypt.h>
#include <tlhelp32.h>
#include <iostream>
#include <fstream>
#include <string>
#include <cstring>

static const char* CLIENT_HASH="500cf8f165cfbbf6f8f28ddb01648dbee3de10a1a8068f51b359598560958c27";
static std::wstring own_dir() { wchar_t p[MAX_PATH];GetModuleFileNameW(nullptr,p,MAX_PATH);std::wstring s=p;return s.substr(0,s.find_last_of(L"\\/")); }
static bool valid_build(const std::wstring& file) {
    HANDLE f=CreateFileW(file.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
    if(f==INVALID_HANDLE_VALUE)return false;
    HCRYPTPROV provider=0;HCRYPTHASH hash=0;
    bool ok=CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)&&CryptCreateHash(provider,CALG_SHA_256,0,0,&hash);
    BYTE buf[65536];DWORD n=0;
    while(ok) { if(!ReadFile(f,buf,sizeof(buf),&n,nullptr)){ok=false;break;}if(!n)break;ok=CryptHashData(hash,buf,n,0); }
    BYTE digest[32];DWORD size=32;char hex[65]={};
    if(ok)ok=CryptGetHashParam(hash,HP_HASHVAL,digest,&size,0);
    if(ok)for(unsigned i=0;i<32;++i)sprintf(hex+i*2,"%02x",digest[i]);
    if(hash)CryptDestroyHash(hash);
    if(provider)CryptReleaseContext(provider,0);
    CloseHandle(f);
    return ok && !strcmp(hex,CLIENT_HASH);
}
static bool inject(HANDLE process,DWORD pid,const std::wstring& path) {
    // Original EXE 0040B1C0 chain: allocate, write DLL path, remote LoadLibrary.
    // Wide string used here so the standalone folder may contain Chinese.
    SIZE_T length=(path.size()+1)*sizeof(wchar_t),done=0;
    void* remote=VirtualAllocEx(process,nullptr,length,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!remote){std::cerr<<"Remote allocation error "<<GetLastError()<<"\n";return false;}
    bool ok=WriteProcessMemory(process,remote,path.c_str(),length,&done)&&done==length;
    uintptr_t local=(uintptr_t)GetModuleHandleW(L"kernel32.dll");
    uintptr_t offset=(uintptr_t)GetProcAddress((HMODULE)local,"LoadLibraryW")-local;
    uintptr_t remote_kernel=0;
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE,pid);
    MODULEENTRY32W item={};item.dwSize=sizeof(item);
    if(snapshot!=INVALID_HANDLE_VALUE){if(Module32FirstW(snapshot,&item))do{if(!_wcsicmp(item.szModule,L"kernel32.dll")){remote_kernel=(uintptr_t)item.modBaseAddr;break;}}while(Module32NextW(snapshot,&item));CloseHandle(snapshot);}
    HANDLE thread=ok&&remote_kernel?CreateRemoteThread(process,nullptr,0,(LPTHREAD_START_ROUTINE)(remote_kernel+offset),remote,0,nullptr):nullptr;
    DWORD result=0;
    if(thread) { DWORD wait=WaitForSingleObject(thread,15000);ok=wait==WAIT_OBJECT_0&&GetExitCodeThread(thread,&result)&&result;CloseHandle(thread);if(wait==WAIT_TIMEOUT)return false; }
    else {std::cerr<<"Remote thread error "<<GetLastError()<<", kernel="<<remote_kernel<<"\n";ok=false;}
    if(!ok)std::cerr<<"Remote library result="<<result<<"\n";
    VirtualFreeEx(process,remote,0,MEM_RELEASE);
    return ok;
}
// Machine-readable result for the Python controller: one file per launch,
// never a shared path, so parallel launchers cannot overwrite each other.
static void write_result(const std::wstring& path,DWORD pid,const Status* s,int slot,DWORD elapsed,int code) {
    std::ofstream report(path.c_str());
    report<<"{\n  \"code\": "<<code<<",\n  \"pid\": "<<pid<<",\n  \"slot\": "<<slot<<",\n  \"elapsed_ms\": "<<elapsed;
    if(s) report<<",\n  \"hwnd\": "<<s->hwnd<<",\n  \"stage\": "<<s->stage<<",\n  \"error\": "<<s->error<<",\n  \"game_base\": "<<s->game_base
                <<",\n  \"account_object\": "<<s->account_object<<",\n  \"selector_object\": "<<s->selector_object<<",\n  \"enter_messages\": "<<s->enter_messages;
    report<<"\n}\n";
}
int wmain(int argc,wchar_t**argv) {
    SetConsoleOutputCP(CP_UTF8);
    int slot=1,server=0,inject_delay=1500;bool piped=false,selection_only=false;
    std::wstring game=L"D:\\什么什么大冒险2.0免安装绿色版2.97\\v2.1\\win32\\WaatClient.exe";
    std::wstring result_path;
    for(int i=1;i<argc;++i) {
        if(!wcscmp(argv[i],L"--slot")&&i+1<argc)slot=_wtoi(argv[++i]);
        else if(!wcscmp(argv[i],L"--server-index")&&i+1<argc)server=_wtoi(argv[++i]);
        else if(!wcscmp(argv[i],L"--game")&&i+1<argc)game=argv[++i];
        else if(!wcscmp(argv[i],L"--result")&&i+1<argc)result_path=argv[++i];
        else if(!wcscmp(argv[i],L"--inject-delay")&&i+1<argc)inject_delay=_wtoi(argv[++i]);
        else if(!wcscmp(argv[i],L"--stdin"))piped=true;
        else if(!wcscmp(argv[i],L"--selection-only"))selection_only=true;
        else {std::cerr<<"Usage: launcher.exe [--slot 1..4] [--server-index 0] [--game PATH] [--stdin] [--selection-only] [--result FILE]\n";return 2;}
    }
    if(result_path.empty())result_path=own_dir()+L"\\last_result.json";
    if(slot<1||slot>4||server<0||server>1000){std::cerr<<"Invalid slot/server index\n";return 2;}
    if(!valid_build(game)){std::cerr<<"Game SHA256 mismatch or file missing; stopped\n";return 3;}
    Login72 packet={};std::string account,password;
    if(!piped)std::cout<<"Account: "<<std::flush;
    std::getline(std::cin,account);
    HANDLE console=GetStdHandle(STD_INPUT_HANDLE);DWORD mode=0;bool masked=!piped&&GetConsoleMode(console,&mode);
    if(!piped)std::cout<<"Password: "<<std::flush;
    if(masked)SetConsoleMode(console,mode&~ENABLE_ECHO_INPUT);
    std::getline(std::cin,password);
    if(masked)SetConsoleMode(console,mode);
    if(!piped)std::cout<<"\n";
    if(account.empty()||password.empty()||account.size()>15||password.size()>15||account.find('\0')!=std::string::npos||password.find('\0')!=std::string::npos){std::cerr<<"Credentials require 1..15 bytes\n";return 4;}
    memcpy(packet.account,account.c_str(),account.size()+1);memcpy(packet.password,password.c_str(),password.size()+1);
    SecureZeroMemory(&password[0],password.size());password.clear();
    packet.server_index=server;packet.role_index=slot-1;
    packet.reserved[0]=selection_only?1:0;
    HANDLE mutex=CreateMutexA(nullptr,FALSE,"iuiuu_run_client"); // original 00406719
    // 0040697E inserts /id= before the numeric string; 004069DF APPENDS
    // the 17-character literal. /login= MUST remain the last token.
    std::wstring parameters=L" /id="+std::to_wstring(server+101)+L" /type=11 /login=";
    std::wstring work=game.substr(0,game.find_last_of(L"\\/"));
    SHELLEXECUTEINFOW launch={};launch.cbSize=sizeof(launch);launch.fMask=SEE_MASK_NOCLOSEPROCESS;
    launch.lpVerb=L"open";launch.lpFile=game.c_str();launch.lpParameters=parameters.c_str();launch.lpDirectory=work.c_str();launch.nShow=SW_SHOWNOACTIVATE;
    DWORD start=GetTickCount();
    if(!ShellExecuteExW(&launch)||!launch.hProcess){std::cerr<<"Launch failed\n";SecureZeroMemory(&packet,sizeof(packet));return 5;}
    DWORD pid=GetProcessId(launch.hProcess);
    std::cout<<"PID "<<pid<<", slot "<<slot<<"\n"<<std::flush;
    // Every exit after this point writes the result file (with pid) so the
    // controller can log the failing stage and clean up the process.
    auto stop=[&](int code,const char* why,const Status* s)->int{
        SecureZeroMemory(&packet,sizeof(packet));
        std::cerr<<why<<"\n";
        write_result(result_path,pid,s,slot,GetTickCount()-start,code);
        return code;
    };
    WaitForInputIdle(launch.hProcess,15000);
    Sleep(inject_delay); // Wait for the actual game module/import initialization before injection.
    HANDLE process=OpenProcess(PROCESS_CREATE_THREAD|PROCESS_VM_OPERATION|PROCESS_VM_READ|PROCESS_VM_WRITE|PROCESS_QUERY_INFORMATION|SYNCHRONIZE,FALSE,pid);
    if(!process)return stop(6,"OpenProcess failed",nullptr);
    wchar_t name[96];mapping_name(name,pid);
    HANDLE map=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(Status),name);
    auto* status=map?(Status*)MapViewOfFile(map,FILE_MAP_ALL_ACCESS,0,0,sizeof(Status)):nullptr;
    if(!status)return stop(7,"Diagnostic mapping failed",nullptr);
    ZeroMemory(status,sizeof(Status));
    const std::wstring folder=own_dir();
    if(!inject(process,pid,folder+L"\\provision_native.dll"))return stop(8,"DLL initialization failed",status);
    DWORD wait=GetTickCount();while(status->stage==0 && GetTickCount()-wait<30000 && WaitForSingleObject(process,0)==WAIT_TIMEOUT)Sleep(100);
    if(status->stage!=1)return stop(9,"Window hook unavailable",status);
    Sleep(1500); // original launcher 00406CD3
    COPYDATASTRUCT copy={13,sizeof(packet),&packet};DWORD_PTR accepted=0;
    bool sent=SendMessageTimeoutW((HWND)(uintptr_t)status->hwnd,WM_COPYDATA,0,(LPARAM)&copy,SMTO_ABORTIFHUNG,1000,&accepted)&&accepted;
    SecureZeroMemory(&packet,sizeof(packet));
    if(!sent)return stop(10,"Login IPC rejected",status);
    LONG last=0;wait=GetTickCount();
    while(GetTickCount()-wait<120000 && WaitForSingleObject(process,0)==WAIT_TIMEOUT) {
        LONG current=status->stage;
        if(current!=last){std::cout<<"Stage "<<current<<", error "<<status->error<<"\n"<<std::flush;last=current;}
        if(current==8||current==9||current<0)break;
        Sleep(100);
    }
    bool ok=status->stage==8||status->stage==9;
    if(WaitForSingleObject(process,0)!=WAIT_TIMEOUT)std::cerr<<"Game process exited during login\n";
    // Evidence has no account or password.
    write_result(result_path,pid,status,slot,GetTickCount()-start,ok?0:11);
    UnmapViewOfFile(status);CloseHandle(map);CloseHandle(process);CloseHandle(launch.hProcess);if(mutex)CloseHandle(mutex);
    std::cout<<(ok?"Login checkpoint reached.\n":"Stopped; no automatic login retry.\n");
    return ok?0:11;
}
