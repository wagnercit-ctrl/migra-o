@echo off
REM Abre o painel com dados ficticios (antes de liberar o acesso a Meta).
cd /d "%~dp0"
python painel\gerar_painel.py --demo --abrir
if errorlevel 1 pause
