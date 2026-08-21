@echo off
chcp 65001 >nul
echo Dang tat TTS Studio...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>&1
echo Da tat.
timeout /t 2 /nobreak >nul
