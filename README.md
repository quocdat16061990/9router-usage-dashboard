# 9Router Telegram Bot

Hỗ trợ liên kết tài khoản và quản lý hạn mức, API key trực tiếp qua chat:

- **Khởi động Bot**: `.venv/bin/python otp_bot.py`
- **Mã khuyến mãi test (0đ/Free credit)**: `HOCVIENKH` ($20) và `NGUOITHAN400` ($400).

## Các tính năng chính
1. `/start` - Điền email và OTP để liên kết tài khoản Telegram.
2. `/me` - Xem thông tin tài khoản (Hạn mức, Đã dùng, Số dư còn lại).
3. `/keys` - Xem danh sách API key, kèm nút thu hồi nhanh.
4. `/createkey` - Tạo API key mới (key hiển thị duy nhất 1 lần kèm cảnh báo sao lưu).
5. `/promo` - Áp dụng mã khuyến mãi miễn phí (0đ) để tăng hạn mức.
6. `/unlink` - Hủy liên kết tài khoản Telegram.
