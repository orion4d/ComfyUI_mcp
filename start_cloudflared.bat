@echo off
REM ============================================================
REM  Cloudflare Tunnel - Quick Tunnel
REM ============================================================
title Cloudflare Tunnel

echo.
echo ============================================================
echo   Cloudflare Tunnel - Demarrage
echo ============================================================
echo.
echo Port local : 3333 (Serveur MCP)
echo.
echo ATTENTION : Notez bien l'URL qui s'affichera !
echo Elle sera au format : https://xxx-yyy-zzz.trycloudflare.com
echo.
echo ============================================================
echo.

REM Pas besoin de cd, cloudflared est dans le PATH !
cloudflared tunnel --url http://localhost:3333

echo.
echo Le tunnel s'est arrete.
pause
