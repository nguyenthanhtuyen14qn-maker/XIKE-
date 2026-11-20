@echo off
chcp 65001 >nul
cd /d %~dp0
REM Doi chuoi duoi day thanh token cua ban (it nhat 24 ky tu, giong o Token trong app)
set XIKE_TOKEN=DOI-CHUOI-NAY-THANH-TOKEN-DAI-NGAU-NHIEN
set XIKE_SYMBOLS=XAUUSD
set XIKE_MAX_LOT=0.10
set XIKE_PORT=8787
REM Neu MT5 khong tu mo duoc, dien duong dan terminal64.exe:
REM set MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
python server.py
pause
