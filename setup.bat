@echo off
chcp 65001 >nul
title Miku Visual Companion - Instalação e Configuração
cd /d "%~dp0"

echo =====================================================================
echo           Configuração Inicial · Miku Visual Companion
echo =====================================================================
echo.

:: 1. Verifica instalação do Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python não foi encontrado no PATH do sistema.
    echo Por favor, instale o Python 3.10+ em https://www.python.org/downloads/
    echo e lembre-se de marcar a opção "Add Python to PATH" durante a instalação.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [INFO] Detectado: %PYTHON_VERSION%
echo.

:: 2. Cria ambiente virtual se não existir
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Criando ambiente virtual (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERRO] Falha ao criar o ambiente virtual .venv.
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado com sucesso.
) else (
    echo [INFO] Ambiente virtual .venv já existe.
)
echo.

:: 3. Atualiza pip e instala dependências
echo [INFO] Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo [INFO] Instalando dependências (requirements.txt)...
echo Isso pode levar alguns minutos na primeira execução...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao instalar dependências do requirements.txt.
    pause
    exit /b 1
)
echo [OK] Dependências instaladas com sucesso.
echo.

:: 4. Cria arquivo .env a partir do .env.example se não existir
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [OK] Arquivo .env gerado a partir de .env.example.
        echo [IMPORTANTE] Abra o arquivo .env e adicione sua GEMINI_API_KEY gratuita!
    ) else (
        echo [AVISO] Arquivo .env.example não foi encontrado.
    )
) else (
    echo [INFO] Arquivo .env já existe.
)
echo.

echo =====================================================================
echo [SUCESSO] Instalação concluída com sucesso!
echo Para iniciar a Miku, basta dar dois cliques no arquivo "run.bat".
echo =====================================================================
echo.
pause
