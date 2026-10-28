# build.ps1 — 编译答题器（DLL + 启动答题器.exe），先跑离线测试。产物只放在 src\build\，不覆盖包里正在用的文件。
#   powershell -ExecutionPolicy Bypass -File build.ps1
# 编译器：D:\mingw32win\mingw32 (i686-win32-dwarf-msvcrt 16.2.0，和原来发布版同一套)。
# injector.exe 没改，沿用包里的；map_names.h 是从游戏解包数据生成的，这里直接用现成的（没有原始 CSV）。
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$env:PATH = "D:\mingw32win\mingw32\bin;" + $env:PATH
$gxx = "D:\mingw32win\mingw32\bin\g++.exe"
$cflags = @("-O2", "-s", "-std=c++17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-cast-function-type", "-static", "-static-libgcc", "-static-libstdc++")
if (-not (Test-Path $gxx)) { Write-Error "Compiler not found: $gxx" }
New-Item -ItemType Directory -Path "$root\build" -Force | Out-Null

Write-Host "[1/5] Generating codec tables and embedded bank..." -ForegroundColor Yellow
python "$root\tools\gen_tables.py"
python "$root\tools\gen_bank_header.py"

Write-Host "[2/5] Offline tests..." -ForegroundColor Yellow
& $gxx @cflags "-I$root\dll" "-I$root\build" "$root\tools\protocol_test.cpp" "-o" "$root\build\protocol_test.exe"
if ($LASTEXITCODE -ne 0) { throw "Build protocol_test failed" }
& $gxx @cflags "$root\tools\boss_quiz_test.cpp" "-o" "$root\build\boss_quiz_test.exe"
if ($LASTEXITCODE -ne 0) { throw "Build boss_quiz_test failed" }
& $gxx @cflags "$root\tools\native_unlock_test.cpp" "-o" "$root\build\native_unlock_test.exe"
if ($LASTEXITCODE -ne 0) { throw "Build native_unlock_test failed" }
Push-Location $root
try {
    & "$root\build\protocol_test.exe"
    if ($LASTEXITCODE -ne 0) { throw "protocol_test failed" }
    & "$root\build\boss_quiz_test.exe"
    if ($LASTEXITCODE -ne 0) { throw "boss_quiz_test failed" }
    & "$root\build\native_unlock_test.exe"
    if ($LASTEXITCODE -ne 0) { throw "native_unlock_test failed" }
} finally { Pop-Location }

Write-Host "[3/5] Compiling UAC manifest resource..." -ForegroundColor Yellow
& "D:\mingw32win\mingw32\bin\windres.exe" -i "$root\controller\app.rc" -O coff -o "$root\build\app.res"
if ($LASTEXITCODE -ne 0) { throw "Compile app.res failed" }

Write-Host "[4/5] Building quizbot.exe (the launcher exe)..." -ForegroundColor Yellow
& $gxx @cflags "$root\controller\main.cpp" "$root\build\app.res" "-o" "$root\build\quizbot.exe"
if ($LASTEXITCODE -ne 0) { throw "Build quizbot.exe failed" }

Write-Host "[5/5] Building quizbot_hook.dll..." -ForegroundColor Yellow
$minhook_srcs = @(
    "$root\dll\minhook\hook.c",
    "$root\dll\minhook\buffer.c",
    "$root\dll\minhook\trampoline.c",
    "$root\dll\minhook\hde\hde32.c"
)
& $gxx @cflags "-shared" "-I$root\dll" "-I$root\dll\include" "$root\dll\quizbot_hook.cpp" @minhook_srcs "-o" "$root\build\quizbot_hook.dll" "-lws2_32" "-lgdi32" "-luser32" "-ldinput8" "-ldxguid"
if ($LASTEXITCODE -ne 0) { throw "Build quizbot_hook.dll failed" }

Write-Host ""
Write-Host "Build complete: $root\build\quizbot.exe, $root\build\quizbot_hook.dll" -ForegroundColor Green
Write-Host "Not deployed. Going live = copy quizbot.exe over the package launcher exe and quizbot_hook.dll over the package DLL." -ForegroundColor Green
