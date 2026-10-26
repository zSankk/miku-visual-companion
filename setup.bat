@echo off
:: Mantenha este arquivo somente em ASCII (sem acentos/emoji): o cmd.exe le
:: .bat no codepage do console e quebra o parse com UTF-8 multibyte.
setlocal
title Miku Visual Companion - Instalacao e Configuracao
cd /d "%~dp0"

echo =====================================================================
echo           Configuracao Inicial - Miku Visual Companion
echo =====================================================================
echo.

:: 1. Verifica instalacao do Python
where python >nul 2>&1
if errorlevel 1 goto :no_python

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%i"
echo [INFO] Detectado: %PYTHON_VERSION%
echo.

:: 2. Cria ambiente virtual se nao existir
if exist ".venv\Scripts\python.exe" goto :venv_exists
echo [INFO] Criando ambiente virtual .venv ...
python -m venv .venv
if errorlevel 1 goto :venv_failed
echo [OK] Ambiente virtual criado com sucesso.
goto :venv_done
:venv_exists
echo [INFO] Ambiente virtual .venv ja existe.
:venv_done
echo.

:: 3. Atualiza pip e instala dependencias
echo [INFO] Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo [INFO] Instalando dependencias do requirements.txt ...
echo Isso pode levar alguns minutos na primeira execucao...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
echo [OK] Dependencias instaladas com sucesso.
echo.

:: 4. Baixa os pesos da voz da Miku (RVC local, ~930 MB, somente na primeira vez)
echo [INFO] Baixando pesos da voz da Miku - cerca de 930 MB na primeira vez...
".venv\Scripts\python.exe" scripts\download_miku_models.py
if errorlevel 1 goto :voice_failed
echo [OK] Voz da Miku instalada.
goto :voice_done
:voice_failed
echo [AVISO] Nao foi possivel baixar a voz da Miku. O app vai usar a voz reserva do Edge-TTS.
echo Para tentar de novo, execute o setup.bat novamente.
:voice_done
echo.

:: 5. Cria arquivo .env a partir do .env.example se nao existir
if exist ".env" goto :env_exists
if not exist ".env.example" goto :env_example_missing
copy ".env.example" ".env" >nul
echo [OK] Arquivo .env gerado a partir de .env.example.
echo [DICA] Voce pode adicionar sua GEMINI_API_KEY no arquivo .env ou pelo botao "Chave de API" na interface da Miku.
goto :env_done
:env_example_missing
echo [AVISO] Arquivo .env.example nao foi encontrado.
goto :env_done
:env_exists
echo [INFO] Arquivo .env ja existe.
:env_done
echo.

echo =====================================================================
echo [SUCESSO] Instalacao concluida com sucesso!
echo Para iniciar a Miku, basta dar dois cliques no arquivo "run.bat".
echo =====================================================================
echo.
pause
exit /b 0

:no_python
echo [ERRO] Python nao foi encontrado no PATH do sistema.
echo Por favor, instale o Python 3.10+ em https://www.python.org/downloads/
echo e lembre-se de marcar a opcao "Add Python to PATH" durante a instalacao.
echo.
pause
exit /b 1

:venv_failed
echo [ERRO] Falha ao criar o ambiente virtual .venv.
pause
exit /b 1

:pip_failed
echo.
echo [ERRO] Falha ao instalar dependencias do requirements.txt.
echo Role a janela para cima para ver a mensagem de erro do pip.
pause
exit /b 1
