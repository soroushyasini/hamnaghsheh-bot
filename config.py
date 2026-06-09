# config.py
# ─────────────────────────────────────────────────────────────────────
# Hamnaghsheh Bale Bot — Configuration
# Copy this file and fill in all values before running the bot.
# ─────────────────────────────────────────────────────────────────────

# ── Bale Bot Token (from @botfather in Bale) ─────────────────────────
BOT_TOKEN = "1186288062:FJf7nh0LfW7p80uAoDXiicKtlx1Dsco_4jM"

# ── Bale API base URL ─────────────────────────────────────────────────
BALE_API_BASE = "https://tapi.bale.ai"

# ── WordPress site URL ────────────────────────────────────────────────
WP_BASE_URL = "https://hamnaghsheh.ir"

# ── Secret key (copy from WP Admin → سفارش‌ها → تنظیمات بات) ─────────
WP_BOT_SECRET = "PASTE_YOUR_SECRET_KEY_HERE"

# ── Bot's own internal HTTP server (for WP push notifications) ───────
# WP will POST to this URL when order status changes
BOT_INTERNAL_HOST = "0.0.0.0"
BOT_INTERNAL_PORT = 8787          # open this port in your firewall

# ── Admin Bale user IDs (to receive new-order notifications) ─────────
# How to find: send /myid to the bot after starting it
ADMIN_BALE_IDS: list[int] = []    # e.g. [123456789, 987654321]

# ── SQLite DB path ────────────────────────────────────────────────────
DB_PATH = "bot_data.db"

# ── Webhook mode (True) or polling mode (False) ───────────────────────
# For production: True + set WEBHOOK_URL + open WEBHOOK_PORT
USE_WEBHOOK = False
WEBHOOK_URL  = "https://YOUR_BOT_SERVER/webhook"   # must be HTTPS
WEBHOOK_PORT = 8443
