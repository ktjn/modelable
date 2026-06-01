# PowerShell entry point for Modelable CLI
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BinDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliDir = Join-Path $BinDir "..\cli"

Push-Location $CliDir
try {
    uv run modelable @args
}
finally {
    Pop-Location
}
