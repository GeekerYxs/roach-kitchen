// Post-login observation and bounded research commands; no credential capture.
#include "MinHook.h"
#include <cstdio>
#include <string>
static FILE* tap_file;
static CRITICAL_SECTION tap_lock;
static bool armed=false;
// Max create requests per process (4 role slots). Python serializes: it waits
// for each 0x4003 before sending the next one.
static LONG create_count=0;
static const LONG MAX_CREATES=4;
extern "C" { void* send_trampoline=nullptr; }
struct Regs {DWORD edi,esi,ebp,esp,ebx,edx,ecx,eax,flags,ret,body;};
static decltype(&send) original_send;
static decltype(&recv) original_recv;
static decltype(&WSASend) original_wsasend;
static std::wstring output_dir(){wchar_t path[MAX_PATH];GetModuleFileNameW(self_module,path,MAX_PATH);std::wstring s=path;return s.substr(0,s.find_last_of(L"\\/"));}
static void record(const char* kind,DWORD op,const void* ptr,unsigned length,DWORD caller=0){
    if(!armed||length>65536)return;
    unsigned char* data=(unsigned char*)HeapAlloc(GetProcessHeap(),0,length?length:1);SIZE_T got=0;
    if(!data)return;
    if(length&&(!ReadProcessMemory(GetCurrentProcess(),ptr,data,length,&got)||got!=length)){HeapFree(GetProcessHeap(),0,data);return;}
    EnterCriticalSection(&tap_lock);
    fprintf(tap_file,"{\"kind\":\"%s\",\"tick\":%lu,\"opcode\":%lu,\"caller_rva\":%lu,\"length\":%u,\"hex\":\"",kind,GetTickCount(),op,caller,length);
    for(unsigned i=0;i<length;++i)fprintf(tap_file,"%02x",data[i]);
    fprintf(tap_file,"\"}\n");fflush(tap_file);
    LeaveCriticalSection(&tap_lock);HeapFree(GetProcessHeap(),0,data);
}
extern "C" void __cdecl log_request(Regs* r){if(r->edi<=0x1bfc)record("request",r->ebx,(void*)r->body,r->edi,r->ret-base);}
extern "C" __attribute__((naked)) void tap_entry(){__asm__ __volatile__("pushfl\n pushal\n pushl %esp\n call _log_request\n addl $4,%esp\n popal\n popfl\n jmp *_send_trampoline\n");}
static int WINAPI tap_send(SOCKET s,const char*b,int n,int f){int r=original_send(s,b,n,f);int e=WSAGetLastError();if(n>0)record("wire_send",0,b,n);WSASetLastError(e);return r;}
static int WINAPI tap_recv(SOCKET s,char*b,int n,int f){int r=original_recv(s,b,n,f);int e=WSAGetLastError();if(r>0)record("wire_recv",0,b,r);WSASetLastError(e);return r;}
static int WINAPI tap_wsasend(SOCKET s,LPWSABUF b,DWORD count,LPDWORD sent,DWORD flags,LPWSAOVERLAPPED ov,LPWSAOVERLAPPED_COMPLETION_ROUTINE callback){int r=original_wsasend(s,b,count,sent,flags,ov,callback);int e=WSAGetLastError();for(DWORD i=0;i<count;++i)if(b[i].len)record("wire_WSASend",0,b[i].buf,b[i].len);WSASetLastError(e);return r;}
static bool arm(){
    if(armed)return true;
    std::wstring folder=output_dir()+L"\\..\\runtime";
    CreateDirectoryW(folder.c_str(),nullptr);
    std::wstring prefix=folder+L"\\tap_"+std::to_wstring(GetCurrentProcessId());
    tap_file=_wfopen((prefix+L".jsonl").c_str(),L"wb");if(!tap_file)return false;
    FILE* codec=_wfopen((prefix+L"_codec.json").c_str(),L"wb");if(!codec)return false;
    fprintf(codec,"{");
    for(int k=0;k<2;++k){fprintf(codec,"%s\"%s\":[",k?",":"",k?"decode":"encode");for(int i=0;i<10;++i){DWORD ptr=read32(base+(k?0x571f0c:0x571ee4)+i*4);unsigned char bytes[256];SIZE_T n=0;if(!ReadProcessMemory(GetCurrentProcess(),(void*)ptr,bytes,256,&n)||n!=256){fclose(codec);return false;}fprintf(codec,"%s\"",i?",":"");for(int j=0;j<256;++j)fprintf(codec,"%02x",bytes[j]);fprintf(codec,"\"");}fprintf(codec,"]");}fprintf(codec,"}");fclose(codec);
    InitializeCriticalSection(&tap_lock);
    if(MH_Initialize()!=MH_OK)return false;
    HMODULE ws=GetModuleHandleW(L"ws2_32.dll");
    if(MH_CreateHook((void*)(base+0x316ab0),(void*)tap_entry,&send_trampoline)!=MH_OK)return false;
    if(MH_CreateHook((void*)GetProcAddress(ws,"send"),(void*)tap_send,(void**)&original_send)!=MH_OK)return false;
    if(MH_CreateHook((void*)GetProcAddress(ws,"recv"),(void*)tap_recv,(void**)&original_recv)!=MH_OK)return false;
    if(MH_CreateHook((void*)GetProcAddress(ws,"WSASend"),(void*)tap_wsasend,(void**)&original_wsasend)!=MH_OK)return false;
    armed=true;
    if(MH_EnableHook(MH_ALL_HOOKS)!=MH_OK){armed=false;return false;}
    return true;
}
// call_regs(fn, regs[6]=eax,ecx,edx,ebx,esi,edi, args, argc): pushes args right-to-left,
// loads the registers, calls fn, then restores ESP from EBP (works for any cleanup style).
extern "C" DWORD __cdecl call_regs(DWORD fn,const DWORD* regs,const uint32_t* args,DWORD argc);
extern "C" { DWORD call_target=0; }
__asm__(R"(
.globl _call_regs
_call_regs:
    pushl %ebp
    movl  %esp, %ebp
    pushl %ebx
    pushl %esi
    pushl %edi
    movl  20(%ebp), %ecx
    movl  16(%ebp), %edx
1:  testl %ecx, %ecx
    jz    2f
    decl  %ecx
    pushl (%edx,%ecx,4)
    jmp   1b
2:  movl  8(%ebp), %eax
    movl  %eax, _call_target
    movl  12(%ebp), %eax
    movl  4(%eax), %ecx
    movl  8(%eax), %edx
    movl  12(%eax), %ebx
    movl  16(%eax), %esi
    movl  20(%eax), %edi
    movl  (%eax), %eax
    call  *_call_target
    leal  -12(%ebp), %esp
    popl  %edi
    popl  %esi
    popl  %ebx
    popl  %ebp
    ret
)");
static LRESULT generic_call(const COPYDATASTRUCT* copy){
    if(status->stage!=8||copy->cbData!=sizeof(CallRequest))return FALSE;  // in world only
    const auto* r=(const CallRequest*)copy->lpData;
    const auto* nt=(const IMAGE_NT_HEADERS*)(base+((const IMAGE_DOS_HEADER*)base)->e_lfanew);
    if(r->argc>8||r->rva<0x1000||r->rva>=nt->OptionalHeader.SizeOfImage)return FALSE;
    const DWORD regs[6]={r->eax,r->ecx,r->edx,r->ebx,r->esi,r->edi};
    status->call_result=call_regs((DWORD)(base+r->rva),regs,r->args,r->argc);
    InterlockedIncrement((LONG*)&status->call_count);
    return TRUE;
}
static LRESULT provision_command(const COPYDATASTRUCT* copy){
    if(copy->dwData==106)return generic_call(copy);
    // arm only observes (send/recv tap): allowed in world too, to record the client's own requests
    // (2026-10-26: the shop's sell reply 「第三个物品不存在」 on 2.100)
    if(copy->dwData==100&&status->stage==8)return arm();
    if(status->stage!=9)return FALSE;
    if(copy->dwData==100)return arm();
    if(copy->dwData==101&&copy->cbData==12){const DWORD* p=(const DWORD*)copy->lpData;if(p[0]>1024||p[1]>768||p[2]>2)return FALSE;UINT msg=p[2]==0?WM_MOUSEMOVE:(p[2]==1?WM_LBUTTONDOWN:WM_LBUTTONUP);return PostMessageW(window,msg,p[2]==1?MK_LBUTTON:0,MAKELPARAM(p[0],p[1]));}
    if(copy->dwData==102&&copy->cbData>0&&copy->cbData<=16){const unsigned char*p=(const unsigned char*)copy->lpData;for(DWORD i=0;i<copy->cbData;++i)PostMessageW(window,WM_CHAR,p[i],0);return TRUE;}
    if(copy->dwData==103&&copy->cbData==300){
        const DWORD* header=(const DWORD*)copy->lpData;
        if(!armed||header[0]!=2||header[1]!=292)return FALSE;
        const unsigned char* body=(const unsigned char*)(header+2);
        if(!body[275]||!memchr(body+275,0,16))return FALSE;
        DWORD manager=read32(base+0x6959f4);
        if(!manager||read32(manager+0x20)==0xffffffff)return FALSE;
        if(InterlockedIncrement(&create_count)>MAX_CREATES)return FALSE;
        uintptr_t result=(uintptr_t)body;
        uintptr_t function=base+0x316ab0;
        // Actual sender ABI: ESI=connection, EBX=opcode, EDI=length, stack=body; ret 4.
        __asm__ __volatile__("pushl %%eax\n call *%%edx\n" : "+a"(result) : "d"(function),"S"(manager),"b"(2),"D"(292) : "ecx","memory","cc");
        return TRUE; // dispatch only; require 0x4003 and an actual role-list observation.
    }
    if(copy->dwData==107&&copy->cbData==294){
        // Delete one role: opcode 3, 286-byte body (client builder RVA 0xF4120). At most one per process.
        static LONG delete_count=0;
        const DWORD* header=(const DWORD*)copy->lpData;
        if(!armed||header[0]!=3||header[1]!=286)return FALSE;
        const unsigned char* body=(const unsigned char*)(header+2);
        if(!(body[265]|body[266]|body[267]|body[268]))return FALSE;  // char_id must not be 0
        DWORD manager=read32(base+0x6959f4);
        if(!manager||read32(manager+0x20)==0xffffffff)return FALSE;
        if(InterlockedIncrement(&delete_count)>1)return FALSE;
        uintptr_t result=(uintptr_t)body;
        uintptr_t function=base+0x316ab0;
        __asm__ __volatile__("pushl %%eax\n call *%%edx\n" : "+a"(result) : "d"(function),"S"(manager),"b"(3),"D"(286) : "ecx","memory","cc");
        return TRUE; // dispatch only; Python waits for 0x4004.
    }
    if(copy->dwData==105&&copy->cbData==4){
        // Enter the world with role index 0..3 (runs once per process, in its own thread).
        static LONG entering=0;
        DWORD index=*(const DWORD*)copy->lpData;
        if(index>3||!status->selector_object)return FALSE;
        if(InterlockedCompareExchange(&entering,1,0)!=0)return FALSE;
        HANDLE t=CreateThread(nullptr,0,enter_thread,(void*)(uintptr_t)index,0,nullptr);
        if(!t){InterlockedExchange(&entering,0);return FALSE;}
        CloseHandle(t);
        return TRUE;
    }
    if(copy->dwData==104&&copy->cbData==4){DWORD key=*(DWORD*)copy->lpData;if(key!=VK_RETURN&&key!=VK_TAB&&key!=VK_ESCAPE)return FALSE;return PostMessageW(window,WM_KEYDOWN,key,0);}
    return FALSE;
}
