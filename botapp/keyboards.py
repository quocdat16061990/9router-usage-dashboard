from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("👤 Thông tin tài khoản", callback_data="my_info")],
        [InlineKeyboardButton("🔑 Xem danh sách API Keys", callback_data="view_keys")],
        [InlineKeyboardButton("➕ Tạo API Key mới", callback_data="create_key")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🛠️ Chức năng Quản trị", callback_data="admin_panel")])
    buttons.extend([
        [InlineKeyboardButton("🎁 Nhập mã khuyến mãi", callback_data="enter_promo")],
        [InlineKeyboardButton("❓ Trợ giúp", callback_data="help")],
        [InlineKeyboardButton("🚪 Hủy liên kết Telegram", callback_data="unlink_account")],
    ])
    return InlineKeyboardMarkup(buttons)


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Thống kê hệ thống", callback_data="admin_stats")],
        [InlineKeyboardButton("💸 Cộng tiền hạn mức", callback_data="admin_add_credit")],
        [InlineKeyboardButton("🔒 Tài khoản quá hạn", callback_data="admin_overlimit")],
        [InlineKeyboardButton("🔙 Quay lại Menu chính", callback_data="main_menu")],
    ])


def confirm_delete_keyboard(key_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có, xóa ngay", callback_data=f"conf_del:{key_id}")],
        [InlineKeyboardButton("❌ Hủy bỏ", callback_data="view_keys")],
    ])


def restart_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Bắt đầu lại", callback_data="restart_flow")],
    ])
