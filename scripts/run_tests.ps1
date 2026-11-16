param([ValidateSet('Debug','Release')][string] $Configuration = 'Release')
. "$PSScriptRoot/common.ps1"
$visualStudio = Find-KirbyVisualStudio
$ctest = Join-Path $visualStudio 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/ctest.exe'
& $ctest --test-dir (Join-Path $ProjectRoot "build/windows-$Configuration") --output-on-failure --no-tests=error
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
