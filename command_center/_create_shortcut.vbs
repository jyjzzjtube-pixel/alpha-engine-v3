Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDesktop = WshShell.SpecialFolders("Desktop")
strBase = fso.GetParentFolderName(WScript.ScriptFullName)
strBase = fso.GetParentFolderName(strBase)
strLnk = strDesktop & "\YJ Command Center.lnk"
Set shortcut = WshShell.CreateShortcut(strLnk)
shortcut.TargetPath = strBase & "\command_center\START.bat"
shortcut.WorkingDirectory = strBase
shortcut.IconLocation = strBase & "\command_center\icon.ico,0"
shortcut.WindowStyle = 7
shortcut.Description = "YJ Partners Command Center"
shortcut.Save
WScript.Echo "Shortcut created: " & strLnk
