"""XIKE MT5 Bridge — cầu nối giữa app XIKE và MetaTrader 5 trên VPS Windows.

Cổng (mọi cổng cần header X-Token, trừ OPTIONS):
  GET  /health            trạng thái MT5
  POST /login             đăng nhập tài khoản MT5 {login, password, server}
  POST /logout            ngắt MT5
  GET  /account           số dư, vốn, ký quỹ
  GET  /positions         lệnh đang mở
  GET  /history?days=7    lệnh đã đóng
  POST /order             đặt lệnh thị trường
  POST /close             đóng lệnh theo ticket

Chạy:  set XIKE_TOKEN=chuoi-dai-ngau-nhien  &&  python server.py
"""
import hmac
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

import MetaTrader5 as mt5

TOKEN = os.environ.get("XIKE_TOKEN", "").strip()
MT5_PATH = os.environ.get("MT5_PATH", "").strip()            # đường dẫn terminal64.exe, để trống = tự tìm
PORT = int(os.environ.get("XIKE_PORT", "8787"))
HOST = os.environ.get("XIKE_HOST", "127.0.0.1")               # 127.0.0.1 khi dùng Cloudflare Tunnel / Caddy
MAX_LOT = float(os.environ.get("XIKE_MAX_LOT", "0.10"))
ALLOWED = {s.strip().upper() for s in os.environ.get("XIKE_SYMBOLS", "XAUUSD").split(",") if s.strip()}
MAGIC = 14014
HIST_LIMIT = 50

app = Flask(__name__)
LOCK = threading.Lock()          # thư viện MetaTrader5 không an toàn khi gọi song song
SEEN = {}                        # client_id -> kết quả, chặn gửi trùng
LOGIN_FAILS = []                 # thời điểm đăng nhập sai, chặn đoán mật khẩu


def ok(data, code=200):
    return jsonify(data), code


def err(msg, code=400, **extra):
    body = {"ok": False, "error": msg}
    body.update(extra)
    return jsonify(body), code


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "X-Token, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.before_request
def check_token():
    if request.method == "OPTIONS":
        return ("", 204)
    got = request.headers.get("X-Token", "")
    if not hmac.compare_digest(got.encode(), TOKEN.encode()):
        return err("Sai token", 401)
    return None


def body():
    return request.get_json(silent=True) or {}


def mt5_error():
    code, text = mt5.last_error()
    return f"{code} {text}"


def ensure_mt5():
    """Mở kết nối tới terminal MT5 nếu chưa có. Trả về chuỗi lỗi hoặc None."""
    if mt5.terminal_info() is not None:
        return None
    started = mt5.initialize(path=MT5_PATH) if MT5_PATH else mt5.initialize()
    if not started:
        return "Không mở được MT5 (" + mt5_error() + ")"
    return None


def need_account():
    """Dùng cho các cổng cần đã đăng nhập. Trả về (None, info) hoặc (response lỗi, None)."""
    e = ensure_mt5()
    if e:
        return err("MT5 chưa sẵn sàng", 503, detail=e), None
    info = mt5.account_info()
    if info is None or not info.login:
        return err("Chưa đăng nhập tài khoản MT5", 503, detail="Vào app, mục Đăng nhập MT5"), None
    term = mt5.terminal_info()
    if term is not None and not term.connected:
        return err("MT5 mất kết nối tới server broker", 503, detail=info.server), None
    return None, info


def account_dict(a):
    return {
        "login": a.login, "name": a.name, "server": a.server, "currency": a.currency,
        "balance": a.balance, "equity": a.equity, "margin": a.margin,
        "margin_free": a.margin_free, "profit": a.profit, "leverage": a.leverage,
        "trade_allowed": bool(a.trade_allowed),
    }


@app.get("/health")
def health():
    with LOCK:
        e = ensure_mt5()
        if e:
            return err("MT5 chưa sẵn sàng", 503, detail=e)
        ver = mt5.version() or (0, 0, "")
        term = mt5.terminal_info()
        acc = mt5.account_info()
        return ok({
            "ok": True, "build": ver[1],
            "connected": bool(term and term.connected),
            "trade_allowed": bool(term and term.trade_allowed),     # nút Algo Trading
            "login": acc.login if acc else 0,
            "server": acc.server if acc else "",
        })


@app.post("/login")
def login():
    b = body()
    now = time.time()
    LOGIN_FAILS[:] = [t for t in LOGIN_FAILS if now - t < 600]
    if len(LOGIN_FAILS) >= 5:
        return err("Sai quá nhiều lần, thử lại sau 10 phút", 429)
    try:
        acc_no = int(str(b.get("login", "")).strip())
    except ValueError:
        return err("Số tài khoản phải là số")
    password = str(b.get("password", ""))
    server = str(b.get("server", "")).strip()
    if acc_no <= 0 or not password or not server:
        return err("Cần đủ số tài khoản, mật khẩu và server")
    with LOCK:
        e = ensure_mt5()
        if e:
            return err("MT5 chưa sẵn sàng", 503, detail=e)
        if not mt5.login(acc_no, password=password, server=server, timeout=20000):
            LOGIN_FAILS.append(now)
            return err("Đăng nhập thất bại: " + mt5_error() + ". Kiểm tra số tài khoản, mật khẩu, tên server", 400)
        a = mt5.account_info()
        term = mt5.terminal_info()
    if a is None:
        return err("Đã đăng nhập nhưng chưa đọc được tài khoản", 503, detail=mt5_error())
    out = account_dict(a)
    out.update({"ok": True, "algo_trading": bool(term and term.trade_allowed)})
    return ok(out)


@app.post("/logout")
def logout():
    with LOCK:
        mt5.shutdown()
    return ok({"ok": True})


@app.get("/account")
def account():
    with LOCK:
        bad, a = need_account()
        if bad:
            return bad
        return ok(account_dict(a))


@app.get("/positions")
def positions():
    with LOCK:
        bad, _ = need_account()
        if bad:
            return bad
        ps = mt5.positions_get() or ()
    return ok([{
        "ticket": p.ticket, "symbol": p.symbol,
        "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        "volume": p.volume, "price_open": p.price_open, "price_current": p.price_current,
        "sl": p.sl, "tp": p.tp, "profit": p.profit, "swap": p.swap, "time": p.time,
    } for p in ps])


@app.get("/history")
def history():
    try:
        days = max(1, min(90, int(request.args.get("days", "7"))))
    except ValueError:
        days = 7
    with LOCK:
        bad, a = need_account()
        if bad:
            return bad
        end = datetime.now(timezone.utc) + timedelta(days=1)
        deals = mt5.history_deals_get(end - timedelta(days=days + 1), end) or ()
    opens, closes = {}, []
    for d in deals:
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue                                   # bỏ nạp/rút tiền
        if d.entry == mt5.DEAL_ENTRY_IN:
            opens[d.position_id] = d
        elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT):
            closes.append(d)
    trades, net_all = [], 0.0
    for d in closes:
        o = opens.get(d.position_id)
        net = d.profit + d.commission + d.swap + getattr(d, "fee", 0.0)
        if o is not None:
            net += o.commission + getattr(o, "fee", 0.0)
        net_all += net
        trades.append({
            "ticket": d.position_id, "symbol": d.symbol,
            # deal đóng ngược chiều lệnh: deal SELL đóng lệnh BUY
            "side": "BUY" if d.type == mt5.DEAL_TYPE_SELL else "SELL",
            "volume": d.volume, "price_in": o.price if o else 0, "price_out": d.price,
            "net": round(net, 2), "time_out": d.time,
        })
    trades.sort(key=lambda t: t["time_out"], reverse=True)
    return ok({"count": len(trades), "net": round(net_all, 2), "currency": a.currency, "trades": trades[:HIST_LIMIT]})


def filling_for(sym_info):
    # Chọn kiểu khớp lệnh broker cho phép (bit 1 = FOK, bit 2 = IOC)
    fm = getattr(sym_info, "filling_mode", 0)
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def remember(cid, result):
    if cid:
        SEEN[cid] = result
        if len(SEEN) > 500:
            for k in list(SEEN)[:250]:
                SEEN.pop(k, None)


@app.post("/order")
def order():
    b = body()
    cid = str(b.get("client_id", ""))[:40]
    if cid and cid in SEEN:
        return ok(SEEN[cid])
    sym = str(b.get("symbol", "")).strip().upper()
    side = b.get("side")
    try:
        vol = round(float(b.get("volume", 0)), 2)
        sl = float(b.get("sl", 0))
        tp = float(b.get("tp", 0) or 0)
    except (TypeError, ValueError):
        return err("Số liệu lệnh không hợp lệ")
    if sym not in ALLOWED:
        return err("Mã " + sym + " không được phép trên VPS (XIKE_SYMBOLS)")
    if side not in ("BUY", "SELL"):
        return err("Hướng lệnh phải là BUY hoặc SELL")
    if not (0 < vol <= MAX_LOT):
        return err(f"Lot phải trong khoảng 0.01 – {MAX_LOT} (giới hạn VPS)")
    if sl <= 0:
        return err("Thiếu SL")
    with LOCK:
        bad, a = need_account()
        if bad:
            return bad
        term = mt5.terminal_info()
        if not (term and term.trade_allowed):
            return err("MT5 đang tắt Algo Trading. Bật nút Algo Trading trên VPS.", 503)
        if not mt5.symbol_select(sym, True):
            return err("Không chọn được mã " + sym, 503, detail=mt5_error())
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info is None or tick is None:
            return err("Không có giá cho " + sym, 503)
        buy = side == "BUY"
        price = tick.ask if buy else tick.bid
        if (buy and sl >= price) or (not buy and sl <= price):
            return err(f"SL sai phía giá hiện tại {price}")
        if tp and ((buy and tp <= price) or (not buy and tp >= price)):
            return err(f"TP sai phía giá hiện tại {price}")
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": vol,
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
            "price": price, "sl": sl, "tp": tp, "deviation": 30, "magic": MAGIC,
            "comment": str(b.get("comment", "XIKE"))[:20],
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_for(info),
        }
        r = mt5.order_send(req)
    if r is None:
        return err("MT5 không phản hồi", 503, detail=mt5_error())
    if r.retcode != mt5.TRADE_RETCODE_DONE:
        return err(r.comment or "Lệnh bị từ chối", 400, retcode=r.retcode)
    out = {"ok": True, "ticket": r.order, "price": r.price, "retcode": r.retcode}
    remember(cid, out)
    return ok(out)


@app.post("/close")
def close():
    b = body()
    cid = str(b.get("client_id", ""))[:40]
    if cid and cid in SEEN:
        return ok(SEEN[cid])
    try:
        ticket = int(b.get("ticket", 0))
    except (TypeError, ValueError):
        return err("Ticket không hợp lệ")
    with LOCK:
        bad, _ = need_account()
        if bad:
            return bad
        ps = mt5.positions_get(ticket=ticket)
        if not ps:
            return err("Không tìm thấy lệnh #" + str(ticket), 404)
        p = ps[0]
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "position": p.ticket,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask, "deviation": 30, "magic": MAGIC,
            "comment": "XIKE close", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_for(info),
        }
        r = mt5.order_send(req)
    if r is None:
        return err("MT5 không phản hồi", 503, detail=mt5_error())
    if r.retcode != mt5.TRADE_RETCODE_DONE:
        return err(r.comment or "Không đóng được lệnh", 400, retcode=r.retcode)
    out = {"ok": True, "price": r.price}
    remember(cid, out)
    return ok(out)


def main():
    if len(TOKEN) < 24:
        raise SystemExit("Đặt biến XIKE_TOKEN dài ít nhất 24 ký tự trước khi chạy.")
    with LOCK:
        e = ensure_mt5()
    print("MT5:", e or "đã kết nối terminal")
    print(f"XIKE MT5 Bridge chạy ở http://{HOST}:{PORT}  (mã cho phép: {', '.join(sorted(ALLOWED))}, lot tối đa {MAX_LOT})")
    from waitress import serve
    serve(app, host=HOST, port=PORT, threads=4)


if __name__ == "__main__":
    main()
