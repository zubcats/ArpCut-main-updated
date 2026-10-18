Set sh = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = folder
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & folder & "\Launch-ZubLock.ps1""", 0, False
