# XIKE CAD

Phần mềm vẽ kỹ thuật 2D chạy trên trình duyệt, gói trong một file `index.html`. Không cần cài đặt hay kết nối mạng: chỉ cần mở file bằng Chrome, Edge hoặc Firefox.

## Tính năng
- **Vẽ:** đoạn thẳng (L), đa tuyến (PL), hình chữ nhật (REC), đường tròn (C), cung 3 điểm (A), đa giác đều (POL), chữ (T), kích thước (DIM)
- **Sửa:** di chuyển (M), sao chép (CO), xoay (RO), tỉ lệ (SC), đối xứng (MI), offset (O), cắt (TR), bo góc (F), phá khối (X), xóa (E)
- **Đo:** khoảng cách (DI), diện tích và chu vi (AA)
- **Trợ giúp vẽ:** bắt điểm (điểm cuối, trung điểm, tâm, góc phần tư, giao điểm) bằng F3, lưới F7, vuông góc F8, snap lưới F9
- **Lớp (layer):** đổi màu, ẩn/hiện, khóa, đổi tên (bấm đúp), xóa
- **Hoàn tác / làm lại** không giới hạn thao tác (tối đa 200 bước)
- **File:** lưu/mở `.json`, mở `.dxf`, xuất `.dxf` (R12, mở được trong các phần mềm CAD phổ biến), `.svg`, `.png`
- Tự động lưu bản vẽ vào trình duyệt

## Nhập tọa độ trên dòng lệnh
| Cú pháp | Ý nghĩa |
|---|---|
| `x,y` | Tọa độ tuyệt đối |
| `@dx,dy` | Tọa độ tương đối so với điểm trước |
| `@d<góc` | Tọa độ cực tương đối (góc tính bằng độ) |
| `50` | Khoảng cách 50 theo hướng con trỏ chuột |

Enter, phím Space hoặc chuột phải để xác nhận; Esc để hủy; Enter khi dòng lệnh trống để lặp lại lệnh trước. Lăn chuột để thu phóng, giữ chuột giữa để di chuyển màn hình. Gõ `HELP` để xem danh sách lệnh.
