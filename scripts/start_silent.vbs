Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(strPath)
WshShell.CurrentDirectory = projectDir

flagFile = projectDir & "\logs\manual_stop.flag"
If fso.FileExists(flagFile) Then
    On Error Resume Next
    fso.DeleteFile flagFile, True
    On Error Goto 0
End If

venvPy = projectDir & "\venv\Scripts\pythonw.exe"
If fso.FileExists(venvPy) Then
    pyCmd = """" & venvPy & """"
Else
    pyCmd = "pythonw.exe"
End If

WshShell.Run pyCmd & " """ & projectDir & "\server.py""", 0, False
WshShell.Run pyCmd & " """ & projectDir & "\scripts\watchdog.pyw""", 0, False
