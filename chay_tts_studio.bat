@echo off
chcp 65001 >nul
title TTS Studio - Giong Ngoc Huyen
cd /d "%~dp0"
echo.
echo  ============================================
echo   TTS Studio - Giong Ngoc Huyen (Piper)
echo   Dang khoi dong server...
echo  ============================================
echo.
python app.py
echo.
echo Server da dung.
pause