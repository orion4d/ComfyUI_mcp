@echo off

REM ============================================================
REM Serveur MCP ComfyUI - Script de démarrage
REM ============================================================

title Serveur MCP ComfyUI

REM Définir le dossier du projet
cd /d D:\serveur_mcp-comfyui

REM Afficher l'en-tête
echo.
echo ============================================================
echo Serveur MCP ComfyUI - Demarrage
echo ============================================================
echo.

echo [1/3] Verification de l'environnement virtuel...

REM Vérifier si le venv existe
if not exist "venv\Scripts\activate.bat" (
    echo ERREUR: L'environnement virtuel n'existe pas!
    echo Veuillez creer le venv avec: python -m venv venv
    echo.
    pause
    exit /b 1
)

echo [OK] Environnement virtuel trouve
echo.

echo [2/3] Activation de l'environnement virtuel...
REM Activer le venv
call venv\Scripts\activate.bat
echo [OK] Environnement virtuel active
echo.

echo [3/3] Demarrage du serveur MCP...
echo.
echo ============================================================
echo Serveur MCP lance sur http://127.0.0.1:8000
echo Endpoint MCP : http://127.0.0.1:8000/mcp
echo ============================================================
echo.
echo Appuyez sur Ctrl+C pour arreter le serveur
echo.

REM Lancer uvicorn (fichiers à la racine maintenant)
uvicorn server:app --host 127.0.0.1 --port 8000 --reload

REM Si uvicorn se termine, garder la fenêtre ouverte
echo.
echo Le serveur s'est arrete.
pause
