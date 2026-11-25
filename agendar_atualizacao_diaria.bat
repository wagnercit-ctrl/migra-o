@echo off
REM Agenda a atualizacao do painel todo dia as 07:00 (Agendador de Tarefas do Windows).
cd /d "%~dp0"
schtasks /Create /F /SC DAILY /ST 07:00 /TN "Painel Carla Nunes - Meta" /TR "python \"%~dp0painel\gerar_painel.py\""
echo.
echo Pronto. Para remover: schtasks /Delete /TN "Painel Carla Nunes - Meta" /F
pause
