Option Explicit

Dim shell, fso, scriptDir, runnerPath, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
runnerPath = fso.BuildPath(scriptDir, "run_wallpaper.ps1")

cmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & runnerPath & """"
shell.Run cmd, 0, True
