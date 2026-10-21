# Puts an "Automation Status" shortcut on the Desktop.
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$desktop = [Environment]::GetFolderPath("Desktop")
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Automation Status.lnk"))
$s.TargetPath = $pythonw
$s.Arguments = "`"$project\status.pyw`""
$s.WorkingDirectory = $project
$s.IconLocation = "$project\assets\status.ico"
$s.Description = "See the Alt+O organiser and everything that runs automatically"
$s.Save()
Write-Output "Desktop shortcut created: $(Join-Path $desktop 'Automation Status.lnk')"
