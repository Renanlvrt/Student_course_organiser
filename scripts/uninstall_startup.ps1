# Removes the Startup shortcut (the app itself and your files are untouched).
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Alt+O Organiser.lnk"
if (Test-Path $lnk) { Remove-Item $lnk; Write-Output "Removed $lnk" } else { Write-Output "No startup shortcut found." }
