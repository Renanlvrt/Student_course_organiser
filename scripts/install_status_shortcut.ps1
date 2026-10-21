# "Automation Status" shortcuts: Desktop (with the Ctrl+Alt+O keyboard shortcut) and Start Menu (search "Automation").
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$shell = New-Object -ComObject WScript.Shell
$targets = @(
  @{ path = Join-Path ([Environment]::GetFolderPath("Desktop")) "Automation Status.lnk"; hotkey = "CTRL+ALT+O" },
  @{ path = Join-Path ([Environment]::GetFolderPath("Programs")) "Automation Status.lnk"; hotkey = "" }
)
foreach ($t in $targets) {
  $s = $shell.CreateShortcut($t.path)
  $s.TargetPath = $pythonw
  $s.Arguments = "`"$project\status.pyw`""
  $s.WorkingDirectory = $project
  $s.IconLocation = "$project\assets\status.ico"
  $s.Description = "See the Alt+O organiser and everything that runs automatically"
  $s.Hotkey = $t.hotkey
  $s.Save()
  Write-Output "Shortcut: $($t.path)  $($t.hotkey)"
}
