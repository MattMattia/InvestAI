' InvestAI Enterprise - Silent Zero-Console Launcher
Option Explicit
Dim objShell, objFSO, strRootDir, strPsScript, strCmd
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")
strRootDir = objFSO.GetParentFolderName(objFSO.GetParentFolderName(WScript.ScriptFullName))
objShell.CurrentDirectory = strRootDir
strPsScript = objFSO.BuildPath(strRootDir, "scripts\launch_investai.ps1")
strCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Sta -File """ & strPsScript & """"
' 0 = Hide window completely, False = Do not block WScript
objShell.Run strCmd, 0, False
