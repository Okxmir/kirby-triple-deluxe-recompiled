param([string] $Upstream, [switch] $Fast)
. "$PSScriptRoot/common.ps1"
Build-Kirby Release $Upstream $Fast.IsPresent
