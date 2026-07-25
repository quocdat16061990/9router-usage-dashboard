from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("👤 Thông tin tài khoản", callback_data="my_info")],
        [InlineKeyboardButton("🔑 Xem danh sách API Keys", callback_data="view_keys")],
        [InlineKeyboardButton("➕ Tạo API Key mới", callback_data="create_key")],
        [InlineKeyboardButton("🎁 Nhập mã khuyến mãi", callback_data="enter_promo")],
        [InlineKeyboardButton("❓ Trợ giúp", callback_data="help")],
        [InlineKeyboardButton("🚪 Hủy liên kết Telegram", callback_data="unlink_account")],
    ]
    return InlineKeyboardMarkup(buttons)


def confirm_delete_keyboard(key_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có, xóa ngay", callback_data=f"conf_del:{key_id}")],
        [InlineKeyboardButton("❌ Hủy bỏ", callback_data="view_keys")],
    ])


def restart_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Bắt đầu lại", callback_data="restart_flow")],
    ])
