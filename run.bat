@echo off
:: Mantenha este arquivo somente em ASCII (sem acentos/emoji): o cmd.exe le
:: .bat no codepage do console e quebra o parse com UTF-8 multibyte.
setlocal
title Miku Visual Companion
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :run
echo [ERRO] Ambiente virtual nao encontrado.
echo Por favor, execute primeiro o arquivo "setup.bat" para instalar o projeto.
echo.
pause
exit /b 1

:run
".venv\Scripts\python.exe" -m src.main
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="0" exit /b 0
echo.
echo [AVISO] A aplicacao encerrou com codigo de erro %APP_EXIT%.
pause
exit /b %APP_EXIT%
