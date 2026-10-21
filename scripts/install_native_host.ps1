# Registers the native-messaging host so the Chrome extension can start the organiser when it is not running.
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$native = Join-Path $project "native"
$python = (Get-Command python.exe -ErrorAction Stop).Source
$extId = (Get-Content (Join-Path $project "extension\EXTENSION_ID.txt")).Trim()

# Chrome runs this .bat; it must speak stdin/stdout, so it uses python.exe (not pythonw).
$bat = Join-Path $native "organiser_host.bat"
$noBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($bat, "@echo off`r`n`"$python`" -u `"%~dp0organiser_host.py`" %*`r`n", [Text.Encoding]::ASCII)

$manifest = @{
  name = "com.alto.organiser"
  description = "Starts the Alt+O organiser"
  path = $bat
  type = "stdio"
  allowed_origins = @("chrome-extension://$extId/")
} | ConvertTo-Json
$json = Join-Path $native "com.alto.organiser.json"
[IO.File]::WriteAllText($json, $manifest, $noBom)   # Chrome rejects a BOM

foreach ($browser in @("Google\Chrome", "Microsoft\Edge")) {
  $key = "HKCU:\Software\$browser\NativeMessagingHosts\com.alto.organiser"
  New-Item -Path $key -Force | Out-Null
  Set-ItemProperty -Path $key -Name "(default)" -Value $json
}
Write-Output "Native host registered for extension $extId"
Write-Output "Manifest: $json"
