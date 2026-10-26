@echo off
chcp 65001 >nul
title Rin Virtual Companion
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.main
pause
