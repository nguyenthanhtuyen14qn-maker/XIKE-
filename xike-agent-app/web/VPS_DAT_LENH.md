# Đặt lệnh MT5 từ app — phần cần thêm trên VPS

> Code đầy đủ của cầu nối (đăng nhập, xem, đặt lệnh) nằm ở `../vps/server.py`, hướng dẫn cài ở `../vps/HUONG_DAN_VPS.md`.

Trang `ai_1.html` (tab Biểu đồ → nút **Đặt lệnh**, khung ngay dưới biểu đồ) gửi lệnh tới cùng VPS
đang dùng cho `/health`, `/account`, `/positions`, `/history`, cùng header `X-Token`.
VPS hiện tại chỉ có các cổng đọc, nên cần thêm 2 cổng dưới đây. Chưa có thì app báo
"VPS chưa có cổng /order".

## Chốt an toàn phía app
- Tắt sẵn mỗi lần mở app; phải tích "Bật đặt lệnh".
- Bắt buộc SL; TP phải nằm đúng phía SL; khi có nến live thì SL/TP phải đúng phía giá hiện tại.
- Lot không vượt "Lot tối đa mỗi lệnh" (mặc định 0.10), bước 0.01.
- Bấm BUY/SELL hai lần trong 6 giây; đổi bất kỳ ô nào thì phải bấm lại từ đầu.
- Lỗi mạng hoặc hết giờ: KHÔNG tự gửi lại, báo xem lại lệnh đang mở.
- Mỗi lệnh có `client_id` riêng để VPS chặn gửi trùng.

**VPS vẫn phải tự kiểm tra lại** (lot tối đa, mã cho phép, SL bắt buộc), vì ai có token đều gọi được API.

## POST /order
Body:
```json
{"client_id":"xk1abc","symbol":"XAUUSD","side":"BUY","volume":0.02,"sl":2390,"tp":2420,"comment":"XIKE"}
```
`tp` = 0 nghĩa là không đặt TP.
Trả về 200: `{"ok":true,"ticket":123456,"price":2401.2,"retcode":10009}`
Lỗi: mã 4xx/5xx hoặc `{"ok":false,"error":"...","retcode":10016}`. 401 khi sai token.

## POST /close
Body: `{"ticket":123456,"client_id":"xk1def"}` → `{"ok":true,"price":2405.1}`

`/positions` cần trả thêm trường `ticket` cho mỗi lệnh thì app mới hiện nút "Đóng".

## Code mẫu (Python, gói MetaTrader5)
Ghép vào server hiện có trên VPS (Flask/FastAPI...), kiểm tra token như các cổng khác.

```python
import MetaTrader5 as mt5

MAX_LOT = 0.10                 # giới hạn cứng trên VPS
ALLOWED = {"XAUUSD"}           # đổi theo tên mã của broker (vd XAUUSDm)
_seen = {}                     # client_id -> kết quả, chặn gửi trùng

def place_order(b):
    cid = str(b.get("client_id", ""))[:40]
    if cid and cid in _seen:
        return 200, _seen[cid]
    sym, side = str(b.get("symbol", "")).upper(), b.get("side")
    vol, sl, tp = float(b.get("volume", 0)), float(b.get("sl", 0)), float(b.get("tp", 0) or 0)
    if sym not in ALLOWED: return 400, {"ok": False, "error": "Mã không được phép"}
    if side not in ("BUY", "SELL"): return 400, {"ok": False, "error": "Hướng lệnh sai"}
    if not (0 < vol <= MAX_LOT): return 400, {"ok": False, "error": "Lot vượt giới hạn VPS"}
    if sl <= 0: return 400, {"ok": False, "error": "Thiếu SL"}
    if not mt5.symbol_select(sym, True): return 503, {"ok": False, "error": "Không chọn được mã"}
    tick = mt5.symbol_info_tick(sym)
    buy = side == "BUY"
    price = tick.ask if buy else tick.bid
    if (buy and sl >= price) or (not buy and sl <= price):
        return 400, {"ok": False, "error": "SL sai phía giá hiện tại"}
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": vol,
        "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
        "price": price, "sl": sl, "tp": tp, "deviation": 30, "magic": 14014,
        "comment": str(b.get("comment", "XIKE"))[:20],
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    if r is None: return 503, {"ok": False, "error": "MT5 không phản hồi", "detail": str(mt5.last_error())}
    if r.retcode != mt5.TRADE_RETCODE_DONE:
        return 400, {"ok": False, "error": r.comment, "retcode": r.retcode}
    out = {"ok": True, "ticket": r.order, "price": r.price, "retcode": r.retcode}
    if cid: _seen[cid] = out
    return 200, out

def close_position(b):
    ps = mt5.positions_get(ticket=int(b.get("ticket", 0)))
    if not ps: return 404, {"ok": False, "error": "Không tìm thấy lệnh"}
    p = ps[0]
    tick = mt5.symbol_info_tick(p.symbol)
    is_buy = p.type == mt5.POSITION_TYPE_BUY
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "position": p.ticket,
        "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if is_buy else tick.ask, "deviation": 30, "magic": 14014,
        "comment": "XIKE close", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return 400, {"ok": False, "error": getattr(r, "comment", "MT5 không phản hồi"), "retcode": getattr(r, "retcode", 0)}
    return 200, {"ok": True, "price": r.price}
```
Nếu broker báo lỗi filling (retcode 10030) thì đổi `ORDER_FILLING_IOC` thành `ORDER_FILLING_FOK` hoặc `ORDER_FILLING_RETURN`.
Nên thử trên tài khoản demo trước.
