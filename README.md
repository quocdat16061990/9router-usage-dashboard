# 9Router Usage Dashboard

Trang công khai `/` giới thiệu Token Codex, mức quy đổi `1 USD thanh toán = 10 USD hạn mức sử dụng`, bảng so sánh chi phí, quyền lợi và quy trình trước khi khách chọn đăng ký hoặc đăng nhập. Dashboard sau đăng nhập nằm tại `/bang-dieu-khien/`.

Trang công khai `/huong-dan-tich-hop/` hướng dẫn dùng Base URL `https://codex.anhlaptrinh.vn/v1` với OpenClaw, Codex trong Antigravity, NousResearch Hermes Agent, Python và Node.js. Token Codex hiện chấp nhận ba ID model: `GPT-5.6-sol`, `GPT-5.6-terra` và `GPT-5.6-luna`; các ví dụ dùng SOL làm mặc định và hướng dẫn cách đổi model. Ví dụ chỉ dùng placeholder và biến môi trường, không chứa API key thật. Người dùng có thể gọi `/v1/models` bằng API key của mình để xác nhận danh sách model trước khi chạy.

Trang `/mua-token/` có ô nhập mã khuyến mãi nhưng không hiển thị danh sách mã trên giao diện. `CHAOMUNG30` tặng thêm 30% cho lần mua đầu tiên; `THANTHIET50` tặng thêm 50% và dùng một lần cho mỗi tài khoản. `THANTHIETX20` áp dụng hệ số quy đổi ×20 cho mọi gói và được dùng tối đa 3 lần trên mỗi tài khoản: gói 10 USD nhận 200 USD, 20 USD nhận 400 USD, 100 USD nhận 2.000 USD hạn mức; mỗi thời điểm chỉ được có một đơn đang chờ với mã này. `THANTHIET15` giữ nguyên số tiền gói, áp dụng hệ số quy đổi ×15 và dùng một lần trên mỗi tài khoản. Email cảnh báo sắp hết hạn mức chỉ giới thiệu `THANTHIET15` nếu tài khoản chưa có đơn dùng mã này ở trạng thái `paid`. `HOCVIENKH` cộng miễn phí 20 USD hạn mức và `NGUOITHAN400` cộng miễn phí ngay 400 USD hạn mức; mỗi mã chỉ dùng một lần trên mỗi tài khoản và không cần thanh toán. Coupon đặc biệt `DAMUA3000K` và `DAMUA4000K` được dùng không giới hạn số lần, lần lượt khóa mỗi đơn ở 3.000 VNĐ hoặc 4.000 VNĐ và đều nhận 100 USD hạn mức. Các đơn trả phí chỉ được cộng hạn mức sau khi webhook xác nhận thanh toán đủ.

## Cổng khách hàng thương mại

- Khách tự đăng ký tại `/dang-ky/`; tài khoản mới có hạn mức `0 USD` cho tới khi admin cấp credit.
- Đăng ký thành công gửi thông báo tới email quản trị cấu hình bằng `ADMIN_NOTIFICATION_EMAIL`.
- Mật khẩu chỉ yêu cầu tối thiểu 6 ký tự; chấp nhận chữ, số hoặc toàn số.
- Người dùng mở `/quen-mat-khau/` để nhận liên kết đặt lại qua email; mật khẩu mới áp dụng cùng quy tắc tối thiểu 6 ký tự.
- Gửi email đọc cấu hình từ các biến `DJANGO_EMAIL_*`; không lưu SMTP credential trong source.
- Admin tạo thủ công tại `/nguoi-dung/`, đặt hạn mức, quyền tự tạo API và số API tối đa.
- API đầy đủ chỉ hiển thị một lần sau khi tạo và không lưu trong Django.
- `/etc/cron.d/altcp-credit-guard` kiểm tra mỗi phút, tạm khóa API bằng `isActive=false` khi đạt hạn mức và tự mở lại nguyên key khi khách được cộng thêm hạn mức.
- Guard gửi riêng email cảnh báo cho khách hàng và admin khi mức dùng đạt từ 80% hạn mức, đồng thời chống gửi lặp mỗi phút.
- Guard theo phút có thể vượt nhỏ giữa hai lần kiểm tra; chặn đồng bộ cần billing proxy ở giai đoạn sau.
- Khách mua thêm Token Codex tại `/mua-token/` với gói cố định từ 10 đến 1.000 USD, bước 10 USD.
- Quy đổi: 1 USD thanh toán = 25.000 VNĐ và được cộng 10 USD hạn mức nhà cung cấp.
- VietQR dùng BIDV; SePay xác nhận tại `/payment/ipn/`, chống xử lý giao dịch trùng và chỉ cộng hạn mức khi nhận đủ tiền. Route cũ `/api/sepay/webhook/` được giữ làm alias tương thích.
- Đơn mới dùng nội dung chuyển khoản dạng `CDX` + 4 chữ số, ví dụ `CDX4565`. Bảng lease giữ mỗi mã 30 ngày, có ràng buộc unique và tự sinh lại khi va chạm; webhook vẫn nhận mã dài cũ.
- Thanh toán thành công gửi xác nhận riêng cho khách và thông báo đơn hàng tới `ADMIN_NOTIFICATION_EMAIL`.

## Cổng khách hàng thương mại

- Khách hàng tự đăng ký tại `/dang-ky/`; tài khoản mới có hạn mức `0 USD` cho tới khi admin cấp credit.
- Admin vẫn có thể tạo tài khoản thủ công tại `/nguoi-dung/`, đặt hạn mức USD, quyền tự tạo API và số API tối đa.
- Khách hàng tự tạo/thu hồi API từ dashboard. API đầy đủ chỉ hiển thị một lần sau khi tạo.
- Cron `/etc/cron.d/altcp-credit-guard` chạy mỗi phút, tạm khóa API khi tổng chi phí đạt hạn mức và tự mở lại khi tổng chi phí thấp hơn hạn mức mới.
- Lệnh kiểm tra thủ công: `.venv/bin/python manage.py enforce_credit_limits`.
- Guard theo phút có thể phát sinh một lượng vượt nhỏ giữa hai lần kiểm tra; chặn giao dịch đồng bộ trước request cần bổ sung billing proxy ở giai đoạn tiếp theo.
- Thanh toán SePay, coupon miễn phí và thao tác tăng hạn mức từ admin đều gọi mở lại key ngay sau transaction; guard tiếp tục retry nếu 9Router tạm thời không phản hồi.
- Chỉ key bị khóa với lý do `Đã dùng hết hạn mức` được tự mở; key do người dùng thu hồi hoặc admin xóa không được khôi phục.
- Key đã bị DELETE theo cơ chế cũ không thể phục hồi nguyên secret; dashboard yêu cầu khách tạo key mới và cập nhật ứng dụng.

Dashboard Django nội bộ truy cập tại `altcp.anhlaptrinh.vn` hoặc `codex.anhlaptrinh.vn`, tổng hợp dữ liệu chỉ đọc từ:

- `/root/.9router/db/data.sqlite` (đọc read-only từ `usageHistory` và `apiKeys`)

Bảng có đúng ba cột: tên API, số request và chi phí. Báo cáo hỗ trợ hôm nay, tháng này hoặc dải ngày tùy chọn theo múi giờ Việt Nam.

Khách hàng còn có bảng nhật ký request chi tiết theo cùng bộ lọc thời gian. Mỗi dòng hiển thị giờ Việt Nam đến giây, mã request nội bộ, API/model, endpoint, trạng thái, token đầu vào/đầu ra và chi phí. Bảng phân trang 50 request mỗi trang và không hiển thị API key, connection ID, prompt hoặc response.

## Phân quyền người dùng

- Superuser xem toàn bộ API có phát sinh sử dụng.
- Người dùng thường chỉ xem các API được gán cho tài khoản của mình.
- Superuser quản lý tài khoản tại `/nguoi-dung/`: tạo user, đặt mật khẩu, chọn nhiều API, đổi thông tin và khóa/mở tài khoản.
- Bảng phân quyền chỉ lưu UUID nội bộ và tên API, không lưu chuỗi API key thật.
- Người dùng chưa được gán API sẽ thấy báo cáo trống, không được xem dữ liệu chung.
- Người dùng thường bị chặn khỏi trang quản lý tài khoản bằng HTTP 403.

## Chạy kiểm tra

```bash
cd /root/Apps/9router_usage_dashboard
source .venv/bin/activate
python manage.py check
python manage.py test
```

## Vận hành

```bash
systemctl status altcp-dashboard
journalctl -u altcp-dashboard -n 100 --no-pager
```

Webhook cần đăng ký trong SePay:

```text
https://codex.anhlaptrinh.vn/payment/ipn/
```

Secret webhook chỉ lưu trong `SEPAY_WEBHOOK_SECRET` tại `.env`, không ghi vào tài liệu hoặc URL.

Thông tin đăng nhập ban đầu được lưu riêng với quyền `600`, không ghi trong source hoặc tài liệu.

## Tích hợp Telegram Bot
Hỗ trợ liên kết tài khoản và quản lý hạn mức, API key trực tiếp qua chat:
- **Khởi động Bot**: `.venv/bin/python otp_bot.py`
- **Mã khuyến mãi test (0đ/Free credit)**: `HOCVIENKH` ($20) và `NGUOITHAN400` ($400).
- **Các tính năng chính**:
  1. `/start` - Điền email và OTP để liên kết tài khoản Telegram.
  2. `/me` - Xem thông tin tài khoản (Hạn mức, Đã dùng, Số dư còn lại).
  3. `/keys` - Xem danh sách API key, kèm nút thu hồi nhanh.
  4. `/createkey` - Tạo API key mới (key hiển thị duy nhất 1 lần kèm cảnh báo sao lưu).
  5. `/promo` - Áp dụng mã khuyến mãi miễn phí (0đ) để tăng hạn mức.
  6. `/unlink` - Hủy liên kết tài khoản Telegram.

