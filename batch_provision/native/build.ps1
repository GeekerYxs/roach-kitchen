# Builds bin\launcher.exe and bin\provision_native.dll (32-bit, mingw32).
$ErrorActionPreference='Stop'
$bin='D:\mingw32win\mingw32\bin'
$env:Path="$bin;"+$env:Path
$minhook='D:\Codes\OpenAiCodex\game_smsm2\third_party\minhook'
$out=Join-Path $PSScriptRoot '..\bin'
$obj=Join-Path $PSScriptRoot 'obj'
New-Item -ItemType Directory -Force $out,$obj | Out-Null
Push-Location $PSScriptRoot
try {
    foreach ($source in @('buffer','hook','trampoline')) {
        & "$bin\gcc.exe" -O2 -I "$minhook\include" -I "$minhook\src" -c "$minhook\src\$source.c" -o "$obj\$source.o"
        if($LASTEXITCODE){throw 'MinHook compilation failed'}
    }
    & "$bin\gcc.exe" -O2 -c "$minhook\src\hde\hde32.c" -o "$obj\hde32.o"
    if($LASTEXITCODE){throw 'hde32 compilation failed'}
    & "$bin\g++.exe" -std=c++17 -O2 -Wall -static -shared -I "$minhook\include" login_dll.cpp "$obj\buffer.o" "$obj\hook.o" "$obj\trampoline.o" "$obj\hde32.o" -o "$out\provision_native.dll" -luser32 -lws2_32
    if($LASTEXITCODE){throw 'DLL compilation failed'}
    & "$bin\g++.exe" -std=c++17 -O2 -Wall -static -municode launcher.cpp -o "$out\launcher.exe" -luser32 -lshell32 -ladvapi32
    if($LASTEXITCODE){throw 'Launcher compilation failed'}
    Write-Host "Built: $out"
} finally {Pop-Location}
