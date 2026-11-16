param(
    [string] $Cartridge,
    [string] $KeyFile,
    [string] $Upstream
)
. "$PSScriptRoot/common.ps1"

if ($Cartridge) { $Cartridge = (Resolve-Path -LiteralPath $Cartridge).Path }
if ($KeyFile) { $KeyFile = (Resolve-Path -LiteralPath $KeyFile).Path }
$dependencies = Get-KirbyDependencies $Upstream
$ProgressPreference = 'SilentlyContinue'
$pinned = '3047d9e990be4ac2c84174cb570dfec569c882e9'
$rustVersion = '1.90.0-x86_64-pc-windows-msvc'

function Get-VerifiedArchive([string] $Name, [string] $Url, [string] $Sha256, [string] $Directory = $dependencies) {
    $path = Join-Path $Directory $Name
    if (!(Test-Path -LiteralPath $path)) {
        $partial = "$path.partial"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partial -TimeoutSec 240
        if ((Get-FileHash -LiteralPath $partial).Hash -ne $Sha256) { throw "SHA-256 mismatch for $Name" }
        Move-Item -LiteralPath $partial -Destination $path
    }
    if ((Get-FileHash -LiteralPath $path).Hash -ne $Sha256) { throw "SHA-256 mismatch for $Name" }
    return $path
}

Push-Location -LiteralPath $ProjectRoot
try {
    New-Item -ItemType Directory -Path 'logs','extracted','generated/kirby-eur' -Force | Out-Null
    $localDependencies = Get-KirbyDependencies
    $sdlDir = Join-Path $localDependencies 'SDL3-3.4.0-src'
    if (!(Test-Path -LiteralPath "$sdlDir/CMakeLists.txt")) {
        New-Item -ItemType Directory -Path $localDependencies -Force | Out-Null
        $sdl = Get-VerifiedArchive 'SDL3-3.4.0.tar.gz' 'https://github.com/libsdl-org/SDL/releases/download/release-3.4.0/SDL3-3.4.0.tar.gz' '082CBF5F429E0D80820F68DC2B507A94D4CC1B4E70817B119BBB8EC6A69584B8' $localDependencies
        $stagedSdl = "$sdlDir-$([Guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Path $stagedSdl | Out-Null
        tar.exe -xf $sdl -C $stagedSdl --strip-components=1
        if ($LASTEXITCODE -ne 0) { throw "Could not unpack $sdl." }
        Move-Item -LiteralPath $stagedSdl -Destination $sdlDir
    }
    if (!$Upstream) {
        New-Item -ItemType Directory -Path $dependencies -Force | Out-Null
        $clockwork = Get-VerifiedArchive 'clockwork-pinned.zip' "https://codeload.github.com/watchmakerers/clockwork/zip/$pinned" '7923E82994E3A06F7AA17DFDB2A6E25A608E3495227BAF1A0FDBCC32DFBE1DED'
        $xbyakCommit = 'df112862583c2d327c1d9782fd28f53aa675f11d'
        $xbyak = Get-VerifiedArchive 'xbyak-pinned.zip' "https://codeload.github.com/herumi/xbyak/zip/$xbyakCommit" 'B0E8D74A5813D4C4D2BAA550B889B7F7C2696E471DFB8DE1554CE47F7E52D7F8'
        $dxc = Get-VerifiedArchive 'dxc_2025_07_14.zip' 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.8.2505.1/dxc_2025_07_14.zip' '9AD895A6B039E3A8F8C22A1009F866800B840A74B50DB9218D13319E215EA8A4'
        $memmap = Get-VerifiedArchive 'memmap2-0.9.11.crate' 'https://static.crates.io/crates/memmap2/memmap2-0.9.11.crate' 'D1219ED1B7F229EE7104D281DD01D6802FE28BB6E95D292942C4DAACDEB798C0'
        $rustc = Get-VerifiedArchive "rustc-$rustVersion.tar.xz" "https://static.rust-lang.org/dist/rustc-$rustVersion.tar.xz" 'A18B3912905F154C34A7572954DDA9E9849AC6411A1E02FA390BF742F918FBCB'
        $rustStd = Get-VerifiedArchive "rust-std-$rustVersion.tar.xz" "https://static.rust-lang.org/dist/rust-std-$rustVersion.tar.xz" '3B8C22F81C93C7E914369433430792BD6C06403806AE25B0B95F3CFC540A8B48'
        if (!(Test-Path -LiteralPath "$dependencies/clockwork-master/runtime")) {
            Expand-Archive -LiteralPath $clockwork -DestinationPath $dependencies -Force
            Move-Item -LiteralPath "$dependencies/clockwork-$pinned" -Destination "$dependencies/clockwork-master"
        }
        if (!(Test-Path -LiteralPath "$dependencies/xbyak-$xbyakCommit/xbyak/xbyak.h")) {
            Expand-Archive -LiteralPath $xbyak -DestinationPath $dependencies -Force
        }
        $dxcDir = Join-Path $dependencies 'dxc-1.8.2505.1'
        if (!(Test-Path -LiteralPath "$dxcDir/bin/x64/dxc.exe")) {
            Expand-Archive -LiteralPath $dxc -DestinationPath $dxcDir -Force
        }
        $compiler = "$dependencies/rustc-$rustVersion/rustc"
        $targetLib = "$compiler/lib/rustlib/x86_64-pc-windows-msvc/lib"
        foreach ($archive in @($memmap,$rustc,$rustStd)) {
            tar.exe -xf $archive -C $dependencies
            if ($LASTEXITCODE -ne 0) { throw "Could not unpack $archive." }
        }
        $stdlib = "$dependencies/rust-std-$rustVersion/rust-std-x86_64-pc-windows-msvc/lib/rustlib/x86_64-pc-windows-msvc/lib"
        New-Item -ItemType Directory -Path $targetLib -Force | Out-Null
        Copy-Item -Path "$stdlib/*" -Destination $targetLib -Recurse -Force
    }

    $vs = Find-KirbyVisualStudio
    & "$PSScriptRoot/build_tools.cmd" (Join-Path $vs 'Common7/Tools/VsDevCmd.bat') $dependencies
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the extraction and recompilation tools.' }

    $image = 'extracted/KIRBY-EUR.cxi'
    $candidate = $image
    if ($Cartridge -or !(Test-Path -LiteralPath $image)) {
        $candidate = "extracted/KIRBY-EUR-$([Guid]::NewGuid().ToString('N')).cxi"
        $options = @('--extract', $candidate)
        if ($Cartridge) { $options += $Cartridge }
        if ($KeyFile) { $options += @('--key-file', $KeyFile) }
        python tools/cartridge.py @options
        if ($LASTEXITCODE -ne 0) { throw 'Could not extract the cartridge.' }
    }
    python tools/verify_extraction.py $candidate | Tee-Object -FilePath logs/integrity.txt
    if ($LASTEXITCODE -ne 0) { throw 'The game partition failed integrity checks.' }
    & build/tools/ctrx.exe --code-only $candidate extracted/kirby-eur | Tee-Object -FilePath logs/extraction.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the ARM executable.' }
    $expectedCode = 'E3ACD2FD3E6DC8EDDE61A6F5BAB0EED7DF1DAEEB02FD3C10E44AC466E477567B'
    if ((Get-FileHash -LiteralPath 'extracted/kirby-eur/code.bin').Hash -ne $expectedCode) {
        throw 'The cartridge does not match the supported European game revision.'
    }
    if ($candidate -ne $image) { Move-Item -LiteralPath $candidate -Destination $image -Force }
    $staged = 'build/generated-staging'
    New-Item -ItemType Directory -Path $staged -Force | Out-Null
    & build/tools/recomp.exe emit extracted/kirby-eur $staged | Tee-Object -FilePath logs/recompile.txt
    if ($LASTEXITCODE -ne 0) { throw 'ARM code generation failed.' }
    foreach ($file in (Get-ChildItem -LiteralPath $staged -File)) {
        $dest = Join-Path 'generated/kirby-eur' $file.Name
        if (!(Test-Path -LiteralPath $dest) -or
            (Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath $dest).Hash) {
            Copy-Item -LiteralPath $file.FullName -Destination $dest -Force
        }
    }
} finally {
    Pop-Location
}
