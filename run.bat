@echo off
chcp 65001 >nul
title Miku Visual Companion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual não encontrado.
    echo Por favor, execute primeiro o arquivo "setup.bat" para instalar o projeto.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m src.main
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [AVISO] A aplicação encerrou com código de erro %ERRORLEVEL%.
    pause
)
