@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Atualizacao das Bases de Dados Oracle
echo ==============================================================================
echo   ATUALIZACAO DAS BASES ORACLE
echo ==============================================================================
echo.

cd /d "%~dp0"

echo Escolha o modo de execucao:
echo [1] Simular execucao (Dry-Run) para TODOS os sistemas
echo [2] Executar producao para TODOS os sistemas
echo [3] Executar para um sistema especifico (digitar sigla)
echo [4] Retomar producao a partir de um sistema
echo [5] Sair
echo.

set /p OPCAO="Digite a opcao desejada [1-5]: "

rem Modo teste: pergunta apenas para execucoes reais (nao dry-run, nao sair).
set TESTEFLAG=
if not "%OPCAO%"=="1" if not "%OPCAO%"=="5" (
    set /p MODOTESTE="Executar em MODO TESTE (sufixo nos arquivos .dmp/.dmp.gz/.log)? [s/N]: "
    if /i "!MODOTESTE!"=="s" (
        set TESTEFLAG=--teste
        echo Modo teste ATIVO: os arquivos enviados/gerados no Oracle usarao o sufixo de teste.
    )
)

if "%OPCAO%"=="1" (
    py main.py --all --dry-run
) else if "%OPCAO%"=="2" (
    py main.py --all !TESTEFLAG!
) else if "%OPCAO%"=="3" (
    set /p SIS="Digite a sigla do sistema (ex: VENDAS): "
    py main.py --sistema !SIS! !TESTEFLAG!
) else if "%OPCAO%"=="4" (
    set /p SIS="Digite a sigla a partir de onde continuar (ex: FINANCEIRO): "
    py main.py --all --from !SIS! !TESTEFLAG!
) else (
    echo Saindo...
    exit /b 0
)

echo.
echo Pressione qualquer tecla para encerrar...
pause >nul
