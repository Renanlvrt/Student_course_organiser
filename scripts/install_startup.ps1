# Creates a Startup shortcut so the organiser starts silently (tray icon) at login.
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Alt+O Organiser.lnk"

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = "`"$project\run.pyw`""
$s.WorkingDirectory = $project
$s.Description = "Alt+O download organiser"
$s.WindowStyle = 7
$s.Save()
Write-Output "Startup shortcut created: $lnk"
Write-Output "Target: $pythonw `"$project\run.pyw`""
