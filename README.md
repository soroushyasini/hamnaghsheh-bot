# Hamnaghsheh Bale Bot — راهنمای نصب

## ساختار فایل‌ها

```
hamnaghsheh-bot/
├── bot-bridge.php   ← پلاگین WordPress (روی سرور WP نصب می‌شود)
├── bot.py           ← بات اصلی (روی VPS اجرا می‌شود)
├── config.py        ← تنظیمات (باید پر شود)
├── db.py            ← پایگاه داده SQLite محلی
├── wp_client.py     ← HTTP wrapper برای API وردپرس
└── requirements.txt
```

---

## گام ۱ — نصب پلاگین WordPress

1. فایل `bot-bridge.php` را در یک پوشه مثل `wp-content/plugins/hn-bot-bridge/` آپلود کنید.
2. از پنل وردپرس → پلاگین‌ها → فعال کنید.
3. بعد از فعال‌سازی، به **سفارش‌ها → تنظیمات بات** بروید.
4. کلید مخفی نمایش داده شده را کپی کنید.

### تنظیمات اضافی در WP (از طریق WP-CLI یا مستقیم در DB):

```bash
# URL داخلی بات (WP برای push notification به اینجا POST می‌کند)
wp option update hn_bot_api_url "http://YOUR_BOT_VPS_IP:8787/internal/push"

# شناسه‌های بله ادمین‌ها (برای دریافت نوتیفیکیشن سفارش جدید)
wp option update hn_bot_admin_bale_ids '[123456789]' --format=json
```

---

## گام ۲ — تنظیم بات (روی VPS)

```bash
# نصب Python 3.11+
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### ویرایش `config.py`:

```python
BOT_TOKEN    = "1186288062:..."      # توکن بات از @botfather
WP_BASE_URL  = "https://hamnaghsheh.ir"
WP_BOT_SECRET = "کلید_از_پنل_WP"
BOT_INTERNAL_PORT = 8787             # پورت برای push از WP
ADMIN_BALE_IDS = [شناسه_بله_ادمین]  # با دستور /myid پیدا کنید
```

---

## گام ۳ — اجرا

```bash
# تست اولیه
python bot.py

# اجرای دائمی با systemd
sudo nano /etc/systemd/system/hamnaghsheh-bot.service
```

```ini
[Unit]
Description=Hamnaghsheh Bale Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/hamnaghsheh-bot
ExecStart=/opt/hamnaghsheh-bot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now hamnaghsheh-bot
sudo journalctl -fu hamnaghsheh-bot
```

---

## گام ۴ — پیدا کردن شناسه بله ادمین

1. بات را اجرا کنید.
2. در بله به بات پیام `/myid` بفرستید.
3. عدد نمایش داده شده را در `config.py` → `ADMIN_BALE_IDS` بگذارید.
4. همین عدد را در WP option `hn_bot_admin_bale_ids` هم وارد کنید.

---

## فلوی کامل

```
کاربر: /start
  ↓
منوی اصلی
  ├── ورود/ثبت‌نام → شماره → OTP → لینک به WP
  ├── سفارش جدید  → انتخاب خدمت → تعداد → لینک سایت
  ├── سفارش‌های من → لیست → جزئیات → پرداخت
  └── پشتیبانی

WP (رویدادها) → bot-bridge.php → POST به بات → کاربر پیام می‌گیرد
  ├── سفارش جدید   → پیام به ادمین‌ها
  ├── قیمت تعیین   → پیام به کاربر + دکمه پرداخت
  ├── پرداخت تأیید → پیام به کاربر
  ├── عملیات شروع  → پیام به کاربر
  └── تکمیل شد     → پیام به کاربر
```

---

## نکات امنیتی

- `WP_BOT_SECRET` را در جایی commit نکنید (از `.env` یا environment variable استفاده کنید).
- پورت `8787` را فقط به IP سرور WP باز کنید (firewall rule).
- کلید مخفی WP را دوره‌ای regenerate کنید.
