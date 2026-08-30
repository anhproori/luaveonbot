# -*- coding: utf-8 -*-
"""
BOT TELEGRAM KIẾM TIỀN ONLINE - TÍCH HỢP LINK4M
=================================================
Tác giả: Claude (theo yêu cầu) - 1 file Python duy nhất, tự tạo DB khi chạy.

CHỨC NĂNG:
- Dashboard 1 tin nhắn duy nhất (luôn edit, không spam tin nhắn mới)
- Toàn bộ điều hướng bằng Inline Button
- Thông tin tài khoản: số dư, coin, thống kê thu nhập hôm nay/24h/7 ngày/30 ngày
- Rút tiền: yêu cầu liên kết ngân hàng, min rút 10k (tiền nhiệm vụ) / 50k (tiền ref),
  admin duyệt/từ chối qua nút bấm
- Mời bạn bè: link giới thiệu riêng, +1.000đ / ref xác minh thành công
- Làm nhiệm vụ: tự tạo link rút gọn qua API link4m, mỗi link dùng được đúng 1 lần,
  chỉ đúng user tạo ra mới dùng được, hoàn thành xong tự cộng tiền + coin
- Đổi tool: dùng coin đổi tài khoản tool do admin nạp sẵn theo từng gói
- Xác minh kênh: khi admin thêm bot vào kênh/nhóm, bot tự nhận kênh đó làm kênh
  xác minh bắt buộc, user phải tham gia + bấm xác nhận mới dùng được bot
- Admin panel: chỉ hiện với đúng ADMIN_ID, có thể duyệt rút tiền, gửi thông báo
  broadcast, thêm gói tool, đổi cấu hình (min rút, mức thưởng, api key link4m...)

DEPLOY TRÊN RENDER:
- Kiểu "Background Worker": Start Command = `python bot.py`  (khuyên dùng, đơn giản nhất)
- Kiểu "Web Service": file này tự mở 1 HTTP server nhỏ ở cổng $PORT để Render
  healthcheck không bị fail, nên deploy Web Service cũng chạy được bình thường.

BIẾN MÔI TRƯỜNG (khai báo trong Render > Environment):
- BOT_TOKEN       : token bot Telegram (bắt buộc)
- ADMIN_ID        : id telegram của admin (bắt buộc)
- LINK4M_API_KEY  : api key link4m (có thể đổi sau bằng lệnh /setlink4m trong bot)
"""

import os
import re
import sqlite3
import logging
import uuid
import random
import threading
import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse

import requests
from flask import Flask, render_template_string
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

# ============================================================
# CẤU HÌNH - đổi giá trị mặc định ở đây hoặc set biến môi trường
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8765543353:AAFbd4IYTzk8bUn2njECLbx8Z3Gb_LWa4_A")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8685327154"))
LINK4M_API_KEY_DEFAULT = os.environ.get("LINK4M_API_KEY", "6a93e433c1e0cd622c1112a8")

DB_PATH = os.environ.get("DB_PATH", "bot.db")
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("moneybot")

BOT_USERNAME = None  # sẽ lấy tự động lúc khởi động
MAIN_LOOP = None      # event loop của bot Telegram, để gọi từ thread Flask
BOT_INSTANCE = None   # telegram.Bot, để gửi tin nhắn từ thread Flask

# ============================================================
# DATABASE
# ============================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            task_balance INTEGER DEFAULT 0,
            ref_balance INTEGER DEFAULT 0,
            coin INTEGER DEFAULT 0,
            ref_by INTEGER,
            ref_count INTEGER DEFAULT 0,
            bank_info TEXT,
            verified INTEGER DEFAULT 0,
            last_msg_id INTEGER,
            joined_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            reward_money INTEGER,
            reward_coin INTEGER,
            used INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            source TEXT,
            bank_info TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS income_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            type TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price_coin INTEGER,
            accounts TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS tool_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool_name TEXT,
            account TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()

    defaults = {
        "link4m_api_key": LINK4M_API_KEY_DEFAULT,
        "channel_id": "",
        "channel_title": "",
        "reward_min": "150",
        "reward_max": "500",
        "coin_min": "5",
        "coin_max": "20",
        "ref_bonus": "1000",
        "min_withdraw_task": "10000",
        "min_withdraw_ref": "50000",
        "web_base_url": "",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def cfg(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_cfg(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def create_user(user_id, username, ref_by=None):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, ref_by, joined_at) VALUES (?,?,?,?)",
        (user_id, username or "", ref_by, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def set_last_msg(user_id, msg_id):
    conn = get_conn()
    conn.execute("UPDATE users SET last_msg_id=? WHERE user_id=?", (msg_id, user_id))
    conn.commit()
    conn.close()


def add_balance(user_id, money, coin, source, log_type):
    """source: 'task' hoặc 'ref' -> cộng vào đúng cột balance tương ứng."""
    conn = get_conn()
    col = "task_balance" if source == "task" else "ref_balance"
    conn.execute(
        f"UPDATE users SET {col} = {col} + ?, coin = coin + ? WHERE user_id=?",
        (money, coin, user_id),
    )
    if money:
        conn.execute(
            "INSERT INTO income_log (user_id, amount, type, created_at) VALUES (?,?,?,?)",
            (user_id, money, log_type, datetime.utcnow().isoformat()),
        )
    conn.commit()
    conn.close()


def income_stats(user_id):
    conn = get_conn()
    now = datetime.utcnow()
    ranges = {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "24h": now - timedelta(hours=24),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
    }
    out = {}
    for key, since in ranges.items():
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM income_log WHERE user_id=? AND created_at>=?",
            (user_id, since.isoformat()),
        ).fetchone()
        out[key] = row["s"]
    conn.close()
    return out


def money_fmt(n):
    return f"{int(n):,}".replace(",", ".") + "đ"


# ============================================================
# LINK4M
# ============================================================

LINK4M_ALLOWED_HOSTS = ("link4m.co", "link4m.com", "www.link4m.co", "www.link4m.com")


def _is_valid_link4m_url(candidate: str, destination_url: str) -> bool:
    """
    Chỉ chấp nhận 1 URL là link4m THẬT nếu:
    - Nằm đúng domain link4m (không phải domain bất kỳ khác)
    - KHÔNG trùng và KHÔNG chứa chính link đích bên trong nó
      (tránh trường hợp API trả lỗi có echo lại url gốc, khiến bot tưởng
      nhầm đó là link rút gọn và gửi thẳng link đích cho user - làm user
      hoàn thành nhiệm vụ mà không cần vượt link quảng cáo nào cả).
    """
    if not candidate or not candidate.startswith("http"):
        return False
    try:
        host = urlparse(candidate).netloc.lower()
    except Exception:
        return False
    if host not in LINK4M_ALLOWED_HOSTS:
        return False
    dest = destination_url.strip()
    if candidate.strip() == dest:
        return False
    if dest in candidate:
        return False
    return True


def create_link4m(destination_url: str) -> str | None:
    """
    Gọi API link4m để tạo link rút gọn. Hàm này cố gắng nhận diện nhiều kiểu
    phản hồi khác nhau (JSON với nhiều tên field khác nhau, hoặc plain text
    chỉ chứa mỗi URL), vì API các trang rút gọn link kiểu này không có chuẩn
    thống nhất và có thể đổi format theo thời gian.

    QUAN TRỌNG: mọi URL tìm được đều phải qua _is_valid_link4m_url() để chắc
    chắn đó là link thật sự thuộc domain link4m, không phải link đích bị lấy
    nhầm - nếu không link4m sẽ không được "vượt qua" và nhiệm vụ hoàn thành
    ngay không qua bước quảng cáo nào.

    Nếu vẫn không tạo được link, toàn bộ raw response sẽ được ghi vào log
    (logger.error) để có thể xem trên Render > Logs và chỉnh lại chính xác.
    """
    api_key = cfg("link4m_api_key", LINK4M_API_KEY_DEFAULT)
    api_url = f"https://link4m.co/st?api={api_key}&url={quote(destination_url, safe='')}"

    try:
        resp = requests.get(api_url, timeout=15)
    except Exception as e:
        logger.error("Lỗi kết nối tới API link4m: %s", e)
        return None

    raw_text = resp.text.strip()

    # In log để đối chiếu khi cần - xem trên Render > Logs
    logger.info("link4m API status=%s raw_response=%r", resp.status_code, raw_text[:500])

    if resp.status_code != 200:
        logger.error("link4m API trả về mã lỗi HTTP %s: %s", resp.status_code, raw_text[:500])
        return None

    # Trường hợp 1: phản hồi là JSON
    try:
        data = resp.json()
        if isinstance(data, dict):
            candidates = []
            for key in (
                "shortenedUrl", "shortened_url", "shorten_url", "shortUrl",
                "short_url", "url", "link", "data", "result",
            ):
                val = data.get(key)
                if isinstance(val, str):
                    candidates.append(val)
                if isinstance(val, dict):
                    for inner_key in ("shortenedUrl", "url", "shortUrl", "short_url"):
                        inner = val.get(inner_key)
                        if isinstance(inner, str):
                            candidates.append(inner)
            for c in candidates:
                if _is_valid_link4m_url(c, destination_url):
                    return c
            logger.warning(
                "link4m trả JSON nhưng không có link4m URL hợp lệ nào (bị từ chối để tránh "
                "gửi nhầm link đích): %s", data
            )
            return None
    except ValueError:
        pass  # không phải JSON, thử cách khác bên dưới

    # Trường hợp 2: phản hồi là plain text, chỉ chứa mỗi link
    if raw_text.startswith("http") and _is_valid_link4m_url(raw_text.split()[0], destination_url):
        return raw_text.split()[0]

    # Trường hợp 3: link nằm lẫn trong 1 đoạn text khác - quét tất cả URL tìm thấy,
    # chỉ nhận cái nào thật sự là link4m hợp lệ
    for match in re.finditer(r"https?://\S+", raw_text):
        candidate = match.group(0).rstrip(").,\"'")
        if _is_valid_link4m_url(candidate, destination_url):
            return candidate

    logger.error(
        "Không tìm được link4m URL hợp lệ trong response (có thể API trả lỗi hoặc "
        "chỉ echo lại link đích) - từ chối để tránh bug bỏ qua bước quảng cáo. raw=%r",
        raw_text[:500],
    )
    return None


# ============================================================
# HIỂN THỊ / EDIT TIN NHẮN (dashboard 1 tin nhắn duy nhất)
# ============================================================

async def render(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, text: str, keyboard=None):
    """
    Luôn cố gắng CHỈ GIỮ ĐÚNG 1 TIN NHẮN của bot trong đoạn chat: edit tin
    nhắn cũ trước; nếu edit thất bại thật sự (tin bị xoá, quá cũ, v.v.) thì
    xoá tin cũ (nếu vẫn còn) rồi mới gửi tin mới, tránh dư tin nhắn rác.
    """
    user = get_user(user_id)
    msg_id = user["last_msg_id"] if user else None
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id, text=text,
                reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True,
            )
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return  # nội dung y hệt tin cũ, không cần làm gì thêm
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass  # tin cũ có thể đã bị xoá sẵn - bỏ qua
    sent = await context.bot.send_message(
        chat_id=chat_id, text=text, reply_markup=keyboard,
        parse_mode="HTML", disable_web_page_preview=True,
    )
    set_last_msg(user_id, sent.message_id)


async def render_cb(update: Update, text: str, keyboard=None):
    """Dùng khi trả lời 1 callback query - edit trực tiếp tin nhắn đang bấm."""
    q = update.callback_query
    try:
        await q.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
    except BadRequest:
        pass


# ============================================================
# KIỂM TRA XÁC MINH KÊNH
# ============================================================

async def is_verified(context, user_id) -> bool:
    channel_id = cfg("channel_id", "")
    if not channel_id:
        return True  # chưa cấu hình kênh -> không bắt buộc
    user = get_user(user_id)
    if user and user["verified"]:
        return True
    try:
        member = await context.bot.get_chat_member(channel_id, user_id)
        ok = member.status in ("member", "administrator", "creator")
        if ok:
            conn = get_conn()
            conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()
        return ok
    except Exception:
        return False


def verify_keyboard():
    channel_title = cfg("channel_title", "kênh")
    buttons = []
    channel_id = cfg("channel_id", "")
    if channel_id.startswith("@"):
        buttons.append([InlineKeyboardButton(f"📢 Tham gia {channel_title}", url=f"https://t.me/{channel_id[1:]}")])
    buttons.append([InlineKeyboardButton("✅ Tôi đã tham gia", callback_data="check_verify")])
    return InlineKeyboardMarkup(buttons)


# ============================================================
# GIAO DIỆN MENU
# ============================================================

def main_menu_kb(user_id):
    rows = [
        [InlineKeyboardButton("💰 Thông tin tài khoản", callback_data="menu_account")],
        [InlineKeyboardButton("📝 Làm nhiệm vụ", callback_data="menu_task"),
         InlineKeyboardButton("💸 Rút tiền", callback_data="menu_withdraw")],
        [InlineKeyboardButton("👥 Mời bạn bè", callback_data="menu_ref"),
         InlineKeyboardButton("🔄 Đổi tool", callback_data="menu_tools")],
    ]
    if user_id == ADMIN_ID:
        rows.append([InlineKeyboardButton("⚙️ Quản trị viên", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]])


def welcome_text(user):
    return (
        "🎉 <b>CHÀO MỪNG BẠN ĐẾN VỚI BOT KIẾM TIỀN ONLINE</b>\n\n"
        f"💰 Số dư: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"🪙 Coin: <b>{user['coin']}</b>\n\n"
        "Chọn chức năng bên dưới 👇"
    )


# ============================================================
# HANDLERS: /start
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    chat_id = update.effective_chat.id
    args = context.args

    existing = get_user(user_tg.id)
    if not existing:
        ref_by = None
        if args and args[0].startswith("ref_"):
            try:
                ref_by = int(args[0].split("_", 1)[1])
                if ref_by == user_tg.id:
                    ref_by = None
            except ValueError:
                ref_by = None
        create_user(user_tg.id, user_tg.username or user_tg.first_name, ref_by)
        existing = get_user(user_tg.id)

    # xử lý deep-link hoàn thành nhiệm vụ: task_<token>
    if args and args[0].startswith("task_"):
        await complete_task(update, context, args[0].split("_", 1)[1])
        return

    # kiểm tra xác minh kênh
    if not await is_verified(context, user_tg.id):
        await render(
            context, user_tg.id, chat_id,
            "🔒 <b>Yêu cầu tham gia kênh để sử dụng bot</b>\n\n"
            "Vui lòng tham gia kênh/group bên dưới rồi bấm <b>Tôi đã tham gia</b>.",
            verify_keyboard(),
        )
        return

    user = get_user(user_tg.id)
    await render(context, user_tg.id, chat_id, welcome_text(user), main_menu_kb(user_tg.id))


async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_tg = update.effective_user
    chat_id = update.effective_chat.id
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE token=?", (token,)).fetchone()

    if not row:
        conn.close()
        await render(context, user_tg.id, chat_id, "❌ Link nhiệm vụ không hợp lệ hoặc không tồn tại.", back_kb())
        return
    if row["used"]:
        conn.close()
        await render(context, user_tg.id, chat_id, "⚠️ Link này đã được sử dụng trước đó (chỉ dùng được 1 lần).", back_kb())
        return
    if row["user_id"] != user_tg.id:
        conn.close()
        await render(context, user_tg.id, chat_id, "🚫 Link này không phải của bạn, không thể sử dụng.", back_kb())
        return

    conn.execute("UPDATE tasks SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()

    add_balance(user_tg.id, row["reward_money"], row["reward_coin"], "task", "task")

    user = get_user(user_tg.id)
    await render(
        context, user_tg.id, chat_id,
        "✅ <b>HOÀN THÀNH NHIỆM VỤ THÀNH CÔNG!</b>\n\n"
        f"+ {money_fmt(row['reward_money'])}\n"
        f"+ {row['reward_coin']} coin\n\n"
        f"💰 Số dư hiện tại: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"🪙 Coin hiện tại: <b>{user['coin']}</b>",
        back_kb(),
    )


# ============================================================
# CALLBACK QUERY ROUTER
# ============================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    user_id = update.effective_user.id
    await q.answer()

    if data == "check_verify":
        if await is_verified(context, user_id):
            user = get_user(user_id)
            await render_cb(update, welcome_text(user), main_menu_kb(user_id))
        else:
            await q.answer("Bạn chưa tham gia kênh, vui lòng tham gia rồi thử lại!", show_alert=True)
        return

    # mọi chức năng khác đều yêu cầu đã xác minh
    if not await is_verified(context, user_id):
        await render_cb(update, "🔒 Vui lòng tham gia kênh trước đã!", verify_keyboard())
        return

    if data == "menu_main":
        user = get_user(user_id)
        await render_cb(update, welcome_text(user), main_menu_kb(user_id))

    elif data == "menu_account":
        await show_account(update, context)

    elif data == "menu_task":
        await do_task(update, context)

    elif data == "menu_withdraw":
        await show_withdraw_menu(update, context)

    elif data.startswith("wd_"):
        await handle_withdraw_amount(update, context, data)

    elif data == "menu_ref":
        await show_ref(update, context)

    elif data == "menu_tools":
        await show_tools(update, context)

    elif data.startswith("buytool_"):
        await buy_tool(update, context, int(data.split("_", 1)[1]))

    elif data == "menu_admin" and user_id == ADMIN_ID:
        await show_admin(update, context)

    elif data.startswith("adm_") and user_id == ADMIN_ID:
        await admin_router(update, context, data)


# ---------------- Thông tin tài khoản ----------------

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    stats = income_stats(user_id)
    text = (
        "📊 <b>THÔNG TIN TÀI KHOẢN</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Tổng số dư: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"   ├ Từ nhiệm vụ: {money_fmt(user['task_balance'])}\n"
        f"   └ Từ giới thiệu: {money_fmt(user['ref_balance'])}\n"
        f"🪙 Coin: <b>{user['coin']}</b>\n"
        f"👥 Số ref: <b>{user['ref_count']}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "📈 <b>Thống kê thu nhập</b>\n"
        f"   • Hôm nay: {money_fmt(stats['today'])}\n"
        f"   • 24 giờ: {money_fmt(stats['24h'])}\n"
        f"   • 7 ngày: {money_fmt(stats['week'])}\n"
        f"   • 30 ngày: {money_fmt(stats['month'])}\n"
    )
    await render_cb(update, text, back_kb())


# ---------------- Làm nhiệm vụ ----------------

async def do_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    base_url = cfg("web_base_url", "") or os.environ.get("RENDER_EXTERNAL_URL", "")
    base_url = base_url.rstrip("/")
    if not base_url:
        await render_cb(
            update,
            "❌ Admin chưa cấu hình địa chỉ web xác nhận nhiệm vụ.\n\n"
            "(Admin: gõ lệnh <code>/setweburl https://ten-app-cua-ban.onrender.com</code> "
            "để đặt, hoặc bot sẽ tự nhận nếu deploy dạng Web Service trên Render.)",
            back_kb(),
        )
        return

    token = uuid.uuid4().hex
    reward_money = random.randint(int(cfg("reward_min", 150)), int(cfg("reward_max", 500)))
    reward_coin = random.randint(int(cfg("coin_min", 5)), int(cfg("coin_max", 20)))

    conn = get_conn()
    conn.execute(
        "INSERT INTO tasks (token, user_id, reward_money, reward_coin, used, created_at) VALUES (?,?,?,?,0,?)",
        (token, user_id, reward_money, reward_coin, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    # Link đích là trang web riêng /<user_id>/<token> - chỉ đúng user này, đúng token
    # này mới xác nhận hoàn thành được, và chỉ dùng được đúng 1 lần.
    dest = f"{base_url}/{user_id}/{token}"
    short_link = create_link4m(dest)

    if not short_link:
        await render_cb(
            update,
            "❌ Không tạo được link nhiệm vụ lúc này, vui lòng thử lại sau ít phút.\n\n"
            "(Admin: xem chi tiết lỗi trong log server - Render > Logs, tìm dòng "
            "'link4m API' để biết chính xác API đã trả về gì.)",
            back_kb(),
        )
        return

    text = (
        "📝 <b>NHIỆM VỤ MỚI</b>\n\n"
        f"Phần thưởng: <b>{money_fmt(reward_money)}</b> + <b>{reward_coin} coin</b>\n\n"
        "👉 Bấm vào link bên dưới, vượt qua các bước quảng cáo.\n"
        "Sau khi hoàn thành, trang web sẽ xác nhận và bot <b>tự động cộng tiền</b> ngay lập tức.\n\n"
        f"🔗 {short_link}\n\n"
        "⚠️ Link chỉ dùng được 1 lần và chỉ mình bạn dùng được."
    )
    await render_cb(update, text, back_kb())


# ---------------- Rút tiền ----------------

async def show_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    min_task = int(cfg("min_withdraw_task", 10000))
    min_ref = int(cfg("min_withdraw_ref", 50000))

    if not user["bank_info"]:
        context.user_data["awaiting"] = "bank_info"
        await render_cb(
            update,
            "🏦 <b>LIÊN KẾT NGÂN HÀNG</b>\n\n"
            "Bạn chưa liên kết ngân hàng. Vui lòng gửi tin nhắn theo cú pháp:\n\n"
            "<code>Tên ngân hàng | Số tài khoản | Chủ tài khoản</code>\n\n"
            "Ví dụ: <code>MB Bank | 0123456789 | NGUYEN VAN A</code>",
            back_kb(),
        )
        return

    total = user["task_balance"] + user["ref_balance"]
    text = (
        "💸 <b>RÚT TIỀN</b>\n\n"
        f"💰 Số dư khả dụng: <b>{money_fmt(total)}</b>\n"
        f"🏦 Ngân hàng: <code>{user['bank_info']}</code>\n\n"
        f"• Min rút (tiền nhiệm vụ): {money_fmt(min_task)}\n"
        f"• Min rút (có dùng tiền ref): {money_fmt(min_ref)}\n\n"
        "Chọn số tiền muốn rút:"
    )
    options = [min_task, min_ref, 100000, 200000]
    rows = []
    row = []
    for i, amt in enumerate(sorted(set(options))):
        row.append(InlineKeyboardButton(money_fmt(amt), callback_data=f"wd_{amt}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Nhập số tiền khác", callback_data="wd_custom")])
    rows.append([InlineKeyboardButton("🔄 Đổi ngân hàng", callback_data="wd_changebank")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")])
    await render_cb(update, text, InlineKeyboardMarkup(rows))


async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    if data == "wd_custom":
        context.user_data["awaiting"] = "withdraw_amount"
        await render_cb(update, "✏️ Nhập số tiền muốn rút (chỉ nhập số):", back_kb())
        return
    if data == "wd_changebank":
        context.user_data["awaiting"] = "bank_info"
        await render_cb(update, "🏦 Gửi thông tin ngân hàng mới theo cú pháp:\n<code>Ngân hàng | STK | Chủ TK</code>", back_kb())
        return
    amount = int(data.split("_", 1)[1])
    await create_withdrawal(update, context, amount)


async def create_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user_id = update.effective_user.id
    user = get_user(user_id)
    min_task = int(cfg("min_withdraw_task", 10000))
    min_ref = int(cfg("min_withdraw_ref", 50000))
    total = user["task_balance"] + user["ref_balance"]

    if amount > total:
        await render_cb(update, f"❌ Số dư không đủ. Số dư hiện tại: {money_fmt(total)}", back_kb())
        return

    source = "task" if amount <= user["task_balance"] else "ref"
    min_required = min_task if source == "task" else min_ref
    if amount < min_required:
        await render_cb(update, f"❌ Số tiền rút tối thiểu là {money_fmt(min_required)} cho loại số dư này.", back_kb())
        return

    conn = get_conn()
    # trừ tiền: ưu tiên trừ task_balance trước, phần còn thiếu trừ ref_balance
    from_task = min(amount, user["task_balance"])
    from_ref = amount - from_task
    conn.execute(
        "UPDATE users SET task_balance = task_balance - ?, ref_balance = ref_balance - ? WHERE user_id=?",
        (from_task, from_ref, user_id),
    )
    conn.execute(
        "INSERT INTO withdrawals (user_id, amount, source, bank_info, status, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, amount, source, user["bank_info"], "pending", datetime.utcnow().isoformat()),
    )
    wd_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()

    await render_cb(
        update,
        f"✅ Đã gửi yêu cầu rút <b>{money_fmt(amount)}</b>.\nAdmin sẽ duyệt trong thời gian sớm nhất.",
        back_kb(),
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"adm_wdok_{wd_id}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"adm_wdno_{wd_id}"),
    ]])
    await context.bot.send_message(
        ADMIN_ID,
        f"💸 <b>YÊU CẦU RÚT TIỀN MỚI #{wd_id}</b>\n"
        f"User: <code>{user_id}</code>\n"
        f"Số tiền: {money_fmt(amount)}\n"
        f"Ngân hàng: {user['bank_info']}",
        reply_markup=kb, parse_mode="HTML",
    )


# ---------------- Mời bạn bè ----------------

async def show_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username
    user = get_user(user_id)
    bonus = int(cfg("ref_bonus", 1000))
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    text = (
        "👥 <b>MỜI BẠN BÈ - NHẬN THƯỞNG</b>\n\n"
        f"Mỗi người bạn mời tham gia & xác minh thành công bạn nhận <b>{money_fmt(bonus)}</b>.\n\n"
        f"🔗 Link giới thiệu của bạn:\n<code>{link}</code>\n\n"
        f"👥 Số bạn đã mời: <b>{user['ref_count']}</b>"
    )
    await render_cb(update, text, back_kb())


# ---------------- Đổi tool ----------------

async def show_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    tools = conn.execute("SELECT * FROM tools").fetchall()
    conn.close()
    if not tools:
        await render_cb(update, "🔄 <b>ĐỔI TOOL</b>\n\nHiện chưa có gói tool nào.", back_kb())
        return
    text = "🔄 <b>ĐỔI TOOL</b>\n\nChọn gói bạn muốn đổi:\n"
    rows = []
    for t in tools:
        stock = len([a for a in t["accounts"].split("\n") if a.strip()])
        text += f"\n• <b>{t['name']}</b> - {t['price_coin']} coin (còn {stock})"
        rows.append([InlineKeyboardButton(f"{t['name']} ({t['price_coin']} coin)", callback_data=f"buytool_{t['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")])
    await render_cb(update, text, InlineKeyboardMarkup(rows))


async def buy_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, tool_id: int):
    user_id = update.effective_user.id
    user = get_user(user_id)
    conn = get_conn()
    tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
    if not tool:
        conn.close()
        await render_cb(update, "❌ Gói tool không tồn tại.", back_kb())
        return
    accounts = [a for a in tool["accounts"].split("\n") if a.strip()]
    if not accounts:
        conn.close()
        await render_cb(update, "❌ Gói tool đã hết hàng.", back_kb())
        return
    if user["coin"] < tool["price_coin"]:
        conn.close()
        await render_cb(update, f"❌ Bạn không đủ coin. Cần {tool['price_coin']} coin.", back_kb())
        return

    acc = accounts.pop(0)
    conn.execute("UPDATE tools SET accounts=? WHERE id=?", ("\n".join(accounts), tool_id))
    conn.execute("UPDATE users SET coin = coin - ? WHERE user_id=?", (tool["price_coin"], user_id))
    conn.execute(
        "INSERT INTO tool_redemptions (user_id, tool_name, account, created_at) VALUES (?,?,?,?)",
        (user_id, tool["name"], acc, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    await render_cb(
        update,
        f"✅ <b>Đổi tool thành công!</b>\n\nGói: {tool['name']}\nThông tin tài khoản:\n<code>{acc}</code>",
        back_kb(),
    )


# ============================================================
# ADMIN
# ============================================================

def admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Gửi thông báo", callback_data="adm_broadcast")],
        [InlineKeyboardButton("✅ Duyệt rút tiền đang chờ", callback_data="adm_pending")],
        [InlineKeyboardButton("➕ Thêm gói tool", callback_data="adm_addtool")],
        [InlineKeyboardButton("⚙️ Cấu hình", callback_data="adm_config")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
    ])


async def show_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    conn.close()
    text = (
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        f"👥 Tổng user: {total_users}\n"
        f"⏳ Yêu cầu rút tiền đang chờ: {pending}\n"
        f"📡 Kênh xác minh: {cfg('channel_id') or 'chưa đặt'}\n"
        f"🔑 Link4m API key: <code>{cfg('link4m_api_key')}</code>"
    )
    await render_cb(update, text, admin_menu_kb())


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    if data == "adm_broadcast":
        context.user_data["awaiting"] = "broadcast"
        await render_cb(update, "📢 Gửi nội dung bạn muốn thông báo tới toàn bộ user (gửi tin nhắn tiếp theo):", back_kb())

    elif data == "adm_pending":
        await show_pending_withdrawals(update, context)

    elif data == "adm_addtool":
        context.user_data["awaiting"] = "addtool_name"
        await render_cb(update, "➕ Nhập <b>tên gói tool</b>:", back_kb())

    elif data == "adm_config":
        text = (
            "⚙️ <b>CẤU HÌNH</b>\n\n"
            "Dùng các lệnh sau (gõ trực tiếp trong chat, không qua nút):\n"
            "<code>/setlink4m &lt;api_key&gt;</code>\n"
            "<code>/setreward &lt;min&gt; &lt;max&gt;</code>\n"
            "<code>/setrefbonus &lt;số tiền&gt;</code>\n"
            "<code>/setminwd &lt;min_task&gt; &lt;min_ref&gt;</code>\n"
            "<code>/setweburl &lt;https://ten-app.onrender.com&gt;</code>\n\n"
            f"🌐 Web base url hiện tại: <code>{cfg('web_base_url') or 'chưa đặt'}</code>\n\n"
            "📡 Để đặt <b>kênh xác minh</b>: thêm bot làm admin trong kênh/group, "
            "bot sẽ tự động lưu kênh đó."
        )
        await render_cb(update, text, back_kb())

    elif data.startswith("adm_wdok_") or data.startswith("adm_wdno_"):
        await handle_withdraw_decision(update, context, data)


async def show_pending_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id").fetchall()
    conn.close()
    if not rows:
        await render_cb(update, "✅ Không có yêu cầu rút tiền nào đang chờ.", back_kb())
        return
    text = "⏳ <b>YÊU CẦU RÚT TIỀN ĐANG CHỜ</b>\n\n"
    for r in rows:
        text += f"#{r['id']} - user <code>{r['user_id']}</code> - {money_fmt(r['amount'])} - {r['bank_info']}\n"
    await render_cb(update, text, admin_menu_kb())


async def handle_withdraw_decision(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    approve = data.startswith("adm_wdok_")
    wd_id = int(data.rsplit("_", 1)[1])
    conn = get_conn()
    row = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wd_id,)).fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        await q_answer(update, "Yêu cầu này đã được xử lý rồi.")
        return

    new_status = "approved" if approve else "rejected"
    conn.execute("UPDATE withdrawals SET status=? WHERE id=?", (new_status, wd_id))

    if not approve:
        # hoàn tiền lại cho user
        col = "task_balance" if row["source"] == "task" else "ref_balance"
        conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id=?", (row["amount"], row["user_id"]))

    conn.commit()
    conn.close()

    await render_cb(update, f"Đã {'duyệt ✅' if approve else 'từ chối ❌'} yêu cầu #{wd_id}.", admin_menu_kb())
    try:
        msg = (
            f"✅ Yêu cầu rút {money_fmt(row['amount'])} của bạn đã được <b>duyệt</b>."
            if approve else
            f"❌ Yêu cầu rút {money_fmt(row['amount'])} của bạn đã bị <b>từ chối</b>, tiền đã được hoàn lại."
        )
        await context.bot.send_message(row["user_id"], msg, parse_mode="HTML")
    except Exception:
        pass


async def q_answer(update, text):
    try:
        await update.callback_query.answer(text, show_alert=True)
    except Exception:
        pass


# ============================================================
# TEXT MESSAGE HANDLER (dùng cho các bước nhập liệu: bank info, rút tiền,
# broadcast, thêm tool, cấu hình...)
# ============================================================

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    awaiting = context.user_data.get("awaiting")
    text = update.message.text.strip()

    if awaiting == "bank_info":
        parts = [p.strip() for p in text.split("|")]
        if len(parts) != 3:
            await update.message.reply_text(
                "❌ Sai cú pháp. Gửi lại theo dạng:\n<code>Ngân hàng | STK | Chủ TK</code>",
                parse_mode="HTML",
            )
            return
        conn = get_conn()
        conn.execute("UPDATE users SET bank_info=? WHERE user_id=?", (text, user_id))
        conn.commit()
        conn.close()
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("✅ Đã lưu thông tin ngân hàng. Vào lại menu Rút tiền để tiếp tục.")
        return

    if awaiting == "withdraw_amount":
        if not text.isdigit():
            await update.message.reply_text("❌ Vui lòng nhập số hợp lệ.")
            return
        context.user_data.pop("awaiting", None)
        amount = int(text)
        fake_update = update  # tái sử dụng hàm create_withdrawal (không cần callback_query ở đây)
        await create_withdrawal_from_message(update, context, amount)
        return

    # ---------- ADMIN ONLY ----------
    if user_id != ADMIN_ID:
        return

    if awaiting == "broadcast":
        context.user_data.pop("awaiting", None)
        conn = get_conn()
        ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]
        conn.close()
        sent, failed = 0, 0
        for uid in ids:
            try:
                await context.bot.copy_message(uid, update.effective_chat.id, update.message.message_id)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(f"📢 Đã gửi tới {sent} user (lỗi {failed}).")
        return

    if awaiting == "addtool_name":
        context.user_data["new_tool_name"] = text
        context.user_data["awaiting"] = "addtool_price"
        await update.message.reply_text("Nhập <b>giá coin</b> cho gói này:", parse_mode="HTML")
        return

    if awaiting == "addtool_price":
        if not text.isdigit():
            await update.message.reply_text("❌ Vui lòng nhập số.")
            return
        context.user_data["new_tool_price"] = int(text)
        context.user_data["awaiting"] = "addtool_accounts"
        await update.message.reply_text(
            "Nhập danh sách tài khoản, mỗi dòng 1 tài khoản, dạng:\n<code>user:pass</code>",
            parse_mode="HTML",
        )
        return

    if awaiting == "addtool_accounts":
        name = context.user_data.pop("new_tool_name")
        price = context.user_data.pop("new_tool_price")
        context.user_data.pop("awaiting", None)
        conn = get_conn()
        conn.execute("INSERT INTO tools (name, price_coin, accounts) VALUES (?,?,?)", (name, price, text))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Đã thêm gói tool <b>{name}</b>.", parse_mode="HTML")
        return


async def create_withdrawal_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user_id = update.effective_user.id
    user = get_user(user_id)
    min_task = int(cfg("min_withdraw_task", 10000))
    min_ref = int(cfg("min_withdraw_ref", 50000))
    total = user["task_balance"] + user["ref_balance"]

    if amount > total:
        await update.message.reply_text(f"❌ Số dư không đủ. Số dư hiện tại: {money_fmt(total)}")
        return
    source = "task" if amount <= user["task_balance"] else "ref"
    min_required = min_task if source == "task" else min_ref
    if amount < min_required:
        await update.message.reply_text(f"❌ Số tiền rút tối thiểu là {money_fmt(min_required)}.")
        return

    conn = get_conn()
    from_task = min(amount, user["task_balance"])
    from_ref = amount - from_task
    conn.execute(
        "UPDATE users SET task_balance = task_balance - ?, ref_balance = ref_balance - ? WHERE user_id=?",
        (from_task, from_ref, user_id),
    )
    conn.execute(
        "INSERT INTO withdrawals (user_id, amount, source, bank_info, status, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, amount, source, user["bank_info"], "pending", datetime.utcnow().isoformat()),
    )
    wd_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Đã gửi yêu cầu rút {money_fmt(amount)}, chờ admin duyệt.")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"adm_wdok_{wd_id}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"adm_wdno_{wd_id}"),
    ]])
    await context.bot.send_message(
        ADMIN_ID,
        f"💸 YÊU CẦU RÚT TIỀN MỚI #{wd_id}\nUser: {user_id}\nSố tiền: {money_fmt(amount)}\nNgân hàng: {user['bank_info']}",
        reply_markup=kb,
    )


# ============================================================
# LỆNH ADMIN CẤU HÌNH NHANH (gõ trực tiếp)
# ============================================================

async def admin_only(update: Update) -> bool:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Bạn không có quyền dùng lệnh này.")
        return False
    return True


async def cmd_setlink4m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Cú pháp: /setlink4m <api_key>")
        return
    set_cfg("link4m_api_key", context.args[0])
    await update.message.reply_text("✅ Đã cập nhật API key link4m.")


async def cmd_setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Cú pháp: /setreward <min> <max>")
        return
    set_cfg("reward_min", context.args[0])
    set_cfg("reward_max", context.args[1])
    await update.message.reply_text("✅ Đã cập nhật mức thưởng nhiệm vụ.")


async def cmd_setrefbonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Cú pháp: /setrefbonus <số tiền>")
        return
    set_cfg("ref_bonus", context.args[0])
    await update.message.reply_text("✅ Đã cập nhật thưởng giới thiệu.")


async def cmd_setminwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Cú pháp: /setminwd <min_task> <min_ref>")
        return
    set_cfg("min_withdraw_task", context.args[0])
    set_cfg("min_withdraw_ref", context.args[1])
    await update.message.reply_text("✅ Đã cập nhật min rút tiền.")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    await update.message.reply_text(
        f"⚙️ Admin panel\n👥 Tổng user: {total_users}",
        reply_markup=admin_menu_kb(),
    )


# ============================================================
# TỰ ĐỘNG NHẬN KÊNH XÁC MINH KHI ADMIN THÊM BOT VÀO KÊNH/GROUP
# ============================================================

async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if cm.new_chat_member.status in ("administrator", "member"):
        chat = cm.chat
        adder = cm.from_user.id
        if adder != ADMIN_ID:
            return
        if chat.type in ("channel", "group", "supergroup"):
            channel_id = f"@{chat.username}" if chat.username else str(chat.id)
            set_cfg("channel_id", channel_id)
            set_cfg("channel_title", chat.title or channel_id)
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"✅ Đã đặt <b>{chat.title}</b> ({channel_id}) làm kênh xác minh bắt buộc.",
                    parse_mode="HTML",
                )
            except Exception:
                pass


# ============================================================
# WEB APP (Flask) - trang xác nhận hoàn thành nhiệm vụ link4m
# URL dạng: https://ten-app.onrender.com/<user_id>/<token>
# ============================================================

flask_app = Flask(__name__)

PAGE_BASE = """
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: 'Segoe UI', Roboto, Arial, sans-serif;
    background: linear-gradient(135deg, {{ grad1 }} 0%, {{ grad2 }} 100%);
    padding: 20px;
  }}
  .card {{
    background: #fff; border-radius: 20px; padding: 40px 32px; max-width: 420px; width: 100%;
    text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.25);
  }}
  .icon {{ font-size: 64px; margin-bottom: 10px; }}
  h1 {{ font-size: 22px; color: #222; margin: 10px 0; }}
  p {{ color: #666; font-size: 15px; line-height: 1.6; }}
  .reward {{
    background: linear-gradient(135deg, #11998e, #38ef7d);
    color: #fff; border-radius: 14px; padding: 18px; margin: 20px 0; font-size: 20px; font-weight: bold;
  }}
  .btn {{
    display: inline-block; margin-top: 16px; padding: 12px 28px; border-radius: 30px;
    background: #229ED9; color: #fff; text-decoration: none; font-weight: 600; font-size: 15px;
  }}
  .footer {{ margin-top: 24px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{{ icon }}</div>
    <h1>{{ title }}</h1>
    <p>{{ message }}</p>
    {% if reward %}<div class="reward">{{ reward }}</div>{% endif %}
    <a class="btn" href="https://t.me/{{ bot_username }}">Quay lại Bot Telegram</a>
    <div class="footer">Bot Kiếm Tiền Online</div>
  </div>
</body>
</html>
"""


async def notify_task_complete(user_id: int, money: int, coin: int):
    """
    Gửi/edit tin nhắn dashboard trên Telegram ngay khi user hoàn thành nhiệm vụ
    qua web. Luôn chỉ giữ đúng 1 tin nhắn: edit tin cũ trước, nếu thất bại thật
    sự thì xoá tin cũ (nếu còn) rồi mới gửi tin mới.
    """
    user = get_user(user_id)
    if not user:
        return
    text = (
        "✅ <b>HOÀN THÀNH NHIỆM VỤ THÀNH CÔNG!</b>\n\n"
        f"+ {money_fmt(money)}\n"
        f"+ {coin} coin\n\n"
        f"💰 Số dư hiện tại: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"🪙 Coin hiện tại: <b>{user['coin']}</b>"
    )
    kb = back_kb()
    msg_id = user["last_msg_id"]
    if msg_id:
        try:
            await BOT_INSTANCE.edit_message_text(
                chat_id=user_id, message_id=msg_id, text=text, reply_markup=kb, parse_mode="HTML"
            )
            return
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return
            try:
                await BOT_INSTANCE.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass  # tin cũ có thể đã bị xoá sẵn - bỏ qua
    try:
        sent = await BOT_INSTANCE.send_message(chat_id=user_id, text=text, reply_markup=kb, parse_mode="HTML")
        set_last_msg(user_id, sent.message_id)
    except Exception as e:
        logger.warning("Không gửi được thông báo Telegram cho user %s: %s", user_id, e)


@flask_app.route("/")
def web_health():
    return "Bot is running", 200


@flask_app.route("/<int:user_id>/<token>")
def web_complete_task(user_id, token):
    # chỉ chấp nhận token dạng hex (từ uuid4().hex) để tránh truy vấn linh tinh
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        return render_template_string(
            PAGE_BASE, title="Link không hợp lệ", icon="❌",
            message="Đường dẫn không đúng định dạng.", reward=None,
            bot_username=BOT_USERNAME or "", grad1="#ff5f6d", grad2="#ffc371",
        ), 400

    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE token=?", (token,)).fetchone()

    if not row:
        conn.close()
        return render_template_string(
            PAGE_BASE, title="Link không tồn tại", icon="❌",
            message="Link nhiệm vụ này không tồn tại hoặc đã hết hạn.", reward=None,
            bot_username=BOT_USERNAME or "", grad1="#ff5f6d", grad2="#ffc371",
        ), 404

    if row["used"]:
        conn.close()
        return render_template_string(
            PAGE_BASE, title="Link đã được sử dụng", icon="⚠️",
            message="Link này chỉ dùng được đúng 1 lần và đã được sử dụng trước đó. "
                    "Vui lòng quay lại bot để lấy nhiệm vụ mới.", reward=None,
            bot_username=BOT_USERNAME or "", grad1="#f7971e", grad2="#ffd200",
        ), 410

    if row["user_id"] != user_id:
        conn.close()
        return render_template_string(
            PAGE_BASE, title="Link không thuộc về bạn", icon="🚫",
            message="Link nhiệm vụ này được tạo cho một tài khoản khác, không thể sử dụng.", reward=None,
            bot_username=BOT_USERNAME or "", grad1="#ff5f6d", grad2="#ffc371",
        ), 403

    conn.execute("UPDATE tasks SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()

    add_balance(user_id, row["reward_money"], row["reward_coin"], "task", "task")

    if MAIN_LOOP:
        try:
            asyncio.run_coroutine_threadsafe(
                notify_task_complete(user_id, row["reward_money"], row["reward_coin"]), MAIN_LOOP
            )
        except Exception as e:
            logger.error("Không lên lịch được thông báo Telegram: %s", e)

    return render_template_string(
        PAGE_BASE, title="Hoàn thành nhiệm vụ!", icon="🎉",
        message="Bạn đã hoàn thành nhiệm vụ thành công. Phần thưởng đã được cộng thẳng vào tài khoản Telegram của bạn.",
        reward=f"+ {money_fmt(row['reward_money'])}  •  + {row['reward_coin']} coin",
        bot_username=BOT_USERNAME or "", grad1="#11998e", grad2="#38ef7d",
    ), 200


def run_web_server():
    try:
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
    except OSError as e:
        # Không để lỗi bind cổng làm crash cả app - bot Telegram vẫn chạy bình thường qua polling.
        logger.warning("Không mở được web server ở cổng %s: %s", PORT, e)


# ============================================================
# CỘNG THƯỞNG REF KHI USER XÁC MINH THÀNH CÔNG LẦN ĐẦU
# (gắn thêm logic vào is_verified qua wrapper)
# ============================================================

_original_is_verified = is_verified


async def is_verified(context, user_id):  # noqa: F811 (override có chủ đích)
    channel_id = cfg("channel_id", "")
    if not channel_id:
        return True
    user = get_user(user_id)
    if user and user["verified"]:
        return True
    try:
        member = await context.bot.get_chat_member(channel_id, user_id)
        ok = member.status in ("member", "administrator", "creator")
        if ok:
            conn = get_conn()
            conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()
            # cộng thưởng cho người giới thiệu (nếu có, chỉ 1 lần)
            if user and user["ref_by"]:
                bonus = int(cfg("ref_bonus", 1000))
                add_balance(user["ref_by"], bonus, 0, "ref", "ref")
                conn = get_conn()
                conn.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?", (user["ref_by"],))
                conn.commit()
                conn.close()
                try:
                    await context.bot.send_message(
                        user["ref_by"],
                        f"🎉 Bạn vừa được +{money_fmt(bonus)} vì có người dùng link giới thiệu của bạn!",
                    )
                except Exception:
                    pass
        return ok
    except Exception:
        return False


# ============================================================
# MAIN
# ============================================================

async def cmd_setweburl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Cú pháp: /setweburl <https://ten-app.onrender.com>")
        return
    set_cfg("web_base_url", context.args[0].rstrip("/"))
    await update.message.reply_text("✅ Đã cập nhật địa chỉ web xác nhận nhiệm vụ.")


def main():
    global BOT_USERNAME, MAIN_LOOP, BOT_INSTANCE

    init_db()

    # Nếu deploy trên Render dạng Web Service, biến RENDER_EXTERNAL_URL được
    # Render tự cấp - dùng luôn làm web_base_url nếu admin chưa tự đặt.
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url and not cfg("web_base_url"):
        set_cfg("web_base_url", render_url.rstrip("/"))

    # Một số bản Python mới (3.12+) không còn tự tạo event loop mặc định ở
    # main thread nữa, khiến python-telegram-bot báo lỗi "no current event
    # loop". Tạo và gán loop thủ công trước khi build app để tránh lỗi này.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("setlink4m", cmd_setlink4m))
    app.add_handler(CommandHandler("setreward", cmd_setreward))
    app.add_handler(CommandHandler("setrefbonus", cmd_setrefbonus))
    app.add_handler(CommandHandler("setminwd", cmd_setminwd))
    app.add_handler(CommandHandler("setweburl", cmd_setweburl))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # lấy username bot + lưu instance bot + event loop hiện tại để thread Flask dùng được
    BOT_INSTANCE = app.bot
    MAIN_LOOP = asyncio.get_event_loop()

    async def _fetch_username():
        global BOT_USERNAME
        me = await app.bot.get_me()
        BOT_USERNAME = me.username

    MAIN_LOOP.run_until_complete(_fetch_username())

    threading.Thread(target=run_web_server, daemon=True).start()

    logger.info("Bot đang khởi động... web_base_url=%s", cfg("web_base_url"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
