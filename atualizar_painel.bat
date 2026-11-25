@echo off
REM Puxa os dados da Meta e abre o painel atualizado.
cd /d "%~dp0"
python painel\gerar_painel.py --abrir
if errorlevel 1 pause
