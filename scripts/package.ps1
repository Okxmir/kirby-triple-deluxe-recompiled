param(
    [string] $Upstream,
    [ValidateSet('en', 'fr', 'de', 'es', 'it')] [string] $Language
)
. "$PSScriptRoot/common.ps1"
$build = Join-Path $ProjectRoot 'build/windows-Release'
$font = Join-Path $ProjectRoot 'extracted/shared-font.bcfnt'
$dist = Join-Path $ProjectRoot 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
Copy-Item -LiteralPath "$build/KirbyTripleDeluxe.exe","$build/SDL3.dll",$font,
    "$ProjectRoot/extracted/mii.romfs" -Destination $dist -Force
$licenses = Join-Path $dist 'licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
$dependencies = Get-KirbyDependencies $Upstream
Copy-Item -LiteralPath "$ProjectRoot/LICENSE" -Destination "$licenses/Clockwork.txt" -Force
Copy-Item -LiteralPath "$ProjectRoot/build/upstream/SDL3-3.4.0-src/LICENSE.txt" -Destination "$licenses/SDL.txt" -Force
Copy-Item -LiteralPath "$dependencies/xbyak-df112862583c2d327c1d9782fd28f53aa675f11d/COPYRIGHT" -Destination "$licenses/Xbyak.txt" -Force
Copy-Item -LiteralPath "$ProjectRoot/build/upstream/citra_system_archives-f470e0c9d341db73b8a24880295d2eab4cd81660/license.txt" -Destination "$licenses/SystemArchives.txt" -Force
if ($Language) {
    $languageIds = @{ en = 1; fr = 2; de = 3; es = 5; it = 4 }
    $userdata = Join-Path $dist 'userdata'
    $settings = Join-Path $userdata 'settings.ini'
    New-Item -ItemType Directory -Path $userdata -Force | Out-Null
    $lines = @()
    if (Test-Path -LiteralPath $settings) {
        $lines = @([IO.File]::ReadAllLines($settings) -notmatch '^language=')
    }
    [IO.File]::WriteAllLines($settings, [string[]]($lines + "language=$($languageIds[$Language])"))
    Write-Host "Game language: $($Language.ToLowerInvariant())"
}
Write-Output (Join-Path $dist 'KirbyTripleDeluxe.exe')
