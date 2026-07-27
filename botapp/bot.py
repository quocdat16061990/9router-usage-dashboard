import logging
import random
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .keyboards import main_menu_keyboard, restart_keyboard, admin_menu_keyboard, back_to_main_keyboard, back_to_admin_keyboard, confirm_delete_user_keyboard
from .services import (
    apply_free_promo_to_user,
    create_api_key_for_user,
    create_customer_account_by_admin,
    delete_api_key_for_user,
    delete_customer_account_by_admin,
    grant_credit_to_user,
    is_valid_email,
    send_telegram_otp_email,
)

logger = logging.getLogger(__name__)

ASK_EMAIL = 0
ASK_OTP = 1
ASK_PROMO = 2
ASK_KEY_NAME = 3
ASK_ADMIN_CREDIT_EMAIL = 4
ASK_ADMIN_CREDIT_AMOUNT = 5
ASK_ADMIN_DELETE_EMAIL = 6
ASK_ADMIN_CREATE_USER_EMAIL = 7
ASK_ADMIN_CREATE_USER_PASSWORD = 8
ASK_REGISTER_PASSWORD = 9


def escape_markdown(text: str) -> str:
    if not text:
        return ""
    for char in ["_", "*", "`", "["]:
        text = text.replace(char, f"\\{char}")
    return text


async def _find_account_by_chat_id(chat_id: int):
    from dashboard.models import CustomerAccount
    return await sync_to_async(
        lambda: CustomerAccount.objects.select_related("user")
        .filter(telegram_chat_id=chat_id, is_verified_telegram=True)
        .first()
    )()


async def _is_admin_account(account) -> bool:
    if not account:
        return False
    return await sync_to_async(lambda: bool(account.user and (account.user.is_superuser or account.user.is_staff)))()


async def _require_active_account(update: Update):
    account = await _find_account_by_chat_id(update.effective_chat.id)
    if not account:
        await _reply_not_linked(update)
        return None
    return account


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    account = await _find_account_by_chat_id(update.effective_chat.id)
    if account:
        is_admin = await _is_admin_account(account)
        email_val = await sync_to_async(lambda: account.user.email)()
        first_name_val = await sync_to_async(lambda: account.user.first_name)()
        await update.message.reply_text(
            f"Xin chào {escape_markdown(first_name_val) or 'bạn'}!\n\n"
            f"Email: `{email_val}`\n"
            f"Hạn mức: `${account.credit_limit:.4f}`\n\n"
            "Chọn chức năng bên dưới.",
            reply_markup=main_menu_keyboard(is_admin),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Chào mừng bạn đến với hệ thống Anh Lập Trình.\n\n"
        "Vui lòng nhập email của bạn đã đăng ký trên hệ thống để liên kết Telegram.\n\n"
        "🤖 *Các câu lệnh hỗ trợ:*\n"
        "• `/me` - Xem thông tin số dư & hạn mức\n"
        "• `/keys` - Xem danh sách & thu hồi API Keys\n"
        "• `/createkey` - Tạo API Key mới nhanh\n"
        "• `/promo` - Nhập mã khuyến mãi\n"
        "• `/unlink` - Hủy liên kết Telegram\n"
        "• `/help` - Xem hướng dẫn sử dụng",
        reply_markup=restart_keyboard(),
        parse_mode="Markdown",
    )
    return ASK_EMAIL


async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email_text = update.message.text.strip().lower()
    if not is_valid_email(email_text):
        await update.message.reply_text("❌ Email không hợp lệ. Vui lòng nhập lại.", reply_markup=restart_keyboard())
        return ASK_EMAIL

    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    user = await sync_to_async(User.objects.filter(email=email_text).first)()
    if not user:
        context.user_data["register_email"] = email_text
        await update.message.reply_text(
            f"Email `{email_text}` chưa có trên hệ thống.\n\n"
            "Vui lòng nhập mật khẩu bạn muốn sử dụng để đăng ký tài khoản Khách Hàng mới:\n"
            "*(Lưu ý: Bạn nên xoá tin nhắn mật khẩu sau khi đăng ký thành công)*",
            reply_markup=restart_keyboard(),
            parse_mode="Markdown",
        )
        return ASK_REGISTER_PASSWORD

    from dashboard.models import CustomerAccount
    account, _ = await sync_to_async(CustomerAccount.objects.get_or_create)(user=user)
    
    if account.is_verified_telegram:
        await update.message.reply_text(
            "❌ Email này đã được liên kết với một tài khoản Telegram.",
            reply_markup=restart_keyboard(),
        )
        return ConversationHandler.END

    otp_code = f"{random.randint(100000, 999999)}"
    try:
        account.telegram_otp = otp_code
        account.telegram_otp_created_at = timezone.now()
        await sync_to_async(account.save)(update_fields=["telegram_otp", "telegram_otp_created_at"])
        
        email_sent = await sync_to_async(send_telegram_otp_email)(email_text, otp_code)
        if not email_sent:
            raise RuntimeError("Không gửi được OTP xác thực Telegram.")
    except Exception:
        logger.exception("Không tạo được phiên xác thực Telegram.")
        await update.message.reply_text("❌ Không gửi được mã xác thực. Vui lòng thử lại sau.", reply_markup=restart_keyboard())
        return ConversationHandler.END

    context.user_data["pending_email"] = email_text
    context.user_data["otp_attempts"] = 0
    await update.message.reply_text(
        f"🔑 Đã gửi mã OTP 6 số đến `{email_text}`. Mã có hiệu lực trong 10 phút.",
        reply_markup=restart_keyboard(),
        parse_mode="Markdown",
    )
    return ASK_OTP


async def handle_register_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    email_text = context.user_data.get("register_email")
    if not email_text:
        await update.message.reply_text("❌ Lỗi phiên đăng ký. Vui lòng bấm /start để thử lại.", reply_markup=restart_keyboard())
        return ConversationHandler.END

    from django.contrib.auth import get_user_model
    User = get_user_model()
    from dashboard.models import CustomerAccount

    try:
        user = await sync_to_async(User.objects.create_user)(username=email_text, email=email_text, password=password)
        account, _ = await sync_to_async(CustomerAccount.objects.get_or_create)(user=user)
        
        otp_code = f"{random.randint(100000, 999999)}"
        account.telegram_otp = otp_code
        account.telegram_otp_created_at = timezone.now()
        await sync_to_async(account.save)(update_fields=["telegram_otp", "telegram_otp_created_at"])
        
        email_sent = await sync_to_async(send_telegram_otp_email)(email_text, otp_code)
        if not email_sent:
            raise RuntimeError("Không gửi được OTP xác thực Telegram.")
            
        context.user_data["pending_email"] = email_text
        context.user_data["otp_attempts"] = 0
        await update.message.reply_text(
            f"✅ Đã tạo tài khoản thành công.\n\n"
            f"🔑 Hệ thống đã gửi mã OTP 6 số đến `{email_text}`. Mã có hiệu lực trong 10 phút.",
            reply_markup=restart_keyboard(),
            parse_mode="Markdown",
        )
        return ASK_OTP
    except Exception:
        logger.exception("Không tạo được tài khoản hoặc gửi OTP.")
        await update.message.reply_text("❌ Đã xảy ra lỗi hệ thống khi đăng ký. Vui lòng thử lại sau.", reply_markup=restart_keyboard())
        return ConversationHandler.END


async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp_text = update.message.text.strip()
    email_text = context.user_data.get("pending_email")
    chat_id = update.effective_chat.id
    if not email_text:
        await update.message.reply_text("❌ Phiên xác thực không hợp lệ. Vui lòng bấm /start.", reply_markup=restart_keyboard())
        return ConversationHandler.END

    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = await sync_to_async(User.objects.filter(email=email_text).first)()
    if not user:
        await update.message.reply_text("❌ Không tìm thấy người dùng. Vui lòng bấm /start.", reply_markup=restart_keyboard())
        return ConversationHandler.END

    from dashboard.models import CustomerAccount
    account, _ = await sync_to_async(CustomerAccount.objects.get_or_create)(user=user)
    account.user = user

    now = timezone.now()
    otp_expired = account.telegram_otp_created_at and now > account.telegram_otp_created_at + timedelta(minutes=10)
    if otp_expired or not account.telegram_otp or account.telegram_otp != otp_text:
        attempts = context.user_data.get("otp_attempts", 0) + 1
        context.user_data["otp_attempts"] = attempts
        if attempts >= 5:
            context.user_data.clear()
            await update.message.reply_text("❌ Bạn đã nhập sai OTP quá nhiều lần. Vui lòng bấm /start.", reply_markup=restart_keyboard())
            return ConversationHandler.END
        await update.message.reply_text(f"❌ OTP không đúng hoặc đã hết hạn ({attempts}/5).", reply_markup=restart_keyboard())
        return ASK_OTP

    # Clear chat id from other accounts first to enforce uniqueness manually
    await sync_to_async(
        lambda: CustomerAccount.objects.filter(telegram_chat_id=chat_id)
        .exclude(id=account.id)
        .update(telegram_chat_id=None, is_verified_telegram=False)
    )()

    account.telegram_chat_id = chat_id
    account.is_verified_telegram = True
    account.telegram_otp = None
    account.telegram_otp_created_at = None
    await sync_to_async(account.save)()

    context.user_data.clear()
    is_admin = user.is_superuser or user.is_staff
    await update.message.reply_text(
        f"✅ Xác thực thành công!\n\nEmail: `{email_text}`\nHạn mức: `${account.credit_limit:.4f}`",
        reply_markup=main_menu_keyboard(is_admin),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def my_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    account = await _require_active_account(update)
    if not account:
        return
    
    from dashboard.services import customer_spent
    spent = await sync_to_async(lambda: customer_spent(account.user))()
    remaining = max(account.credit_limit - spent, 0)
    email_val = await sync_to_async(lambda: account.user.email)()
    first_name_val = await sync_to_async(lambda: account.user.first_name)()
    
    text = (
        "👤 Thông tin tài khoản của bạn\n\n"
        f"Email: `{email_val}`\n"
        f"Họ tên: {escape_markdown(first_name_val) or 'Chưa cập nhật'}\n"
        f"Hạn mức: `${account.credit_limit:.4f}`\n"
        f"Đã sử dụng: `${spent:.4f}`\n"
        f"Còn lại: `${remaining:.4f}`"
    )
    is_admin = await _is_admin_account(account)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")


async def show_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()

    account = await _require_active_account(update)
    if not account:
        return

    from dashboard.models import ManagedApiKey
    keys = await sync_to_async(lambda: list(ManagedApiKey.objects.filter(user=account.user, is_active=True)))()
    
    keyboard_buttons = []
    if not keys:
        text = "❌ Bạn hiện không có API Key hoạt động nào."
    else:
        text = "🔑 *Danh sách API Keys đang hoạt động:*\n\n"
        for i, key in enumerate(keys, 1):
            text += f"📌 *{escape_markdown(key.api_name)}*\n"
            text += f"   • Prefix: `{key.key_prefix}...`\n"
            text += f"   • Ngày tạo: {key.created_at.strftime('%d/%m/%Y %H:%M')}\n\n"
            keyboard_buttons.append([InlineKeyboardButton(f"❌ Thu hồi '{key.api_name}'", callback_data=f"del_key:{key.id}")])

    keyboard_buttons.append([InlineKeyboardButton("🔙 Quay lại Menu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    account = await _require_active_account(update)
    if not account:
        return
    is_admin = await _is_admin_account(account)
    email_val = await sync_to_async(lambda: account.user.email)()
    first_name_val = await sync_to_async(lambda: account.user.first_name)()
    await query.edit_message_text(
        f"Xin chào {escape_markdown(first_name_val) or 'bạn'}!\n\nEmail: `{email_val}`",
        reply_markup=main_menu_keyboard(is_admin),
        parse_mode="Markdown",
    )


async def menu_exit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await main_menu_callback(update, context)
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Lệnh hỗ trợ:\n"
        "/start - liên kết tài khoản Telegram\n"
        "/me - xem thông tin hạn mức & sử dụng\n"
        "/keys - xem danh sách API Keys đang hoạt động\n"
        "/unlink - đăng xuất Telegram"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=restart_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=restart_keyboard())


async def restart_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    
    account = await _find_account_by_chat_id(update.effective_chat.id)
    if account:
        is_admin = await _is_admin_account(account)
        first_name_val = await sync_to_async(lambda: account.user.first_name)()
        email_val = await sync_to_async(lambda: account.user.email)()
        await query.edit_message_text(
            f"Xin chào {escape_markdown(first_name_val) or 'bạn'}!\n\nEmail: `{email_val}`",
            reply_markup=main_menu_keyboard(is_admin),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "Chào mừng bạn đến với hệ thống Anh Lập Trình.\n\n"
        "Vui lòng nhập email của bạn đã đăng ký trên hệ thống để liên kết Telegram.\n\n"
        "🤖 *Các câu lệnh hỗ trợ:*\n"
        "• `/me` - Xem thông tin số dư & hạn mức\n"
        "• `/keys` - Xem danh sách & thu hồi API Keys\n"
        "• `/createkey` - Tạo API Key mới nhanh\n"
        "• `/promo` - Nhập mã khuyến mãi\n"
        "• `/unlink` - Hủy liên kết Telegram\n"
        "• `/help` - Xem hướng dẫn sử dụng",
        reply_markup=restart_keyboard(),
        parse_mode="Markdown",
    )
    return ASK_EMAIL


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Đã hủy. Gõ /start để bắt đầu lại.", reply_markup=restart_keyboard())
    return ConversationHandler.END


async def _reply_not_linked(update: Update) -> None:
    text = "❌ Bạn chưa liên kết tài khoản Telegram.\n\nGõ /start và nhập email để liên kết."
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=restart_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=restart_keyboard())


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    chat_id = update.effective_chat.id

    from dashboard.models import CustomerAccount
    account = await sync_to_async(lambda: CustomerAccount.objects.filter(telegram_chat_id=chat_id).first())()
    if account:
        account.telegram_chat_id = None
        account.is_verified_telegram = False
        account.telegram_otp = None
        account.telegram_otp_created_at = None
        await sync_to_async(account.save)()
    await update.message.reply_text("Đã hủy liên kết Telegram. Vui lòng nhập email để liên kết lại.", reply_markup=restart_keyboard())
    return ASK_EMAIL


async def unlink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    chat_id = update.effective_chat.id

    from dashboard.models import CustomerAccount
    account = await sync_to_async(lambda: CustomerAccount.objects.filter(telegram_chat_id=chat_id).first())()
    if account:
        account.telegram_chat_id = None
        account.is_verified_telegram = False
        account.telegram_otp = None
        account.telegram_otp_created_at = None
        await sync_to_async(account.save)()
    await query.edit_message_text("Đã hủy liên kết Telegram. Bấm /start để liên kết lại.", reply_markup=restart_keyboard())
    return ConversationHandler.END


async def start_promo_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    msg_text = "🎁 Vui lòng nhập mã khuyến mãi (Mã 0đ / Free credit) của bạn:"
    if query:
        await query.edit_message_text(msg_text, reply_markup=back_to_main_keyboard())
    else:
        await update.message.reply_text(msg_text, reply_markup=back_to_main_keyboard())
    return ASK_PROMO


async def handle_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    promo_text = update.message.text.strip().upper()
    
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    success, message = await sync_to_async(lambda: apply_free_promo_to_user(account.user, promo_text))()
    is_admin = await _is_admin_account(account)
    
    if success:
        await update.message.reply_text(
            f"✅ {message}",
            reply_markup=main_menu_keyboard(is_admin),
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\nVui lòng thử lại hoặc gõ /cancel để hủy.",
            reply_markup=back_to_main_keyboard(),
        )
        return ASK_PROMO


async def cancel_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    is_admin = False
    account = await _find_account_by_chat_id(update.effective_chat.id)
    if account:
        is_admin = await _is_admin_account(account)
    await update.message.reply_text(
        "Đã hủy nhập mã khuyến mãi.",
        reply_markup=main_menu_keyboard(is_admin),
    )
    return ConversationHandler.END


async def start_create_key_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        from dashboard.services import customer_spent
        spent = await sync_to_async(lambda: customer_spent(account.user))()
        active_count = await sync_to_async(lambda: account.user.managed_api_keys.filter(is_active=True).count())()
        
        if not account.allow_key_creation:
            msg = "❌ Tài khoản của bạn chưa được cấp quyền tự tạo API Key."
            if query:
                await query.edit_message_text(msg, reply_markup=main_menu_keyboard(is_admin))
            else:
                await update.message.reply_text(msg, reply_markup=main_menu_keyboard(is_admin))
            return ConversationHandler.END
            
        if account.credit_limit <= spent:
            msg = f"❌ Tài khoản đã hết số dư khả dụng (Đã dùng: `${spent:.4f}` / Hạn mức: `${account.credit_limit:.4f}`).\n\nVui lòng nạp thêm tiền hoặc dùng mã khuyến mãi `/promo` trước khi tạo API Key."
            if query:
                await query.edit_message_text(msg, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")
            else:
                await update.message.reply_text(msg, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")
            return ConversationHandler.END

        if active_count >= account.max_api_keys:
            msg = f"❌ Tài khoản đã đạt giới hạn số lượng API Key đang hoạt động ({account.max_api_keys} keys).\n\nVui lòng thu hồi bớt API Key cũ trong `/keys` trước khi tạo mới."
            if query:
                await query.edit_message_text(msg, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")
            else:
                await update.message.reply_text(msg, reply_markup=main_menu_keyboard(is_admin), parse_mode="Markdown")
            return ConversationHandler.END

    msg_text = (
        "➕ **Tạo API Key mới**\n\n"
        "Vui lòng nhập **Tên gợi nhớ** cho API Key mới của bạn (chỉ gồm chữ, số, tối đa 30 ký tự):\n"
        "*(Hoặc bấm Quay lại / gõ /cancel để hủy)*"
    )
    if query:
        await query.edit_message_text(msg_text, reply_markup=back_to_main_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg_text, reply_markup=back_to_main_keyboard(), parse_mode="Markdown")
    return ASK_KEY_NAME


async def handle_key_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name_text = update.message.text.strip()
    
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    import re
    if not re.match(r"^[a-zA-Z0-9\-_\s]+$", name_text) or len(name_text) > 30:
        await update.message.reply_text(
            "❌ Tên gợi nhớ không hợp lệ. Vui lòng nhập lại tên ngắn gọn (chỉ gồm chữ, số, dấu gạch ngang, tối đa 30 ký tự) hoặc gõ /cancel để hủy:",
            reply_markup=back_to_main_keyboard()
        )
        return ASK_KEY_NAME
        
    success, message, raw_key = await sync_to_async(lambda: create_api_key_for_user(account.user, name_text))()
    is_admin = await _is_admin_account(account)
    
    if success:
        warning_msg = (
            f"✅ **Tạo API Key thành công!**\n\n"
            f"📌 Tên gợi nhớ: *{escape_markdown(name_text)}*\n"
            f"🔑 API Key: `{raw_key}`\n\n"
            f"⚠️ **CẢNH BÁO QUAN TRỌNG:** API Key này **chỉ hiển thị duy nhất một lần**. "
            f"Vui lòng sao chép và lưu trữ an toàn ngay lập tức. Sau khi rời khỏi màn hình này, "
            f"bạn sẽ **không bao giờ xem lại** được mã key này nữa!"
        )
        await update.message.reply_text(
            warning_msg,
            reply_markup=main_menu_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}",
            reply_markup=main_menu_keyboard(is_admin)
        )
        return ConversationHandler.END


async def cancel_key_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    is_admin = False
    account = await _find_account_by_chat_id(update.effective_chat.id)
    if account:
        is_admin = await _is_admin_account(account)
    await update.message.reply_text(
        "Đã hủy quá trình tạo API Key.",
        reply_markup=main_menu_keyboard(is_admin),
    )
    return ConversationHandler.END


async def delete_key_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    account = await _require_active_account(update)
    if not account:
        return
        
    key_id = int(query.data.split(":")[1])
    key = await sync_to_async(lambda: account.user.managed_api_keys.filter(pk=key_id, is_active=True).first())()
    
    if not key:
        is_admin = await _is_admin_account(account)
        await query.edit_message_text(
            "❌ API Key này không tồn tại hoặc đã bị thu hồi trước đó.",
            reply_markup=main_menu_keyboard(is_admin)
        )
        return
        
    from .keyboards import confirm_delete_keyboard
    warning_text = (
        f"⚠️ **CẢNH BÁO THU HỒI KEY:**\n\n"
        f"Bạn có chắc chắn muốn thu hồi (xóa) API Key *{escape_markdown(key.api_name)}* (`{key.key_prefix}...`)?\n\n"
        f"Hành động này sẽ **ngay lập tức vô hiệu hóa** key trên Anh Lập Trình và làm gián đoạn mọi ứng dụng đang sử dụng nó. "
        f"Hành động này **không thể hoàn tác**!"
    )
    await query.edit_message_text(
        warning_text,
        reply_markup=confirm_delete_keyboard(key.id),
        parse_mode="Markdown"
    )


async def delete_key_execute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    account = await _require_active_account(update)
    if not account:
        return
        
    key_id = int(query.data.split(":")[1])
    from .services import delete_api_key_for_user
    success, message = await sync_to_async(lambda: delete_api_key_for_user(account.user, key_id))()
    
    is_admin = await _is_admin_account(account)
    if success:
        await query.edit_message_text(
            f"✅ {message}",
            reply_markup=main_menu_keyboard(is_admin)
        )
    else:
        await query.edit_message_text(
            f"❌ {message}",
            reply_markup=main_menu_keyboard(is_admin)
        )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        await query.edit_message_text("❌ Bạn không có quyền truy cập chức năng này.", reply_markup=main_menu_keyboard(False))
        return
        
    text = (
        "🛠️ **BẢNG ĐIỀU KHIỂN QUẢN TRỊ (ADMIN PANEL)**\n\n"
        "Chào mừng Quản trị viên! Vui lòng chọn một tác vụ dưới đây:"
    )
    from .keyboards import admin_menu_keyboard
    if query:
        await query.edit_message_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return
        
    from django.contrib.auth import get_user_model
    from django.db import models
    from dashboard.models import CustomerAccount, ManagedApiKey
    from dashboard.services import usage_totals_by_api_id
    from decimal import Decimal
    
    User = get_user_model()
    total_users = await sync_to_async(User.objects.count)()
    
    total_credit = await sync_to_async(
        lambda: CustomerAccount.objects.aggregate(total=models.Sum("credit_limit"))["total"] or Decimal("0")
    )()
    
    active_keys = await sync_to_async(list)(ManagedApiKey.objects.filter(is_active=True))
    active_keys_count = len(active_keys)
    
    active_key_ids = [k.external_api_key_id for k in active_keys]
    costs = await sync_to_async(usage_totals_by_api_id)(active_key_ids)
    total_active_cost = sum(costs.values())
    
    total_closed_cost = await sync_to_async(
        lambda: ManagedApiKey.objects.filter(is_active=False).aggregate(total=models.Sum("closed_cost"))["total"] or Decimal("0")
    )()
    
    total_spent = total_active_cost + total_closed_cost
    
    text = (
        "📊 **THỐNG KÊ TOÀN HỆ THỐNG**\n\n"
        f"• 👥 Tổng số người dùng: **{total_users}**\n"
        f"• 💳 Tổng hạn mức đã cấp: **${total_credit:.4f}**\n"
        f"• 🔑 Số API Key đang hoạt động: **{active_keys_count}**\n"
        f"• 💸 Tổng chi phí tiêu dùng: **${total_spent:.4f}**\n"
        f"  (Trong đó API đã thu hồi: `${total_closed_cost:.4f}`)"
    )
    
    from .keyboards import admin_menu_keyboard
    if query:
        await query.edit_message_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")


async def admin_overlimit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return
        
    from dashboard.models import CustomerAccount
    from dashboard.services import customer_spent
    
    accounts = await sync_to_async(list)(CustomerAccount.objects.select_related("user"))
    
    overlimit_users = []
    for acc in accounts:
        spent = await sync_to_async(lambda: customer_spent(acc.user))()
        email_val = await sync_to_async(lambda: acc.user.email)()
        if acc.credit_limit <= spent:
            overlimit_users.append((email_val, acc.credit_limit, spent))
            
    if not overlimit_users:
        text = "🔒 **TÀI KHOẢN QUÁ HẠN**\n\nHhiện tại không có tài khoản khách hàng nào bị vượt/hết hạn mức!"
    else:
        text = "🔒 **DANH SÁCH TÀI KHOẢN QUÁ HẠN MỨC:**\n\n"
        for i, (email, limit, spent) in enumerate(overlimit_users, 1):
            text += f"{i}. `{email}`\n"
            text += f"   • Hạn mức: `${limit:.4f}`\n"
            text += f"   • Đã dùng: `${spent:.4f}`\n\n"
            
    from .keyboards import admin_menu_keyboard
    if query:
        await query.edit_message_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")


async def admin_users_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return
        
    from dashboard.models import CustomerAccount
    from datetime import timedelta
    
    accounts = await sync_to_async(list)(
        CustomerAccount.objects.select_related("user").order_by("-created_at")
    )
    
    if not accounts:
        text = "👥 **DANH SÁCH TÀI KHOẢN**\n\nHệ thống hiện chưa có tài khoản khách hàng nào!"
    else:
        text = "👥 **DANH SÁCH TÀI KHOẢN KHÁCH HÀNG:**\n\n"
        for i, acc in enumerate(accounts, 1):
            created_str = acc.created_at.strftime("%d/%m/%Y")
            expiry = acc.created_at + timedelta(days=365)
            expiry_str = expiry.strftime("%d/%m/%Y")
            tg_status = "Đã liên kết 🟢" if acc.telegram_chat_id else "Chưa liên kết 🔴"
            email_val = await sync_to_async(lambda: acc.user.email)()
            
            text += f"{i}. `{email_val}`\n"
            text += f"   • Hạn mức: `${acc.credit_limit:.4f}`\n"
            text += f"   • Đăng ký: {created_str}\n"
            text += f"   • Hạn dùng (1 năm): {expiry_str}\n"
            text += f"   • Telegram: {tg_status}\n\n"
            
    from .keyboards import admin_menu_keyboard
    if query:
        await query.edit_message_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")


async def start_admin_add_credit_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return ConversationHandler.END
        
    text = "💸 **Cộng tiền hạn mức**\n\nVui lòng nhập **Email** của khách hàng bạn muốn cộng tiền:"
    if query:
        await query.edit_message_text(text, reply_markup=back_to_admin_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=back_to_admin_keyboard(), parse_mode="Markdown")
    return ASK_ADMIN_CREDIT_EMAIL


async def handle_admin_credit_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email_text = update.message.text.strip().lower()
    
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    from django.contrib.auth import get_user_model
    User = get_user_model()
    target_user = await sync_to_async(User.objects.filter(email=email_text).first)()
    
    if not target_user:
        await update.message.reply_text(
            f"❌ Không tìm thấy người dùng có email `{email_text}`.\nVui lòng nhập lại hoặc gõ /cancel để hủy:",
            reply_markup=back_to_admin_keyboard(),
            parse_mode="Markdown"
        )
        return ASK_ADMIN_CREDIT_EMAIL
        
    context.user_data["credit_target_email"] = email_text
    await update.message.reply_text(
        f"👤 Đang chọn tài khoản: `{email_text}`\n\nVui lòng nhập số tiền **USD** muốn cộng thêm (ví dụ: 50 hoặc 100):",
        reply_markup=back_to_admin_keyboard(),
        parse_mode="Markdown"
    )
    return ASK_ADMIN_CREDIT_AMOUNT


async def handle_admin_credit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount_text = update.message.text.strip()
    target_email = context.user_data.get("credit_target_email")
    
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    try:
        amount_usd = float(amount_text)
        if amount_usd <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Số tiền không hợp lệ. Vui lòng nhập một số dương lớn hơn 0 (ví dụ: 100):",
            reply_markup=back_to_admin_keyboard()
        )
        return ASK_ADMIN_CREDIT_AMOUNT
        
    from .services import grant_credit_to_user
    success, message = await sync_to_async(lambda: grant_credit_to_user(target_email, amount_usd))()
    
    from .keyboards import admin_menu_keyboard
    if success:
        await update.message.reply_text(
            f"✅ {message}",
            reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\nVui lòng nhập lại số tiền hoặc gõ /cancel để hủy:",
            reply_markup=back_to_admin_keyboard()
        )
        return ASK_ADMIN_CREDIT_AMOUNT


async def cancel_admin_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from .keyboards import admin_menu_keyboard
    await update.message.reply_text(
        "Đã hủy tác vụ cộng tiền.",
        reply_markup=admin_menu_keyboard(),
    )
    return ConversationHandler.END


# Admin Delete User Conversation Flow:
async def start_admin_delete_user_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return ConversationHandler.END
        
    text = "❌ **Xóa tài khoản khách hàng**\n\nVui lòng nhập **Email** của khách hàng bạn muốn xóa vĩnh viễn:"
    if query:
        await query.edit_message_text(text, reply_markup=back_to_admin_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=back_to_admin_keyboard(), parse_mode="Markdown")
    return ASK_ADMIN_DELETE_EMAIL


async def handle_admin_delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email_text = update.message.text.strip().lower()
    
    account = await _require_active_account(update)
    if not account:
        return ConversationHandler.END
        
    from django.contrib.auth import get_user_model
    User = get_user_model()
    target_user = await sync_to_async(User.objects.filter(email=email_text).first)()
    
    if not target_user:
        await update.message.reply_text(
            f"❌ Không tìm thấy người dùng có email `{email_text}`.\nVui lòng nhập lại hoặc gõ /cancel để hủy:",
            reply_markup=back_to_admin_keyboard(),
            parse_mode="Markdown"
        )
        return ASK_ADMIN_DELETE_EMAIL
        
    target_is_admin = await sync_to_async(lambda: bool(target_user.is_superuser or target_user.is_staff))()
    if target_is_admin:
        await update.message.reply_text(
            "❌ Không thể xóa tài khoản Quản trị viên vì lý do bảo mật.\n\nVui lòng nhập email tài khoản khách hàng thường hoặc gõ /cancel để hủy:",
            reply_markup=back_to_admin_keyboard(),
            parse_mode="Markdown"
        )
        return ASK_ADMIN_DELETE_EMAIL
        
    context.user_data["delete_target_user_id"] = target_user.id
    context.user_data["delete_target_email"] = email_text
    
    warning_msg = (
        f"⚠️ **CẢNH BÁO XÓA TÀI KHOẢN VĨNH VIỄN:**\n\n"
        f"Bạn có chắc chắn muốn xóa vĩnh viễn tài khoản `{email_text}`?\n\n"
        f"Hành động này sẽ:\n"
        f"1. Thu hồi và vô hiệu hóa **toàn bộ API Key** của người dùng này trên Anh Lập Trình và hệ thống.\n"
        f"2. Xóa thông tin hạn mức, lịch sử giao dịch và tài khoản người dùng khỏi hệ thống.\n"
        f"3. **Hành động này không thể hoàn tác!**"
    )
    
    from .keyboards import confirm_delete_user_keyboard
    await update.message.reply_text(
        warning_msg,
        reply_markup=confirm_delete_user_keyboard(target_user.id),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def admin_conf_del_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    account = await _require_active_account(update)
    if not account:
        return
        
    is_admin = await _is_admin_account(account)
    if not is_admin:
        return
        
    user_id = int(query.data.split(":")[1])
    
    from django.contrib.auth import get_user_model
    User = get_user_model()
    target_user = await sync_to_async(User.objects.filter(pk=user_id).first)()
    
    if not target_user:
        await query.edit_message_text(
            "❌ Tài khoản này không tồn tại hoặc đã bị xóa trước đó.",
            reply_markup=admin_menu_keyboard()
        )
        return
        
    from .services import delete_customer_account_by_admin
    success, message = await sync_to_async(lambda: delete_customer_account_by_admin(target_user.email))()
    
    if success:
        await query.edit_message_text(
            f"✅ {message}",
            reply_markup=admin_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            f"❌ {message}",
            reply_markup=admin_menu_keyboard()
        )


async def cancel_admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from .keyboards import admin_menu_keyboard
    await update.message.reply_text(
        "Đã hủy tác vụ xóa tài khoản.",
        reply_markup=admin_menu_keyboard(),
    )
    return ConversationHandler.END



async def start_admin_create_user_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        account = await _find_account_by_chat_id(update.effective_chat.id)
        is_admin = await _is_admin_account(account)
        if not is_admin:
            await query.edit_message_text("❌ Bạn không có quyền thực hiện chức năng này.")
            return ConversationHandler.END

        await query.edit_message_text(
            "➕ *Thêm khách hàng mới*\n\n"
            "Vui lòng nhập **Email** của khách hàng muốn tạo:\n"
            "_(Hoặc bấm /cancel để hủy)_",
            parse_mode="Markdown"
        )
    return ASK_ADMIN_CREATE_USER_EMAIL


async def handle_admin_create_user_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    from .services import is_valid_email
    if not is_valid_email(email):
        await update.message.reply_text(
            "⚠️ Email không hợp lệ. Vui lòng nhập lại email đúng định dạng:\n"
            "_(Hoặc bấm /cancel để hủy)_"
        )
        return ASK_ADMIN_CREATE_USER_EMAIL

    context.user_data["create_user_email"] = email.lower()
    await update.message.reply_text(
        f"Email hợp lệ: `{email}`\n\n"
        "Bây giờ, vui lòng nhập **Mật khẩu** khởi tạo cho khách hàng (ít nhất 6 ký tự):\n"
        "_(Hoặc bấm /cancel để hủy)_",
        parse_mode="Markdown"
    )
    return ASK_ADMIN_CREATE_USER_PASSWORD


async def handle_admin_create_user_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text(
            "⚠️ Mật khẩu quá ngắn. Vui lòng nhập mật khẩu có ít nhất 6 ký tự:\n"
            "_(Hoặc bấm /cancel để hủy)_"
        )
        return ASK_ADMIN_CREATE_USER_PASSWORD

    email = context.user_data.get("create_user_email")
    if not email:
        await update.message.reply_text("❌ Đã xảy ra lỗi: Không tìm thấy email trong phiên làm việc. Vui lòng thử lại.")
        return ConversationHandler.END

    from .keyboards import admin_menu_keyboard
    success, message = await sync_to_async(create_customer_account_by_admin)(email, password, 0.0)
    
    if success:
        await update.message.reply_text(
            f"✅ *Thành công!*\n{message}",
            reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ *Thất bại:*\n{message}",
            reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )

    # Dọn dẹp dữ liệu phiên làm việc
    if "create_user_email" in context.user_data:
        del context.user_data["create_user_email"]

    return ConversationHandler.END


async def cancel_admin_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from .keyboards import admin_menu_keyboard
    if "create_user_email" in context.user_data:
        del context.user_data["create_user_email"]
    await update.message.reply_text(
        "Đã hủy tác vụ thêm khách hàng.",
        reply_markup=admin_menu_keyboard(),
    )
    return ConversationHandler.END


def build_application() -> Application:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN chưa được cấu hình trong .env")

    async def post_init(app: Application) -> None:
        from telegram import BotCommand
        commands = [
            BotCommand("start", "Liên kết tài khoản Telegram"),
            BotCommand("me", "Xem thông tin hạn mức & sử dụng"),
            BotCommand("keys", "Xem danh sách API Keys đang chạy"),
            BotCommand("createkey", "Tạo API Key mới nhanh"),
            BotCommand("promo", "Nhập mã khuyến mãi nhận tiền"),
            BotCommand("unlink", "Hủy liên kết tài khoản Telegram"),
            BotCommand("help", "Xem hướng dẫn và trợ giúp"),
        ]
        await app.bot.set_my_commands(commands)

    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        from telegram.error import BadRequest
        if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
            return
            
        logger.error("Lỗi xử lý sự kiện Telegram Bot:", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ Đã xảy ra lỗi hệ thống. Vui lòng thử lại hoặc bấm /start."
                )
            except Exception:
                pass

    application.add_error_handler(global_error_handler)
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("unlink", unlink_command),
            CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
        ],
        states={
            ASK_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
            ASK_REGISTER_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_register_password),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
            ASK_OTP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start), CommandHandler("unlink", unlink_command)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(conversation_handler)
    
    promo_conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_promo_flow, pattern="^enter_promo$"),
            CommandHandler("promo", start_promo_flow),
        ],
        states={
            ASK_PROMO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo_code),
                CallbackQueryHandler(menu_exit_callback, pattern="^main_menu$"),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_promo),
            CallbackQueryHandler(menu_exit_callback, pattern="^main_menu$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(promo_conversation_handler)
    
    create_key_conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_create_key_flow, pattern="^create_key$"),
            CommandHandler("createkey", start_create_key_flow),
        ],
        states={
            ASK_KEY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_key_name),
                CallbackQueryHandler(menu_exit_callback, pattern="^main_menu$"),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_key_creation),
            CallbackQueryHandler(menu_exit_callback, pattern="^main_menu$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(create_key_conversation_handler)

    application.add_handler(CallbackQueryHandler(delete_key_confirm_callback, pattern="^del_key:"))
    application.add_handler(CallbackQueryHandler(delete_key_execute_callback, pattern="^conf_del:"))

    # Admin Panel Handlers
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_overlimit_callback, pattern="^admin_overlimit$"))
    application.add_handler(CallbackQueryHandler(admin_users_list_callback, pattern="^admin_users_list$"))
    application.add_handler(CommandHandler("admin", admin_panel_callback))

    admin_credit_conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_admin_add_credit_flow, pattern="^admin_add_credit$"),
        ],
        states={
            ASK_ADMIN_CREDIT_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_credit_email),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
            ASK_ADMIN_CREDIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_credit_amount),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_admin_credit),
            CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(admin_credit_conversation_handler)

    # Admin Delete User Conversation Flow
    admin_delete_conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_admin_delete_user_flow, pattern="^admin_delete_user$")
        ],
        states={
            ASK_ADMIN_DELETE_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_delete_email),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_admin_delete),
            CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(admin_delete_conversation_handler)

    # Admin Create User Conversation Flow
    admin_create_user_conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_admin_create_user_flow, pattern="^admin_create_user$")
        ],
        states={
            ASK_ADMIN_CREATE_USER_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_create_user_email),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$")
            ],
            ASK_ADMIN_CREATE_USER_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_create_user_password),
                CallbackQueryHandler(restart_flow, pattern="^restart_flow$")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_admin_create_user),
            CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
    application.add_handler(admin_create_user_conversation_handler)

    # Callback for confirming deletion
    application.add_handler(CallbackQueryHandler(admin_conf_del_user_callback, pattern="^admin_conf_del_user:"))

    application.add_handler(CommandHandler("keys", show_keys))
    application.add_handler(CommandHandler("me", my_info))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("unlink", unlink_command))
    application.add_handler(CallbackQueryHandler(show_keys, pattern="^view_keys$"))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(my_info, pattern="^my_info$"))
    application.add_handler(CallbackQueryHandler(help_command, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(unlink_callback, pattern="^unlink_account$"))
    application.add_handler(CallbackQueryHandler(restart_flow, pattern="^restart_flow$"))
    return application


def run_bot() -> None:
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
    app = build_application()
    print("Bot Anh Lập Trình đang chạy và lắng nghe tin nhắn...")
    app.run_polling()
