@echo off

REM ============================================================
REM Cloudflare Tunnel - Tunnel Permanent MCP
REM ============================================================

title Cloudflare Tunnel - MCP Permanent

echo.
echo ============================================================
echo Cloudflare Tunnel - Demarrage du tunnel permanent
echo ============================================================
echo.
echo Port local : 8000 (Serveur MCP)
echo.
echo L'URL permanente est configuree dans votre compte Cloudflare.
echo (Exemple : https://bridge-77.creanode.eu)
echo.
echo Ce script va maintenant demarrer le tunnel nomme.
echo ============================================================
echo.

REM Demarrer le tunnel permanent en utilisant le fichier config.yml
REM La commande "run" va automatiquement trouver votre config.yml
REM si vous lancez ce .bat depuis le bon endroit, ou si le
REM fichier est dans C:\Users\VotreNom\.cloudflared\
cloudflared tunnel run

echo.
echo Le tunnel s'est arrete.
pause