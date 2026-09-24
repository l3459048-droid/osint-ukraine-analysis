Option Explicit
Dim shell, fso, root, bat
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
bat = Chr(34) & root & "\start_local.bat" & Chr(34)
shell.Run bat, 0, False
