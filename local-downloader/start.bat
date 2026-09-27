@echo off
chcp 65001 >nul
cd /d "%~dp0"
title VideoVault 本地下載站
python server.py
if errorlevel 1 pause
