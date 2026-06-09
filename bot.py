#!/usr/bin/env python3
# bot.py — Hamnaghsheh Bale Bot
# Uses python-telegram-bot 20.x with Bale's Telegram-compatible API

import asyncio
import logging
import json
from aiohttp import web

from telegram import (
    Update, Bot,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

import config
import db
import wp_client

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("hamnaghsheh-bot")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt_price(p: int) -> str:
    return f"{p:,} تومان"

def order_status_emoji(status: str) -> str:
    return {
        "pending":          "⏳",
        "awaiting_payment": "💳",
        "paid":             "✅",
        "in_progress":      "🗺️",
        "completed":        "🎉",
        "cancelled":        "❌",
    }.get(status, "•")

def main_menu_keyboard(is_linked: bool) -> ReplyKeyboardMarkup:
    if is_linked:
        rows = [
            [KeyboardButton("📋 سفارش جدید"), KeyboardButton("📦 سفارش‌های من")],
            [KeyboardButton("📞 پشتیبانی"),    KeyboardButton("👤 حساب من")],
        ]
    else:
        rows = [
            [KeyboardButton("🔐 ورود / ثبت‌نام")],
            [KeyboardButton("📞 پشتیبانی")],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=False)

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = ""):
    uid = str(update.effective_user.id)
    linked = db.is_linked(uid)
    msg = text or ("به ربات همنقشه خوش آمدید 🗺️\nاز منوی زیر یک گزینه انتخاب کنید:" if not linked
                   else "منوی اصلی:")
    await update.effective_message.reply_text(
        msg, reply_markup=main_menu_keyboard(linked), parse_mode=ParseMode.MARKDOWN
    )

# ─────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_state(str(update.effective_user.id))
    await send_main_menu(update, context,
        "سلام! 👋\nبه ربات *همنقشه* خوش آمدید.\n\nاز اینجا می‌توانید سفارش نقشه‌برداری ثبت کنید، وضعیت سفارش‌هایتان را ببینید و اطلاعیه‌های سفارش را دریافت کنید.")

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """For admins to find their Bale user ID"""
    await update.message.reply_text(f"🆔 شناسه بله شما: `{update.effective_user.id}`",
                                    parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────────
# AUTH FLOW
# States: await_mobile → await_otp
# ─────────────────────────────────────────────

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    db.set_state(uid, "await_mobile")
    await update.effective_message.reply_text(
        "📱 لطفاً شماره موبایل خود را وارد کنید:\n_(مثال: 09121234567)_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 بازگشت")]], resize_keyboard=True),
    )

async def handle_mobile_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = str(update.effective_user.id)
    mobile = update.message.text.strip()

    # Check user existence
    user_info = await wp_client.check_user(mobile)
    if not user_info:
        await update.message.reply_text("❌ شماره موبایل نامعتبر است. دوباره امتحان کنید:")
        return

    # Send OTP
    otp_result = await wp_client.send_otp(mobile)
    if not otp_result:
        await update.message.reply_text("⚠️ خطا در ارسال کد. لطفاً دوباره تلاش کنید.")
        return

    if not otp_result.get("sent"):
        remaining = otp_result.get("rate_limit_remaining", 60)
        await update.message.reply_text(
            f"⏱ کد قبلاً ارسال شده. {remaining} ثانیه دیگر امتحان کنید."
        )
        return

    db.set_state(uid, "await_otp", {"mobile": mobile})
    name_hint = f" {user_info['first_name']}" if user_info.get("first_name") else ""
    await update.message.reply_text(
        f"📩 کد تأیید ۶ رقمی به {mobile} ارسال شد.\nلطفاً کد را وارد کنید:",
        parse_mode=ParseMode.MARKDOWN,
    )

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.effective_user.id)
    code = update.message.text.strip()
    state, data = db.get_state(uid)
    mobile = data.get("mobile", "")

    result = await wp_client.verify_otp(mobile, code, uid)
    if not result or not result.get("success"):
        await update.message.reply_text("❌ کد نادرست یا منقضی شده است. دوباره امتحان کنید:")
        return

    db.save_user(uid, result["wp_user_id"], mobile, result["display_name"])
    db.clear_state(uid)

    name = result["display_name"] or "کاربر"
    welcome = f"✅ با موفقیت وارد شدید!\nخوش آمدید *{name}* 🎉" if not result.get("is_new_user") \
              else f"✅ ثبت‌نام با موفقیت انجام شد!\nخوش آمدید *{name}* 🎉\n\n" \
                   "برای تکمیل پروفایل می‌توانید وارد سایت شوید."

    await send_main_menu(update, context, welcome)

# ─────────────────────────────────────────────
# SERVICES & NEW ORDER
# ─────────────────────────────────────────────

async def show_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if not db.is_linked(uid):
        await start_auth(update, context)
        return

    services = await wp_client.get_services()
    if not services:
        await update.effective_message.reply_text("⚠️ در حال حاضر خدمتی فعال نیست.")
        return

    text = "🗺️ *خدمات نقشه‌برداری همنقشه*\n\nیک خدمت انتخاب کنید:\n\n"
    buttons = []
    for s in services:
        text += f"*{s['name']}*\n💰 {fmt_price(s['price'])} هر جلسه\n{s['description'] or ''}\n\n"
        buttons.append([InlineKeyboardButton(
            f"📋 سفارش {s['name']}",
            callback_data=f"order_service:{s['key']}:{s['price']}"
        )])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cb_order_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a service → show quantity selector"""
    query = update.callback_query
    await query.answer()

    uid = str(update.effective_user.id)
    _, service_key, price_str = query.data.split(":")
    price = int(price_str)

    db.set_state(uid, "await_quantity", {"service_key": service_key, "price": price})

    buttons = [
        [
            InlineKeyboardButton("1️⃣ ۱ جلسه",  callback_data=f"qty:1"),
            InlineKeyboardButton("2️⃣ ۲ جلسه",  callback_data=f"qty:2"),
        ],
        [
            InlineKeyboardButton("3️⃣ ۳ جلسه",  callback_data=f"qty:3"),
            InlineKeyboardButton("4️⃣ ۴ جلسه",  callback_data=f"qty:4"),
        ],
        [InlineKeyboardButton("🔙 بازگشت",     callback_data="back_services")],
    ]
    await query.edit_message_text(
        f"📦 تعداد جلسات را انتخاب کنید:\n_(هر جلسه = {fmt_price(price)})_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cb_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected quantity → send deep link to order form"""
    query = update.callback_query
    await query.answer()

    uid = str(update.effective_user.id)
    qty = int(query.data.split(":")[1])
    state, data = db.get_state(uid)

    service_key = data.get("service_key")
    price       = data.get("price", 0)
    total       = price * qty

    user = db.get_user(uid)
    wp_user_id = user["wp_user_id"] if user else None

    # Generate magic login URL → /order-details/ with pre-filled params
    order_url = f"{config.WP_BASE_URL}/order-details/?service={service_key}&qty={qty}"
    login_url = await wp_client.generate_login_url(wp_user_id, order_url) if wp_user_id else order_url

    db.clear_state(uid)

    text = (f"✅ انتخاب شما:\n"
            f"📦 تعداد: *{qty} جلسه*\n"
            f"💰 جمع کل: *{fmt_price(total)}*\n\n"
            f"برای تکمیل سفارش روی دکمه زیر بزنید.\n"
            f"_(فرم آدرس و جزئیات در سایت تکمیل می‌شود)_")

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 تکمیل سفارش در سایت", url=login_url)
        ]]),
    )

# ─────────────────────────────────────────────
# MY ORDERS
# ─────────────────────────────────────────────

async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if not db.is_linked(uid):
        await start_auth(update, context)
        return

    user = db.get_user(uid)
    orders = await wp_client.get_orders(user["wp_user_id"])

    if not orders:
        await update.effective_message.reply_text(
            "📦 هنوز سفارشی ثبت نکرده‌اید.\n\nبرای ثبت سفارش گزینه *📋 سفارش جدید* را انتخاب کنید.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text = "📦 *سفارش‌های شما:*\n\n"
    buttons = []
    for o in orders[:8]:  # max 8 in list
        emoji = order_status_emoji(o["status"])
        text += f"{emoji} `{o['order_number']}` — {o['status_label']}\n"
        label = f"{emoji} {o['order_number']} — {o['status_label']}"
        if o.get("payment_needed"):
            label += " 💳"
        buttons.append([InlineKeyboardButton(label, callback_data=f"view_order:{o['id']}")])

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cb_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid      = str(update.effective_user.id)
    order_id = int(query.data.split(":")[1])
    o        = await wp_client.get_order(order_id)

    if not o:
        await query.edit_message_text("❌ سفارش یافت نشد.")
        return

    # Verify ownership
    user = db.get_user(uid)
    if not user or user["wp_user_id"] != o.get("user_id"):
        await query.edit_message_text("⛔ دسترسی مجاز نیست.")
        return

    emoji = order_status_emoji(o["status"])
    price_line = ""
    if o.get("final_price"):
        price_line = f"💰 مبلغ نهایی: *{fmt_price(o['final_price'])}*\n"
    else:
        price_line = f"💰 مبلغ تخمینی: *{fmt_price(o['requested_total_price'])}*\n"

    text = (
        f"{emoji} *سفارش {o['order_number']}*\n\n"
        f"📌 وضعیت: *{o['status_label']}*\n"
        f"🗺️ خدمت: {o['service_name']}\n"
        f"📦 تعداد: {o['quantity']} جلسه\n"
        f"{price_line}"
        f"📍 آدرس: {o['address']}\n"
        f"📐 مساحت: {o['area_size']}\n"
    )
    if o.get("admin_notes"):
        text += f"\n📝 یادداشت کارشناس:\n_{o['admin_notes']}_\n"

    buttons = [[InlineKeyboardButton("🌐 مشاهده کامل در سایت", url=o["order_url"])]]
    if o.get("payment_needed"):
        user_row = db.get_user(uid)
        pay_url  = await wp_client.generate_login_url(user_row["wp_user_id"], o["order_url"])
        buttons.insert(0, [InlineKeyboardButton("💳 پرداخت", url=pay_url)])

    buttons.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_orders")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# ─────────────────────────────────────────────
# MY ACCOUNT
# ─────────────────────────────────────────────

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user = db.get_user(uid)

    if not user:
        await start_auth(update, context)
        return

    login_url = await wp_client.generate_login_url(user["wp_user_id"], config.WP_BASE_URL + "/dashboard/")

    text = (f"👤 *حساب کاربری*\n\n"
            f"🧑 نام: {user['display_name']}\n"
            f"📱 موبایل: {user['mobile']}\n\n"
            f"برای مدیریت حساب وارد پورتال شوید:")

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 ورود به پورتال", url=login_url)
        ]]),
    )

# ─────────────────────────────────────────────
# SUPPORT
# ─────────────────────────────────────────────

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📞 *پشتیبانی همنقشه*\n\n"
        "برای ارتباط با تیم پشتیبانی:\n\n"
        "📲 تلفن: `021-XXXXXXXX`\n"
        "🕐 ساعت کاری: شنبه تا پنجشنبه ۸–۱۷\n\n"
        "یا از طریق سایت پیام بگذارید:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 ارسال پیام از سایت", url=config.WP_BASE_URL + "/contact/")
        ]]),
    )

# ─────────────────────────────────────────────
# ADMIN: /order_{id} command
# ─────────────────────────────────────────────

async def cmd_admin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid not in [str(a) for a in config.ADMIN_BALE_IDS]:
        return  # silently ignore for non-admins

    text = update.message.text  # e.g. /order_42
    try:
        order_id = int(text.replace("/order_", ""))
    except ValueError:
        return

    o = await wp_client.get_order(order_id)
    if not o:
        await update.message.reply_text("❌ سفارش یافت نشد.")
        return

    emoji = order_status_emoji(o["status"])
    text  = (
        f"{emoji} *سفارش {o['order_number']}*\n\n"
        f"📌 وضعیت: *{o['status_label']}*\n"
        f"🗺️ خدمت: {o['service_name']}\n"
        f"📦 تعداد: {o['quantity']} جلسه\n"
        f"💰 مبلغ درخواستی: {fmt_price(o['requested_total_price'])}\n"
        f"📍 آدرس: {o['address']}\n"
        f"📐 مساحت: {o['area_size']}\n"
        f"📞 تلفن: {o['phone']}\n"
    )

    admin_url = config.WP_BASE_URL + f"/wp-admin/admin.php?page=hamnaghsheh-order-detail&order_id={order_id}"
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔧 مدیریت در پنل", url=admin_url)
        ]]),
    )

# ─────────────────────────────────────────────
# ROUTER: plain text messages
# ─────────────────────────────────────────────

async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.effective_user.id)
    text = update.message.text.strip()
    state, data = db.get_state(uid)

    # State machine
    if state == "await_mobile":
        if text == "🔙 بازگشت":
            db.clear_state(uid)
            await send_main_menu(update, context)
        else:
            await handle_mobile_input(update, context)
        return

    if state == "await_otp":
        if text == "🔙 بازگشت":
            db.clear_state(uid)
            await start_auth(update, context)
        else:
            await handle_otp_input(update, context)
        return

    # Menu buttons
    if text == "🔐 ورود / ثبت‌نام":
        await start_auth(update, context)
    elif text == "📋 سفارش جدید":
        await show_services(update, context)
    elif text == "📦 سفارش‌های من":
        await show_my_orders(update, context)
    elif text == "👤 حساب من":
        await show_account(update, context)
    elif text == "📞 پشتیبانی":
        await show_support(update, context)
    elif text == "🔙 بازگشت":
        db.clear_state(uid)
        await send_main_menu(update, context)
    else:
        await send_main_menu(update, context, "گزینه مورد نظر را از منوی زیر انتخاب کنید:")

# ─────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────

async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data == "back_main":
        await query.answer()
        await send_main_menu(update, context)
    elif data == "back_services":
        await query.answer()
        await show_services(update, context)
    elif data == "back_orders":
        await query.answer()
        await show_my_orders(update, context)
    elif data.startswith("order_service:"):
        await cb_order_service(update, context)
    elif data.startswith("qty:"):
        await cb_qty(update, context)
    elif data.startswith("view_order:"):
        await cb_view_order(update, context)
    else:
        await query.answer("❓ گزینه ناشناخته")

# ─────────────────────────────────────────────
# INTERNAL HTTP SERVER (WP → Bot push)
# WP calls POST /internal/push  {bale_user_id, text, inline_buttons}
# ─────────────────────────────────────────────

def make_internal_app(bot: Bot) -> web.Application:
    app = web.Application()

    async def handle_push(request: web.Request) -> web.Response:
        # Verify secret
        if request.headers.get("X-Bot-Secret") != config.WP_BOT_SECRET:
            return web.Response(status=403, text="Forbidden")

        body = await request.json()
        bale_user_id   = body.get("bale_user_id")
        text           = body.get("text", "")
        inline_buttons = body.get("inline_buttons", [])

        if not bale_user_id or not text:
            return web.Response(status=400, text="Bad Request")

        keyboard = None
        if inline_buttons:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(b["text"], url=b.get("url", ""))
                for b in inline_buttons
            ]])

        try:
            await bot.send_message(
                chat_id=int(bale_user_id),
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
        except Exception as e:
            log.error(f"Push failed to {bale_user_id}: {e}")
            return web.Response(status=500, text=str(e))

        return web.Response(status=200, text="ok")

    app.router.add_post("/internal/push", handle_push)
    return app

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .base_url(f"{config.BALE_API_BASE}/bot")
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_start))
    app.add_handler(CommandHandler("myid",   cmd_myid))

    # /order_NNN for admins
    app.add_handler(MessageHandler(filters.Regex(r"^/order_\d+$"), cmd_admin_order))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(route_callback))

    # Start internal push server alongside the bot
    async def on_startup(app_instance):
        internal = make_internal_app(app_instance.bot)
        runner   = web.AppRunner(internal)
        await runner.setup()
        site = web.TCPSite(runner, config.BOT_INTERNAL_HOST, config.BOT_INTERNAL_PORT)
        await site.start()
        log.info(f"Internal push server running on port {config.BOT_INTERNAL_PORT}")

    app.post_init = on_startup

    log.info("Bot starting in polling mode...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
