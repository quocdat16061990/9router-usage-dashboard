# ALTCP Dashboard DEV Workspace

Đây là môi trường DEV tách biệt, không dùng `.env`, database Django hoặc database 9Router production.

## Chạy website

```bash
cd /home/dev-altcp/9router_usage_dashboard_dev
set -a
. ./.env
set +a
source .venv/bin/activate
python manage.py runserver 127.0.0.1:8873
```

Trên máy cá nhân, mở SSH tunnel:

```bash
ssh -L 8873:127.0.0.1:8873 dev-altcp@IP_VPS
```

Sau đó truy cập `http://127.0.0.1:8873/`.

## Tài khoản DEV

Thông tin đăng nhập ban đầu nằm tại `/home/dev-altcp/.dev_altcp_login` và chỉ user `dev-altcp` đọc được. Đổi mật khẩu sau lần đăng nhập đầu tiên nếu cần.

## Git cục bộ

```bash
git status
git diff
git add <file>
git commit -m "Mô tả thay đổi"
```

Không thêm `.env`, database, token, credential, log hoặc virtualenv vào Git.

## Giới hạn an toàn

- Không truy cập hoặc chỉnh sửa production trong `/root`.
- Không dùng API key, email SMTP, webhook hoặc dữ liệu khách hàng thật.
- Không chạy website DEV trên `0.0.0.0`; chỉ dùng `127.0.0.1:8873` và SSH tunnel.
- Không tự triển khai lên production. Chủ VPS/Codex sẽ kiểm tra diff trước khi áp dụng.
