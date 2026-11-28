#!/usr/bin/env bash
# Cầu nối XIKE ↔ Exness Trader API (chạy được trên VPS Linux, không cần MT5)
cd "$(dirname "$0")"
export XIKE_MODE=exness
export XIKE_TOKEN="DOI-CHUOI-NAY-THANH-TOKEN-DAI-NGAU-NHIEN"   # giống ô Token trong app, >= 24 ký tự
export XIKE_SYMBOLS="XAUUSDm"      # Standard: XAUUSDm · Pro/Raw/Zero: XAUUSD
export XIKE_MAX_LOT="0.10"
export XIKE_PORT="8787"
export EXN_API_KEY="exnsk-..."                 # API key tạo trong Key Management
export EXN_ACCOUNT_ID="12345678"               # số tài khoản giao dịch
export EXN_GATEWAY="https://..."               # Gateway URL lấy ở trang tài liệu Exness API
export EXN_PRIVATE_KEY_FILE="$HOME/.xike/exness_private.pem"   # khoá riêng, chmod 600, KHÔNG gửi ai
python3 server.py
