# XI KE AGENT — Hướng dẫn gắn vào app Nhật Ký XAUUSD

## Luồng chạy
Chỉ báo TradingView → alert JSON → ntfy.sh (miễn phí, không cần server) → app → luật cứng → Gemini kiểm duyệt → thông báo CHO PHÉP / CHẶN → bạn vào lệnh trên MT5.

AI chỉ cho phép hoặc chặn. AI không tạo lệnh, không đổi hướng, không thấy và không sửa lot/SL/TP. Lỗi mạng, timeout, câu trả lời sai định dạng, thiếu số liệu đều bị CHẶN.

## Luật cứng (chạy trước, không tốn lượt gọi AI)
- Sai hoặc chưa đặt secret
- Tín hiệu cũ quá 180 giây (phân tích lại bằng tay: 15 phút)
- Giờ cấm 18:00–22:00 giờ VN (đổi trong app, 0-0 = tắt)
- Đang có lệnh mở (ô đánh dấu trong app)
- Thiếu số liệu giá/EMA/MACD/volume, hướng lệnh không phải BUY/SELL, tín hiệu trùng

## Bước 1 — Thêm 2 file Kotlin
1. Chép `XiKeAgentCore.kt` và `XiKeAgentAndroid.kt` vào thư mục code Kotlin của app (cùng một thư mục, tạo thư mục con `xike/agent` nếu cần).
2. Trong `AndroidManifest.xml`, bên trong thẻ `<application>`:
   `<activity android:name="xike.agent.AgentActivity" android:exported="false" />`
3. Bên ngoài `<application>` (nếu chưa có):
   `<uses-permission android:name="android.permission.INTERNET" />`
   `<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />`
4. Thêm một nút trong tab AI để mở màn hình agent:
   `startActivity(Intent(this, xike.agent.AgentActivity::class.java))`
5. App cần minSdk 26 trở lên.

## Bước 2 — Cài đặt trong app
- Gemini API key, model (mặc định `gemini-3.8-flash`, đổi được nếu Google đổi tên)
- Topic ntfy: chuỗi dài khó đoán, ví dụ `xike-7f3k9q2m8z`. Ai biết topic đều đọc được tín hiệu, nên đừng chia sẻ.
- Secret: chuỗi chữ và số, phải giống trong Pine
- Quy tắc: dán quy tắc chỉ báo của bạn, mỗi quy tắc một dòng, có số cụ thể
- Bấm "Gửi tín hiệu thử" để kiểm tra key Gemini

## Bước 3 — TradingView
1. Tạo chỉ báo mới từ `xike_agent_feed.pine` (hoặc dán phần "BẮT ĐẦU" vào cuối chỉ báo của bạn).
2. Sửa 2 dòng `xk_buy` / `xk_sell` thành điều kiện BUY/SELL của chỉ báo. Đặt secret giống trong app.
3. Tạo alert: điều kiện "XI KE Agent Feed" → "Any alert() function call", bật Webhook URL `https://ntfy.sh/<topic>`. Webhook cần gói TradingView có hỗ trợ webhook.

## Dạy AI bằng ảnh mẫu
Nhập ghi chú → bấm "Thêm ảnh mẫu: VÀO ĐÚNG" hoặc "KHÔNG NÊN VÀO" → chọn ảnh chart. Mỗi lần kiểm duyệt gửi 4 ảnh mẫu mới nhất. Ảnh mẫu càng nhiều thì mỗi lần gọi càng tốn token.

## Ảnh chart hiện tại
Khi có tín hiệu: chụp màn hình chart → bấm "Phân tích lại tín hiệu gần nhất + ảnh chart". AI đọc cả số liệu lẫn ảnh. Số liệu vẫn là nguồn chính vì đọc giá từ ảnh dễ sai.

## Giới hạn cần biết
- App chỉ theo dõi khi đang mở (mỗi 20 giây). Tín hiệu đến lúc tắt app sẽ bị chặn vì quá cũ khi mở lại. ntfy.sh chỉ giữ tin vài giờ.
- App chưa tự đặt lệnh MT5: app MT5 trên điện thoại không có API. Muốn tự động phải có cầu nối MT5 trên cloud (dịch vụ trả phí) hoặc máy chạy 24/7.
- Nhật ký `xike_agent_log.jsonl` ghi mọi quyết định, kể cả lệnh bị chặn. Sau vài tuần, so lệnh bị chặn với kết quả thật để biết AI có giúp hay chỉ làm mất lệnh tốt.
