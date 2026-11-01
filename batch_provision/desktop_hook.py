"""Desktop hook to ensure all threads and child processes use the interactive desktop WinSta0\\Default."""
import os
import sys

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes as W
    import _winapi

    u = ctypes.windll.user32
    k = ctypes.windll.kernel32

    # 1. Bind current thread to Default desktop so EnumWindows / FindWindow / SendMessage see the user's desktop
    hdesk = u.OpenDesktopW('Default', 0, False, 0x01FF)
    if hdesk:
        u.SetThreadDesktop(hdesk)

    # 2. Patch _winapi.CreateProcess so all child processes (launcher.exe, game, etc.) launch on Default desktop
    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR), ('lpTitle', W.LPWSTR),
            ('dwX', W.DWORD), ('dwY', W.DWORD), ('dwXSize', W.DWORD), ('dwYSize', W.DWORD),
            ('dwXCountChars', W.DWORD), ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD),
            ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD),
            ('lpReserved2', ctypes.c_char_p), ('hStdInput', W.HANDLE), ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE), ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]

    _orig_cp = _winapi.CreateProcess

    def _default_create_process(app_name, cmd_line, proc_sec, thread_sec, inherit_handles, flags, env, cwd, startupinfo):
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(_STARTUPINFOW)
        si.lpDesktop = "WinSta0\\Default"
        if startupinfo is not None:
            if hasattr(startupinfo, 'dwFlags'):
                si.dwFlags = startupinfo.dwFlags
            if hasattr(startupinfo, 'wShowWindow'):
                si.wShowWindow = startupinfo.wShowWindow
            if hasattr(startupinfo, 'hStdInput') and startupinfo.hStdInput is not None:
                si.hStdInput = int(startupinfo.hStdInput)
            if hasattr(startupinfo, 'hStdOutput') and startupinfo.hStdOutput is not None:
                si.hStdOutput = int(startupinfo.hStdOutput)
            if hasattr(startupinfo, 'hStdError') and startupinfo.hStdError is not None:
                si.hStdError = int(startupinfo.hStdError)

        pi = _PROCESS_INFORMATION()

        env_arg = None
        if env is not None:
            flags |= 0x00000400  # CREATE_UNICODE_ENVIRONMENT
            block = '\0'.join(f'{key}={val}' for key, val in sorted(env.items())) + '\0\0'
            env_buf = ctypes.create_unicode_buffer(block, len(block))
            env_arg = ctypes.byref(env_buf)

        ok = k.CreateProcessW(app_name, cmd_line, proc_sec, thread_sec, bool(inherit_handles), flags, env_arg, cwd, ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)

        return pi.hProcess, pi.hThread, pi.dwProcessId, pi.dwThreadId

    _winapi.CreateProcess = _default_create_process
