# Kết nối app XIKE với MT5 trên VPS

```
App (điện thoại) ──https + token──▶ Cloudflare Tunnel ──▶ server.py (VPS Windows) ──▶ MT5
```
App không nối thẳng vào MT5 được. `server.py` chạy trên VPS, cạnh MT5, làm cầu nối.

## 1. Chuẩn bị VPS
- VPS **Windows** (gói Python MetaTrader5 chỉ chạy trên Windows), RAM 2 GB trở lên.
- Cài MT5 của broker, mở lên một lần.
- Bật **Algo Trading** (nút trên thanh công cụ MT5). Tắt thì vẫn xem được tài khoản nhưng không đặt lệnh được.
- Cài Python 3.11+ từ python.org, tích **Add Python to PATH**.

## 2. Chạy cầu nối
1. Chép thư mục `vps` này lên VPS (ví dụ `C:\xike\vps`).
2. Mở Command Prompt trong thư mục đó:
   ```
   pip install -r requirements.txt
   ```
3. Tạo token: một chuỗi ngẫu nhiên dài ≥ 24 ký tự, ví dụ chạy
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
4. Mở `chay.bat` bằng Notepad, thay `DOI-CHUOI-NAY-...` bằng token. Sửa `XIKE_SYMBOLS` nếu broker đặt tên khác (vd `XAUUSDm`), sửa `XIKE_MAX_LOT` nếu cần.
5. Bấm đúp `chay.bat`. Thấy dòng `XIKE MT5 Bridge chạy ở http://127.0.0.1:8787` là được.

Muốn tự chạy khi VPS khởi động lại: đặt lối tắt của MT5 và `chay.bat` vào thư mục `shell:startup`, và bật tự đăng nhập Windows.

## 3. Mở địa chỉ https (Cloudflare Tunnel, miễn phí)
Cần một tên miền đã thêm vào Cloudflare.
1. Cloudflare → Zero Trust → Networks → Tunnels → **Create a tunnel** → Cloudflared → đặt tên.
2. Chọn Windows, chạy lệnh cài nó đưa (chạy CMD bằng quyền Administrator).
3. Tab **Public Hostname**: subdomain `mt5`, domain của bạn, Service `HTTP` → `localhost:8787`.
4. Địa chỉ VPS của bạn là `https://mt5.ten-mien-cua-ban.com`.

Không cần mở cổng trên tường lửa Windows. `server.py` chỉ nghe ở `127.0.0.1`, ngoài Internet chỉ vào được qua tunnel.

## 4. Kết nối trong app
Tab **Biểu đồ → Cài đặt**:
1. **Địa chỉ VPS**: `https://mt5.ten-mien-cua-ban.com`; **Token**: chuỗi ở bước 2 → **Lưu và kết nối**.
   Dòng "Trạng thái MT5" hiện `MT5 chạy, chưa đăng nhập` là cầu nối đã thông.
2. **Đăng nhập MT5**: số tài khoản, mật khẩu, server (tên đúng như trong MT5, ví dụ `Exness-MT5Real8`) → **Đăng nhập MT5**.
3. Thấy `Đã đăng nhập TK ... · số dư ...` là xong. Khối tài khoản, lệnh mở, lịch sử tự cập nhật mỗi 20 giây.

App chỉ nhớ số tài khoản và server, **không lưu mật khẩu**; mật khẩu gửi một lần qua https tới VPS. MT5 trên VPS tự nhớ đăng nhập nếu bạn tích "Lưu mật khẩu" trong MT5.
Dùng **mật khẩu chỉ xem (investor)** nếu chỉ muốn xem; muốn đặt lệnh thì cần mật khẩu giao dịch (master).

## Lỗi thường gặp
| App báo | Cách sửa |
|---|---|
| Không kết nối được VPS | Sai địa chỉ, tunnel chưa chạy, hoặc `chay.bat` đã tắt |
| Sai token | Token trong app khác token trong `chay.bat` |
| MT5 chưa sẵn sàng (Không mở được MT5) | Mở MT5 trên VPS, hoặc điền `MT5_PATH` trong `chay.bat` |
| Đăng nhập thất bại | Sai số tài khoản / mật khẩu / tên server |
| Sai quá nhiều lần | Đợi 10 phút (chặn đoán mật khẩu) |
| MT5 đang tắt Algo Trading | Bấm nút Algo Trading trong MT5 trên VPS |
| Mã ... không được phép | Thêm mã vào `XIKE_SYMBOLS` |

## An toàn
- Ai có địa chỉ + token là xem và đặt lệnh được: không chia sẻ, đổi token nếu lộ.
- VPS chặn thêm: chỉ mã trong `XIKE_SYMBOLS`, lot ≤ `XIKE_MAX_LOT`, bắt buộc SL đúng phía giá, chặn gửi trùng.
- Thử bằng tài khoản **demo** trước.
