@echo off
chcp 65001 >nul
cd /d %~dp0
REM Cau noi XIKE - Exness Trader API (khong can MT5)
set XIKE_MODE=exness
set XIKE_TOKEN=DOI-CHUOI-NAY-THANH-TOKEN-DAI-NGAU-NHIEN
set XIKE_SYMBOLS=XAUUSDm
set XIKE_MAX_LOT=0.10
set XIKE_PORT=8787
set EXN_API_KEY=exnsk-...
set EXN_ACCOUNT_ID=12345678
set EXN_GATEWAY=https://...
REM File khoa rieng (private key) tai tu Key Management, de tren VPS, khong gui ai
set EXN_PRIVATE_KEY_FILE=C:\xike\exness_private.pem
python server.py
pause
