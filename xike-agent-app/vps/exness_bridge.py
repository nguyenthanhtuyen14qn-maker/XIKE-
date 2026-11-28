"""Exness Trader API cho cầu nối XIKE (chế độ XIKE_MODE=exness).

Làm theo tài liệu https://www.exness-api.com (bản 19/11/2026):
- Ký mỗi request bằng Ed25519: payload JSON {api_key, idempotency_key, timestamp, sign_version, method,
  path, body_hash} (không khoảng trắng), EXN-DATA = base64url(payload), EXN-SIGN = base64url(chữ ký).
- Tìm Access Point của tài khoản qua Gateway rồi gửi mọi request tài khoản tới Access Point.
- Lệnh giao dịch trả về 202 (đã nhận) rồi mới khớp: hỏi trạng thái operation cho tới khi xong.

Khoá bí mật chỉ nằm trên VPS (biến môi trường), không bao giờ gửi về app.

Biến môi trường:
  EXN_API_KEY        mã khoá API (EXN-API-KEY)
  EXN_PRIVATE_KEY    khoá ký: 128 ký tự hex do Exness tạo, hoặc PEM PKCS#8
  EXN_PRIVATE_KEY_FILE  (tuỳ chọn) đường dẫn file chứa khoá ký, thay cho EXN_PRIVATE_KEY
  EXN_ACCOUNT_ID     số tài khoản giao dịch
  EXN_GATEWAY        địa chỉ Gateway lấy ở mục DNS trong Key Management, dạng https://...
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

EMPTY_BODY_HASH = "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"
TF_OK = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def load_signing_key(text):
    text = text.strip()
    if text.startswith("-----BEGIN PRIVATE KEY-----"):
        key = serialization.load_pem_private_key(text.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Khoá ký phải là Ed25519")
        return key
    if not re.fullmatch(r"[0-9a-fA-F]{128}", text):
        raise ValueError("Khoá ký phải là 128 ký tự hex hoặc PEM PKCS#8")
    raw = bytes.fromhex(text)             # 32 byte seed + 32 byte khoá công khai
    key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if pub != raw[32:]:
        raise ValueError("Khoá ký không khớp nửa khoá công khai")
    return key


def sign_headers(api_key, key, method, path_with_query, body=b"", idem="", timestamp_ms=None):
    """Header EXN-* cho một request. body là đúng các byte sẽ gửi đi."""
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    payload = json.dumps({
        "api_key": api_key,
        "idempotency_key": idem,
        "timestamp": ts,
        "sign_version": 1,
        "method": method.upper(),
        "path": path_with_query,
        "body_hash": b64url(hashlib.sha256(body).digest()),
    }, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "EXN-API-KEY": api_key,
        "EXN-IDEMPOTENCY-KEY": idem,
        "EXN-TIMESTAMP": str(ts),
        "EXN-SIGN-VERSION": "1",
        "EXN-DATA": b64url(payload),
        "EXN-SIGN": b64url(key.sign(payload)),
    }


def https_base(value):
    u = urllib.parse.urlsplit(value.strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
        raise ValueError("Địa chỉ phải là https://tên-máy không kèm đường dẫn")
    return "https://" + u.netloc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # không chuyển header đã ký sang địa chỉ khác


class ExnError(Exception):
    def __init__(self, msg, status=400, code=""):
        super().__init__(msg)
        self.status, self.code = status, code


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(s):
    s = str(s or "").replace("Z", "+00:00")
    if "." in s:   # cắt phần lẻ giây dài (nano giây)
        head, tail = s.split(".", 1)
        frac = re.match(r"\d*", tail).group(0)
        rest = tail[len(frac):]
        s = head + "." + (frac[:6] or "0") + rest
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class ExnessBridge:
    def __init__(self, env=None, opener=None):
        env = env or os.environ
        self.api_key = env.get("EXN_API_KEY", "").strip()
        key_text = env.get("EXN_PRIVATE_KEY", "")
        if not key_text and env.get("EXN_PRIVATE_KEY_FILE"):
            with open(env["EXN_PRIVATE_KEY_FILE"], encoding="utf-8") as fh:
                key_text = fh.read()
        self.account_id = env.get("EXN_ACCOUNT_ID", "").strip()
        gw = env.get("EXN_GATEWAY", "").strip()
        missing = [n for n, v in (("EXN_API_KEY", self.api_key), ("EXN_PRIVATE_KEY", key_text),
                                  ("EXN_ACCOUNT_ID", self.account_id), ("EXN_GATEWAY", gw)) if not v]
        if missing:
            raise ValueError("Thiếu biến môi trường: " + ", ".join(missing))
        if not re.fullmatch(r"[1-9][0-9]{0,19}", self.account_id):
            raise ValueError("EXN_ACCOUNT_ID phải là số tài khoản")
        self.key = load_signing_key(key_text)
        self.gateway = https_base(gw)
        self.opener = opener or urllib.request.build_opener(_NoRedirect)
        self.lock = threading.Lock()
        self.access_point = None
        self.cache = {}          # tên → (hết hạn, giá trị)

    # ---- HTTP có ký ----
    def _call(self, base, method, path, body_obj=None, idem=""):
        body = b"" if body_obj is None else json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = sign_headers(self.api_key, self.key, method, path, body, idem)
        if body_obj is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=body if body_obj is not None else None, headers=headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=20) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            code = str(data.get("code") or data.get("error_code") or "")
            msg = data.get("error_message") or data.get("message") or ("Exness trả lỗi %d" % e.code)
            if e.code == 401 or code.startswith("AUTH_"):
                msg = "Exness từ chối khoá API hoặc chữ ký (" + (code or str(e.code)) + "). Kiểm tra EXN_API_KEY, khoá ký, giờ máy VPS."
            raise ExnError(msg, e.code, code)
        except urllib.error.URLError as e:
            raise ExnError("Không kết nối được Exness: %s" % e.reason, 503)

    def _ap(self):
        if not self.access_point:
            _, data = self._call(self.gateway, "GET", "/v1/trading/access-point?account_id=" + self.account_id)
            ap = data.get("access_point")
            if not isinstance(ap, str) or not ap:
                raise ExnError("Exness không trả Access Point cho tài khoản", 503)
            self.access_point = https_base(ap)
        return self.access_point

    def get(self, path):
        return self._call(self._ap(), "GET", path)[1]

    def _cached(self, name, ttl, fn):
        now = time.time()
        hit = self.cache.get(name)
        if hit and hit[0] > now:
            return hit[1]
        val = fn()
        self.cache[name] = (now + ttl, val)
        return val

    # ---- Đọc ----
    def details(self):
        return self._cached("details", 300, lambda: self.get("/v1/configuration/accounts/%s/account" % self.account_id))

    def snapshot(self):
        return self.get("/v1/trading/accounts/%s/snapshot" % self.account_id)

    def condition(self, instrument):
        return self._cached("cond:" + instrument, 600, lambda: self.get(
            "/v1/configuration/accounts/%s/instruments/%s/conditions" % (self.account_id, urllib.parse.quote(instrument, safe=""))))

    def candles(self, instrument, tf, count, price_type="bid"):
        """Nến cũ → mới. count có thể lớn hơn giới hạn một lần gọi: lấy lùi nhiều lần."""
        if tf not in TF_OK:
            raise ExnError("Khung thời gian không hỗ trợ: " + tf)
        want = max(1, min(int(count), 5000))
        out, start = [], datetime.now(timezone.utc) + timedelta(minutes=1)
        while len(out) < want:
            n = min(1000, want - len(out))
            q = urllib.parse.urlencode({"instrument": instrument, "timeframe": tf, "price_type": price_type,
                                        "from": _iso(start), "count": str(-n)})
            data = self.get("/v1/market-data/accounts/%s/candles?%s" % (self.account_id, q))
            page = data.get("candles") or []
            if not page:
                break
            out = page + out
            first = _parse_time(page[0]["time"])
            if len(page) < n or first >= start:
                break
            start = first           # `from` của lần sau: nến cũ nhất đã có (lấy lùi, không gồm nến đó)
        # bỏ trùng theo thời gian, giữ thứ tự cũ → mới
        seen, bars = set(), []
        for c in out:
            t = int(_parse_time(c["time"]).timestamp())
            if t in seen:
                continue
            seen.add(t)
            bars.append({"t": t, "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"], "v": c.get("volume", 0)})
        bars.sort(key=lambda b: b["t"])
        return bars[-want:]

    def quote(self, instrument):
        """Giá bid/ask mới nhất (nến M1 cuối)."""
        q = urllib.parse.urlencode({"instrument": instrument, "timeframe": "M1", "price_type": "both",
                                    "from": _iso(datetime.now(timezone.utc) + timedelta(minutes=1)), "count": "-1"})
        data = self.get("/v1/market-data/accounts/%s/candles?%s" % (self.account_id, q))
        page = data.get("candles") or []
        if not page:
            raise ExnError("Không có giá cho " + instrument, 503, "MARKET_NO_QUOTES")
        c = page[-1]
        return _num(c["bid"]["close"]), _num(c["ask"]["close"])

    # ---- Ghi: gửi, rồi chờ kết quả cuối ----
    def _mutate(self, method, path, body_obj, idem):
        status, ack = self._call(self._ap(), method, path, body_obj, idem)
        op = str(ack.get("operation_id") or "")
        if not op:
            return {"status": ack.get("status", "accepted"), "operation_id": ""}
        deadline = time.time() + 10
        last = {"status": "pending", "operation_id": op}
        while time.time() < deadline:
            time.sleep(0.6)
            try:
                last = self.get("/v1/trading/accounts/%s/operations/%s" % (self.account_id, op))
            except ExnError as e:
                if e.status == 404:
                    continue
                raise
            if last.get("status") in ("confirmed", "rejected", "failed"):
                break
        return last

    def open_position(self, instrument, side, volume, sl, tp, comment, idem):
        cond = self.condition(instrument)
        digits = int(_num(cond.get("point_digits"), 2))
        step = _num(cond.get("volume_step"), 0.01) or 0.01
        vol = round(round(volume / step) * step, 8)
        if vol < _num(cond.get("volume_min"), 0.01):
            raise ExnError("Khối lượng nhỏ hơn mức tối thiểu của Exness")
        body = {"instrument": instrument, "side": side, "volume": ("%.8f" % vol).rstrip("0").rstrip("."),
                "stop_loss_price": "%.*f" % (digits, sl)}
        if tp:
            body["take_profit_price"] = "%.*f" % (digits, tp)
        if comment:
            body["comment"] = comment[:20]
        return self._mutate("POST", "/v1/trading/accounts/%s/positions" % self.account_id, body, idem)

    def close_position(self, position_id, idem):
        return self._mutate("DELETE", "/v1/trading/accounts/%s/positions/%s" % (self.account_id, position_id), None, idem)

    def deals(self, days):
        end = datetime.now(timezone.utc)
        q = urllib.parse.urlencode({"from": _iso(end - timedelta(days=days)), "to": _iso(end), "limit": "200"})
        items, path = [], "/v1/history/accounts/%s/deals?%s" % (self.account_id, q)
        for _ in range(5):
            data = self.get(path)
            items += data.get("items") or []
            cur = data.get("next_cursor")
            if not data.get("has_more") or not cur:
                break
            path = "/v1/history/accounts/%s/deals?%s" % (self.account_id, urllib.parse.urlencode({"cursor": cur, "limit": "200"}))
        return items


# ===== Các cổng cho app (trả (mã HTTP, dữ liệu) giống bản MT5) =====
def _err(msg, code=400, **extra):
    d = {"ok": False, "error": msg}
    d.update(extra)
    return code, d


def handle(bridge, route, args, body, allowed_by_key, max_lot, seen):
    try:
        with bridge.lock:
            return _route(bridge, route, args, body, allowed_by_key, max_lot, seen)
    except ExnError as e:
        status = e.status if e.status in (400, 401, 403, 404, 409, 429, 503) else 503
        if status == 401:
            status = 503       # 401 của app nghĩa là sai token VPS, không lẫn với lỗi khoá Exness
        return _err(str(e), status, exn_code=e.code)


def _acc_settings(bridge):
    d = bridge.details()
    return d, d.get("settings") or {}


def _route(b, route, args, body, allowed_by_key, max_lot, seen):
    if route == "health":
        d, st = _acc_settings(b)
        return 200, {"ok": True, "build": "Exness API", "connected": True,
                     "trade_allowed": st.get("account_status", "") not in ("disabled", "read_only", "close_only"),
                     "login": int(b.account_id), "server": "Exness API · " + (d.get("account_name") or "")}
    if route == "login":
        d, st = _acc_settings(b)
        snap = b.snapshot().get("account_state") or {}
        return 200, {"ok": True, "login": int(b.account_id), "name": d.get("account_name", ""), "server": "Exness API",
                     "currency": st.get("currency", ""), "balance": _num(snap.get("balance")), "algo_trading": True,
                     "note": "Chế độ Exness API: khoá API đã gắn với tài khoản, không cần mật khẩu MT5."}
    if route == "logout":
        return 200, {"ok": True}
    if route == "account":
        d, st = _acc_settings(b)
        s = b.snapshot().get("account_state") or {}
        bal, eq, used = _num(s.get("balance")), _num(s.get("equity")), _num(s.get("used_margin"))
        return 200, {"login": int(b.account_id), "name": d.get("account_name", ""), "server": "Exness API",
                     "currency": st.get("currency", ""), "balance": bal, "equity": eq, "margin": used,
                     "margin_free": round(eq - used, 2), "profit": round(eq - bal, 2),
                     "leverage": st.get("leverage", ""), "trade_allowed": True}
    if route == "positions":
        snap = b.snapshot()
        sltp = {}
        for o in snap.get("orders") or []:
            if o.get("order_type") == "sltp" and o.get("position_id"):
                sltp[str(o["position_id"])] = (_num(o.get("stop_loss_price")), _num(o.get("take_profit_price")))
        _, st = _acc_settings(b)
        out, quotes = [], {}
        for p in snap.get("positions") or []:
            if p.get("state") != "open":
                continue
            sym = p.get("instrument", "")
            vol, opn = _num(p.get("volume")), _num(p.get("open_price"))
            profit = None
            try:   # lãi/lỗ tạm tính: chỉ khi giá báo bằng đồng tiền của tài khoản
                cond = b.condition(sym)
                if cond.get("quote_currency") == st.get("currency"):
                    if sym not in quotes:
                        quotes[sym] = b.quote(sym)
                    bid, ask = quotes[sym]
                    cs = _num(cond.get("contract_size"), 0)
                    diff = (bid - opn) if p.get("direction") == "buy" else (opn - ask)
                    profit = round(diff * vol * cs + _num(p.get("swap")) + _num(p.get("commission")), 2)
            except ExnError:
                profit = None
            sl, tp = sltp.get(str(p.get("position_id")), (0, 0))
            out.append({"ticket": int(p["position_id"]), "symbol": sym, "type": "BUY" if p.get("direction") == "buy" else "SELL",
                        "volume": vol, "price_open": opn, "sl": sl, "tp": tp,
                        "profit": profit if profit is not None else 0, "profit_known": profit is not None,
                        "swap": _num(p.get("swap")), "time": int(_parse_time(p.get("create_time")).timestamp())})
        return 200, out
    if route == "history":
        days = max(1, min(90, int(_num(args.get("days"), 7))))
        _, st = _acc_settings(b)
        opens, closes = {}, []
        for it in b.deals(days):
            dl = it.get("deal") or {}
            if dl.get("type") == "open":
                opens[str(dl.get("position_id"))] = dl
            elif dl.get("type") == "close":
                closes.append(dl)
        trades, net_all = [], 0.0
        for dl in closes:
            o = opens.get(str(dl.get("position_id")))
            net = _num((dl.get("profit") or {}).get("amount")) + _num(dl.get("commission")) + (_num(o.get("commission")) if o else 0)
            net_all += net
            side = (o.get("direction") if o else ("sell" if dl.get("direction") == "buy" else "buy"))
            trades.append({"ticket": int(_num(dl.get("position_id"))), "symbol": dl.get("instrument", ""),
                           "side": "BUY" if side == "buy" else "SELL", "volume": _num(dl.get("volume")),
                           "price_in": _num(o.get("price")) if o else 0, "price_out": _num(dl.get("price")),
                           "net": round(net, 2), "time_out": int(_parse_time(dl.get("create_time")).timestamp())})
        trades.sort(key=lambda t: t["time_out"], reverse=True)
        return 200, {"count": len(trades), "net": round(net_all, 2), "currency": st.get("currency", ""), "trades": trades[:50]}
    if route == "candles":
        asked = str(args.get("symbol", "")).strip()
        sym = allowed_by_key.get(asked.lower(), "") if asked else next(iter(allowed_by_key.values()), "")
        if not sym:
            return _err("Mã " + asked + " không được phép trên VPS (XIKE_SYMBOLS)")
        tf = str(args.get("tf", "M15")).upper()
        bars = b.candles(sym, tf, int(_num(args.get("count"), 500)))
        return 200, {"ok": True, "symbol": sym, "tf": tf, "source": "Exness API", "bars": bars}
    if route == "order":
        cid = str(body.get("client_id", ""))[:40]
        if cid and cid in seen:
            return 200, seen[cid]
        asked = str(body.get("symbol", "")).strip()
        sym = allowed_by_key.get(asked.lower(), "")
        side = body.get("side")
        vol, sl, tp = round(_num(body.get("volume")), 2), _num(body.get("sl")), _num(body.get("tp"))
        if not sym:
            return _err("Mã " + asked + " không được phép trên VPS (XIKE_SYMBOLS)")
        if side not in ("BUY", "SELL"):
            return _err("Hướng lệnh phải là BUY hoặc SELL")
        if not (0 < vol <= max_lot):
            return _err("Lot phải trong khoảng 0.01 – %s (giới hạn VPS)" % max_lot)
        if sl <= 0:
            return _err("Thiếu SL")
        bid, ask = b.quote(sym)
        buy = side == "BUY"
        price = ask if buy else bid
        if (buy and sl >= price) or (not buy and sl <= price):
            return _err("SL sai phía giá hiện tại %s" % price)
        if tp and ((buy and tp <= price) or (not buy and tp >= price)):
            return _err("TP sai phía giá hiện tại %s" % price)
        idem = "xike-" + re.sub(r"[^A-Za-z0-9._~-]", "", cid or str(int(time.time() * 1000)))
        res = b.open_position(sym, "buy" if buy else "sell", vol, sl, tp, str(body.get("comment", "XIKE")), idem[:128])
        st = res.get("status")
        if st in ("rejected", "failed"):
            return _err("Exness từ chối lệnh: " + (res.get("error_message") or res.get("error_code") or st), 400, retcode=res.get("error_code", ""))
        out = {"ok": True, "ticket": res.get("operation_id", ""), "price": round(price, 5),
               "pending": st != "confirmed", "note": "" if st == "confirmed" else "Đã gửi, Exness đang xử lý. Xem lại Lệnh đang mở."}
        if cid:
            seen[cid] = out
        return 200, out
    if route == "close":
        cid = str(body.get("client_id", ""))[:40]
        if cid and cid in seen:
            return 200, seen[cid]
        ticket = str(body.get("ticket", "")).strip()
        if not re.fullmatch(r"[0-9]{1,20}", ticket):
            return _err("Ticket không hợp lệ")
        idem = "xike-close-" + re.sub(r"[^A-Za-z0-9._~-]", "", cid or str(int(time.time() * 1000)))
        res = b.close_position(ticket, idem[:128])
        st = res.get("status")
        if st in ("rejected", "failed"):
            return _err("Exness không đóng được lệnh: " + (res.get("error_message") or res.get("error_code") or st), 400)
        out = {"ok": True, "pending": st != "confirmed"}
        if cid:
            seen[cid] = out
        return 200, out
    return _err("Không có cổng này", 404)
