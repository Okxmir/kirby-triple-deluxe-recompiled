$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Find-KirbyVisualStudio {
    $finder = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (!(Test-Path -LiteralPath $finder)) { throw 'Install Visual Studio with the Desktop development with C++ workload.' }
    $instances = & $finder -all -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    foreach ($instance in $instances) {
        $tools = Join-Path $instance 'Common7/IDE/CommonExtensions/Microsoft/CMake'
        if ((Test-Path -LiteralPath "$tools/CMake/bin/cmake.exe") -and (Test-Path -LiteralPath "$tools/Ninja/ninja.exe")) {
            return $instance
        }
    }
    throw 'Visual Studio with x64 C++ and CMake tools was not found.'
}

function Get-KirbyDependencies([string] $Directory) {
    if ($Directory) { return (Resolve-Path -LiteralPath $Directory).Path }
    return (Join-Path $ProjectRoot 'build/upstream')
}

function Build-Kirby([string] $Configuration, [string] $Upstream, [bool] $Fast) {
    $visualStudio = Find-KirbyVisualStudio
    $developerPrompt = Join-Path $visualStudio 'Common7/Tools/VsDevCmd.bat'
    $option = if ($Fast) { 'ON' } else { 'OFF' }
    $dependencies = Get-KirbyDependencies $Upstream
    & (Join-Path $PSScriptRoot 'native_build.cmd') $developerPrompt $visualStudio $Configuration $dependencies $option
    if ($LASTEXITCODE -ne 0) { throw "Windows build failed ($LASTEXITCODE)." }
}
