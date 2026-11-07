Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
WshShell.CurrentDirectory = projectDir
WshShell.Run Chr(34) & projectDir & "\start_server.bat" & Chr(34) & " --silent", 0, False
