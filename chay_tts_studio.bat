@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Neu server dang chay roi -> chi mo trinh duyet, khong loi port
netstat -ano | findstr :5000 | findstr LISTENING >nul 2>&1
if %errorlevel%==0 (
    start "" http://127.0.0.1:5000/
    exit /b
)

rem Khoi dong AN (pythonw = khong cua so terminal), roi mo trinh duyet
start "" /b pythonw.exe app.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5000/
exit /b
