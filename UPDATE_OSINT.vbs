Option Explicit
Dim shell, fso, root, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
script = Chr(34) & root & "\update_local.ps1" & Chr(34)
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & script, 1, False
