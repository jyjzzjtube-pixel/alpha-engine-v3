import win32com.client
import os

shell = win32com.client.Dispatch("WScript.Shell")

base = r"C:\Users\jyjzz\OneDrive\바탕 화면"
project = os.path.join(base, "franchise-db")
shortcut_path = os.path.join(base, "YJ Command Center.lnk")

shortcut = shell.CreateShortCut(shortcut_path)
shortcut.TargetPath = os.path.join(project, r"AI_Command_Center\venv\Scripts\pythonw.exe")
shortcut.Arguments = "-m command_center.main"
shortcut.WorkingDirectory = project
shortcut.IconLocation = os.path.join(project, r"command_center\icon.ico") + ", 0"
shortcut.Description = "YJ Partners Command Center"
shortcut.WindowStyle = 1
shortcut.Save()

if os.path.exists(shortcut_path):
    size = os.path.getsize(shortcut_path)
    print(f"Shortcut created successfully: {shortcut_path}")
    print(f"File size: {size} bytes")
    print(f"Target: {shortcut.TargetPath}")
    print(f"Arguments: {shortcut.Arguments}")
    print(f"Working Dir: {shortcut.WorkingDirectory}")
    print(f"Icon: {shortcut.IconLocation}")
else:
    print("ERROR: Shortcut was not created!")
