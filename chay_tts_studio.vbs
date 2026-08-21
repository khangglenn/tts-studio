' TTS Studio - khoi dong AN TOAN TRUC (khong hien cua so nao)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Khang\Desktop\tts-studio"

' Neu server dang chay (port 5000) -> chi mo trinh duyet
Set exec = WshShell.Exec("cmd /c netstat -ano | findstr :5000 | findstr LISTENING")
WScript.Sleep 500
If exec.StdOut.AtEndOfStream Then
    WshShell.Run "pythonw.exe app.py", 0, False
    WScript.Sleep 2000
End If
WshShell.Run "http://127.0.0.1:5000/", 1, False
