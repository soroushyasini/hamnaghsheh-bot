# wp_client.py
# Thin HTTP wrapper for all calls to the WP bot-bridge REST API
import httpx
from config import WP_BASE_URL, WP_BOT_SECRET

BASE = f"{WP_BASE_URL.rstrip('/')}/wp-json/bot/v1"
HEADERS = {"X-Bot-Secret": WP_BOT_SECRET, "Content-Type": "application/json"}
TIMEOUT = 10.0

async def _get(path: str, params: dict = {}) -> dict | list | None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{BASE}{path}", headers=HEADERS, params=params)
        if r.status_code == 200:
            return r.json()
    return None

async def _post(path: str, data: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}{path}", headers=HEADERS, json=data)
        if r.status_code == 200:
            return r.json()
    return None

# ── Auth ──────────────────────────────────────────────────────────────

async def check_user(mobile: str) -> dict | None:
    """Returns {exists, has_password, first_name, wp_user_id}"""
    return await _post("/check-user", {"mobile": mobile})

async def send_otp(mobile: str) -> dict | None:
    """Returns {sent, rate_limit_remaining}"""
    return await _post("/send-otp", {"mobile": mobile})

async def verify_otp(mobile: str, code: str, bale_user_id: str) -> dict | None:
    """Returns {success, wp_user_id, display_name, is_new_user, login_url}"""
    return await _post("/verify-otp", {
        "mobile": mobile,
        "code": code,
        "bale_user_id": bale_user_id,
    })

async def generate_login_url(wp_user_id: int, redirect_to: str = "") -> str | None:
    """Returns a one-time magic login URL"""
    result = await _post("/login-url", {"wp_user_id": wp_user_id, "redirect_to": redirect_to})
    return result.get("url") if result else None

# ── Services ──────────────────────────────────────────────────────────

async def get_services() -> list:
    """Returns [{id, key, name, price, description, image_url}]"""
    result = await _get("/services")
    return result if isinstance(result, list) else []

# ── Orders ────────────────────────────────────────────────────────────

async def get_orders(wp_user_id: int) -> list:
    """Returns list of order summaries for a user"""
    result = await _get(f"/orders/{wp_user_id}")
    return result if isinstance(result, list) else []

async def get_order(order_id: int) -> dict | None:
    """Returns full order detail"""
    return await _get(f"/order/{order_id}")
