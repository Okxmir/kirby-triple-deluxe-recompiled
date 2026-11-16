param(
    [string] $Cartridge,
    [ValidateSet('en', 'fr', 'de', 'es', 'it')] [string] $Language,
    [string] $KeyFile,
    [string] $Upstream,
    [switch] $Fast
)
. "$PSScriptRoot/common.ps1"
& "$PSScriptRoot/prepare.ps1" -Cartridge $Cartridge -KeyFile $KeyFile -Upstream $Upstream
if (!(Test-Path -LiteralPath "$ProjectRoot/extracted/shared-font.bcfnt") -or
    !(Test-Path -LiteralPath "$ProjectRoot/extracted/mii.romfs")) {
    & "$PSScriptRoot/prepare_font.ps1"
}
& "$PSScriptRoot/build_release.ps1" -Upstream $Upstream -Fast:$Fast
& "$PSScriptRoot/run_tests.ps1"
$packageOptions = @{ Upstream = $Upstream }
if ($Language) { $packageOptions.Language = $Language }
& "$PSScriptRoot/package.ps1" @packageOptions
