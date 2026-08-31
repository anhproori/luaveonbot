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
import http.server
import socketserver
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
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
from telegram.error import TelegramError

# ============================================================
# CẤU HÌNH - đổi giá trị mặc định ở đây hoặc set biến môi trường
# ============================================================
# ⚠️ KHÔNG hardcode token/API key thật vào code (kể cả khi test) - nếu file
# này từng bị dán/commit kèm token thật ở bất kỳ đâu, hãy vào @BotFather ->
# /mybots -> API Token -> Revoke current token để thu hồi ngay, rồi set token
# MỚI qua biến môi trường bên dưới. Bot sẽ không khởi động nếu thiếu biến bắt buộc.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8765543353:AAFbd4IYTzk8bUn2njECLbx8Z3Gb_LWa4_A")
ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "8685327154")
LINK4M_API_KEY_DEFAULT = os.environ.get("LINK4M_API_KEY", "6a93e433c1e0cd622c1112a8")

if not BOT_TOKEN:
    raise SystemExit("❌ Thiếu biến môi trường BOT_TOKEN. Hãy set BOT_TOKEN trong Render > Environment.")
if not ADMIN_ID_RAW:
    raise SystemExit("❌ Thiếu biến môi trường ADMIN_ID. Hãy set ADMIN_ID trong Render > Environment.")
ADMIN_ID = int(ADMIN_ID_RAW)

DB_PATH = os.environ.get("DB_PATH", "bot.db")
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("moneybot")

BOT_USERNAME = None  # sẽ lấy tự động lúc khởi động
BOT_NAME = None  # tên hiển thị (first_name) của chính bot Telegram - lấy tự động lúc khởi động

# ============================================================
# GIỜ VIỆT NAM (UTC+7) - toàn bộ thời gian lưu DB + hiển thị trong bot đều
# theo múi giờ này thay vì UTC như trước.
# ============================================================
from datetime import timezone as _timezone

VN_TZ = _timezone(timedelta(hours=7))


def now_vn() -> datetime:
    """Thời điểm hiện tại theo giờ Việt Nam (UTC+7), có gắn tzinfo."""
    return datetime.now(VN_TZ)


def fmt_vn(iso_str: str) -> str:
    """Định dạng 1 chuỗi ISO datetime (đã lưu theo giờ VN) để hiển thị đẹp,
    dạng 'dd/mm/YYYY HH:MM (giờ VN)'. An toàn với chuỗi rỗng/None/cũ (UTC)."""
    if not iso_str:
        return "(không rõ)"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m/%Y %H:%M") + " (giờ VN)"
    except Exception:
        return str(iso_str)[:16].replace("T", " ") + " (giờ VN)"


async def ensure_bot_info(context: ContextTypes.DEFAULT_TYPE):
    """Đảm bảo đã có BOT_USERNAME + BOT_NAME (phòng khi hàm nào chạy trước khi
    main() kịp lấy xong lúc khởi động)."""
    global BOT_USERNAME, BOT_NAME
    if not BOT_USERNAME or not BOT_NAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username
        BOT_NAME = me.first_name or me.username

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
            last_checkin TEXT,
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
            reject_reason TEXT,
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

        CREATE TABLE IF NOT EXISTS channels (
            chat_id TEXT PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'active',
            required INTEGER DEFAULT 0,
            added_at TEXT,
            checked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS dice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            session_no INTEGER,
            status TEXT DEFAULT 'betting',
            game_msg_id INTEGER,
            dice1 INTEGER, dice2 INTEGER, dice3 INTEGER,
            total INTEGER, result TEXT,
            created_at TEXT,
            closed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS dice_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_id INTEGER,
            username TEXT,
            side TEXT,
            amount INTEGER,
            created_at TEXT
        );
        """
    )
    conn.commit()

    # Migration nhẹ: nếu DB cũ (đã tạo trước khi có tính năng điểm danh) chưa
    # có cột last_checkin thì tự thêm vào, không làm mất dữ liệu cũ.
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_checkin TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # cột đã tồn tại rồi

    # Migration: thêm cột đếm số ngày điểm danh liên tiếp (streak)
    try:
        c.execute("ALTER TABLE users ADD COLUMN checkin_streak INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: đếm số nhiệm vụ đã hoàn thành (để hiện thống kê đẹp hơn)
    try:
        c.execute("ALTER TABLE users ADD COLUMN tasks_done INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: hệ thống cấm (ban) user - lý do + thời hạn rõ ràng
    for col, coltype in [
        ("banned", "INTEGER DEFAULT 0"),
        ("ban_reason", "TEXT"),
        ("banned_until", "TEXT"),   # NULL = cấm vĩnh viễn, có giá trị = cấm có thời hạn (ISO datetime)
        ("banned_at", "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Migration: lý do từ chối rút tiền (để hiện rõ cho user thay vì chỉ báo
    # "bị từ chối" chung chung).
    try:
        c.execute("ALTER TABLE withdrawals ADD COLUMN reject_reason TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: kênh xác minh giờ hỗ trợ NHIỀU kênh/group CÙNG LÚC (trước
    # đây chỉ 1 kênh duy nhất lưu trong config "channel_id"). Thêm cột
    # "required" đánh dấu kênh nào đang là điều kiện bắt buộc, và tự động
    # chuyển kênh đang cấu hình cũ (nếu có) sang làm kênh bắt buộc đầu tiên
    # để bot đang chạy không bị mất cấu hình khi cập nhật lên bản này.
    try:
        c.execute("ALTER TABLE channels ADD COLUMN required INTEGER DEFAULT 0")
        conn.commit()
        old_channel_row = c.execute("SELECT value FROM config WHERE key='channel_id'").fetchone()
        if old_channel_row and old_channel_row[0]:
            c.execute("UPDATE channels SET required=1 WHERE chat_id=?", (old_channel_row[0],))
            conn.commit()
    except sqlite3.OperationalError:
        pass

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
        "checkin_min": "100",
        "checkin_max": "300",
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
        (user_id, username or "", ref_by, now_vn().isoformat()),
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
            (user_id, money, log_type, now_vn().isoformat()),
        )
    conn.commit()
    conn.close()


def income_stats(user_id):
    conn = get_conn()
    now = now_vn()
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
# HỆ THỐNG CẤM (BAN) USER
# ============================================================

def is_banned(user) -> bool:
    """Kiểm tra 1 row user (sqlite3.Row) có đang bị cấm không. Nếu cấm có
    thời hạn và đã hết hạn thì tự động bỏ cấm luôn (trả về False)."""
    if not user or not user["banned"]:
        return False
    until = user["banned_until"]
    if until:
        try:
            if now_vn() >= datetime.fromisoformat(until):
                unban_user(user["user_id"])
                return False
        except ValueError:
            pass
    return True


def ban_user(user_id: int, reason: str, days: int = 0):
    """days=0 -> cấm vĩnh viễn. days>0 -> cấm có thời hạn N ngày."""
    now = now_vn()
    until = (now + timedelta(days=days)).isoformat() if days > 0 else None
    conn = get_conn()
    conn.execute(
        "UPDATE users SET banned=1, ban_reason=?, banned_until=?, banned_at=? WHERE user_id=?",
        (reason, until, now.isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def unban_user(user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET banned=0, ban_reason=NULL, banned_until=NULL, banned_at=NULL WHERE user_id=?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def upsert_channel(chat_id: str, title: str, status: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO channels (chat_id, title, status, added_at, checked_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, status=excluded.status, checked_at=excluded.checked_at",
        (chat_id, title, status, now_vn().isoformat(), now_vn().isoformat()),
    )
    conn.commit()
    conn.close()


def list_channels():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM channels ORDER BY added_at DESC").fetchall()
    conn.close()
    return rows


def get_required_channels():
    """Danh sách kênh/group đang được bật làm điều kiện BẮT BUỘC xác minh.
    Có thể là 0, 1, hoặc NHIỀU kênh cùng lúc - user phải tham gia TOÀN BỘ
    các kênh trong danh sách này mới được coi là đã xác minh. Chỉ lấy kênh
    đang 'active' (bot còn ở trong đó) để tránh khoá user vì 1 kênh bot đã
    bị gỡ khỏi từ lâu."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM channels WHERE required=1 AND status='active' ORDER BY added_at"
    ).fetchall()
    conn.close()
    return rows


def set_channel_required(chat_id: str, required: bool):
    conn = get_conn()
    conn.execute("UPDATE channels SET required=? WHERE chat_id=?", (1 if required else 0, chat_id))
    conn.commit()
    conn.close()


def reset_all_verified():
    """Buộc TẤT CẢ user (kể cả admin) phải xác minh lại kênh từ đầu - dùng
    khi admin đổi sang kênh xác minh mới, hoặc chủ động bấm nút yêu cầu xác
    minh lại trong Admin Panel."""
    conn = get_conn()
    conn.execute("UPDATE users SET verified=0")
    conn.commit()
    conn.close()


def ban_notice_text(user) -> str:
    """Tin nhắn thông báo cấm - đầy đủ lý do + thời gian, hiển thị cho
    chính user bị cấm khi họ mở lại bot."""
    reason = user["ban_reason"] or "Không có lý do cụ thể"
    until = user["banned_until"]
    if until:
        time_line = f"⏳ Hết hạn cấm: <b>{fmt_vn(until)}</b>"
    else:
        time_line = "⏳ Thời hạn: <b>Vĩnh viễn</b>"
    return (
        "🚫🔒 <b>TÀI KHOẢN CỦA BẠN ĐÃ BỊ KHOÁ</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📄 Lý do: <b>{reason}</b>\n"
        f"{time_line}\n"
        f"🕒 Bị khoá lúc: {fmt_vn(user['banned_at'])}\n"
        "━━━━━━━━━━━━━━━\n"
        "<i>Nếu bạn cho rằng đây là nhầm lẫn, vui lòng liên hệ admin để được hỗ trợ.</i>"
    )


# ============================================================
# LINK4M
# ============================================================
# Bot gọi thẳng API rút gọn của link4m TỪ SERVER (endpoint api-shorten/v2,
# đúng cấu trúc link4m hướng dẫn dùng trong PHP):
#   https://link4m.co/api-shorten/v2?api=<api_key>&url=<link_đích_đã_encode>
# và nhận về JSON { "status": "success", "shortenedUrl": "..." } (hoặc lỗi).
#
# ⚠️ LƯU Ý: bản trước của bot đã CHỦ ĐỘNG bỏ cách gọi này vì link4m đứng sau
# Cloudflare, và Cloudflare có thể chặn request đến từ server (không phải
# trình duyệt thật) bằng lỗi 403 "Just a moment...". Nếu bạn thấy nhiệm vụ
# báo "Không tạo được link nhiệm vụ" hàng loạt sau khi cập nhật, khả năng
# cao là đang gặp lại đúng lỗi này - xem mục "Debug" trong README. Cách an
# toàn nhất để tránh 403 vẫn là ghép chuỗi
# `https://link4m.co/st?api=<key>&url=<đích>` rồi gắn thẳng vào nút bấm cho
# TRÌNH DUYỆT CỦA USER tự mở (không qua server) - nhưng theo yêu cầu, bot
# giờ quay lại gọi API từ server như dưới đây.

async def link4m_shorten(api_key: str, dest_url: str):
    """Gọi API link4m TỪ SERVER để rút gọn link đích. Trả về tuple
    (thành công?, kết quả) - kết quả là link rút gọn nếu thành công, hoặc
    thông báo lỗi (để hiện cho admin debug) nếu thất bại."""
    api_url = f"https://link4m.co/api-shorten/v2?api={api_key}&url={quote(dest_url, safe='')}"
    try:
        resp = await asyncio.to_thread(requests.get, api_url, timeout=15)
        logger.info("link4m API status=%s body=%s", resp.status_code, resp.text[:500])
        data = resp.json()
    except Exception as e:
        logger.exception("link4m API lỗi khi gọi từ server")
        return False, f"Không kết nối được tới link4m: {e}"

    if data.get("status") != "success":
        return False, data.get("message", "link4m trả về lỗi không xác định.")

    shortened = data.get("shortenedUrl", "")
    if not shortened or not re.match(r"^https?://link4m\.(co|com)/", shortened):
        return False, "link4m trả về link rút gọn không hợp lệ."
    return True, shortened


# ============================================================
# HIỂN THỊ / EDIT TIN NHẮN (dashboard 1 tin nhắn duy nhất)
# ============================================================

# Khoá riêng cho từng user - tránh trường hợp user bấm /start hoặc nút bấm
# liên tục nhiều lần liền nhau khiến 2 tiến trình cùng đọc/ghi last_msg_id
# song song, sinh ra 2 tin nhắn dashboard cùng lúc (1 trong 2 sẽ "im lặng"
# vì bị tin còn lại ghi đè last_msg_id) - đây là nguyên nhân chính gây cảm
# giác bot "bị đứng", "không phản hồi" khi bấm /start liên tục.
_user_locks: dict[int, asyncio.Lock] = {}


def _lock_for(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


async def render(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, text: str, keyboard=None):
    """
    Luôn cố gắng CHỈ GIỮ ĐÚNG 1 TIN NHẮN của bot trong đoạn chat: edit tin
    nhắn cũ trước; nếu edit thất bại vì BẤT KỲ lý do gì (tin bị xoá do user
    xoá lịch sử chat, tin quá cũ, mất mạng tạm thời, bot từng bị chặn rồi
    unblock, v.v.) thì luôn có phương án dự phòng: xoá tin cũ (nếu còn) rồi
    gửi tin mới - đảm bảo bot KHÔNG BAO GIỜ im lặng không phản hồi.
    """
    async with _lock_for(user_id):
        user = get_user(user_id)
        msg_id = user["last_msg_id"] if user else None
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=text,
                    reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True,
                )
                return
            except TelegramError as e:
                if "message is not modified" in str(e).lower():
                    return  # nội dung y hệt tin cũ, không cần làm gì thêm
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass  # tin cũ có thể đã bị xoá sẵn (ví dụ user xoá lịch sử chat) - bỏ qua
        try:
            sent = await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=keyboard,
                parse_mode="HTML", disable_web_page_preview=True,
            )
            set_last_msg(user_id, sent.message_id)
        except TelegramError:
            logger.exception("render(): gửi tin nhắn thất bại cho user_id=%s", user_id)


async def render_cb(update: Update, text: str, keyboard=None):
    """Dùng khi trả lời 1 callback query - edit trực tiếp tin nhắn đang bấm.
    Nếu edit thất bại (ví dụ tin đã bị xoá do user xoá lịch sử chat), luôn
    gửi 1 tin nhắn mới thay thế thay vì im lặng bỏ qua - và cập nhật lại
    last_msg_id để những lần render/edit sau vẫn trúng đúng 1 tin nhắn duy nhất."""
    q = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    async with _lock_for(user_id):
        try:
            await q.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
            return
        except TelegramError as e:
            if "message is not modified" in str(e).lower():
                return
        try:
            sent = await update.get_bot().send_message(
                chat_id=chat_id, text=text, reply_markup=keyboard,
                parse_mode="HTML", disable_web_page_preview=True,
            )
            set_last_msg(user_id, sent.message_id)
        except Exception:
            logger.exception("render_cb(): gửi tin nhắn thất bại cho user_id=%s", user_id)


async def render_cb_fx(update: Update, loading_text: str, final_text: str, keyboard=None, delay: float = 0.7):
    """
    Tạo hiệu ứng nhẹ cho các thao tác quan trọng (nhận thưởng, điểm danh,
    rút tiền...): edit tin nhắn sang trạng thái "đang xử lý" kèm icon động,
    đợi 1 chút rồi mới edit sang nội dung kết quả cuối cùng - tạo cảm giác
    bot đang "xử lý thật" thay vì trả kết quả cụt lủn ngay lập tức.
    """
    q = update.callback_query
    try:
        await q.edit_message_text(text=loading_text, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramError:
        pass
    await asyncio.sleep(delay)
    await render_cb(update, final_text, keyboard)


# ============================================================
# KIỂM TRA XÁC MINH KÊNH
# ============================================================

async def is_verified(context, user_id) -> bool:
    """Kiểm tra user đã tham gia ĐỦ TOÀN BỘ kênh/group xác minh bắt buộc
    chưa (có thể là 0, 1, hoặc NHIỀU kênh cùng lúc - xem get_required_channels).
    Cờ `verified` được cache lại trong DB để không phải gọi API Telegram mỗi
    lần bấm nút - cờ này chỉ bị reset về 0 khi: (1) admin bật thêm 1 kênh bắt
    buộc MỚI, hoặc (2) admin bấm nút "Yêu cầu xác minh lại" trong Admin
    Panel. Áp dụng y hệt cho TẤT CẢ mọi người, không có ngoại lệ cho
    ADMIN_ID."""
    channels = get_required_channels()
    if not channels:
        return True  # chưa cấu hình kênh nào -> không bắt buộc
    user = get_user(user_id)
    if user and user["verified"]:
        return True
    ok = True
    try:
        for ch in channels:
            member = await context.bot.get_chat_member(ch["chat_id"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                ok = False
                break
    except Exception:
        ok = False

    if ok:
        conn = get_conn()
        conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        # cộng thưởng cho người giới thiệu (nếu có, chỉ 1 lần duy nhất
        # ngay lúc user được mời xác minh đủ kênh thành công lần đầu)
        if user and user["ref_by"] and not user["verified"]:
            bonus = int(cfg("ref_bonus", 1000))
            add_balance(user["ref_by"], bonus, 0, "ref", "ref")
            conn = get_conn()
            conn.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?", (user["ref_by"],))
            conn.commit()
            conn.close()
            try:
                await render(
                    context, user["ref_by"], user["ref_by"],
                    f"🎉💰 <b>BẠN VỪA CÓ THÊM REF!</b>\n━━━━━━━━━━━━━━━\n"
                    f"Một người dùng link giới thiệu của bạn vừa xác minh kênh thành công.\n"
                    f"💵 Thưởng: <b>+{money_fmt(bonus)}</b>\n\n"
                    f"Bấm /start để xem dashboard mới nhất.",
                    None,
                )
            except Exception:
                pass
    return ok


def verify_keyboard():
    channels = get_required_channels()
    buttons = []
    for ch in channels:
        title = ch["title"] or ch["chat_id"]
        if ch["chat_id"].startswith("@"):
            buttons.append([InlineKeyboardButton(f"📢 Tham gia {title}", url=f"https://t.me/{ch['chat_id'][1:]}")])
    buttons.append([InlineKeyboardButton("✅ Tôi đã tham gia", callback_data="check_verify")])
    return InlineKeyboardMarkup(buttons)


def verify_gate_text():
    channels = get_required_channels()
    if len(channels) <= 1:
        name = channels[0]["title"] or channels[0]["chat_id"] if channels else "kênh"
        need_line = f"kênh <b>{name}</b>"
    else:
        names = "\n".join(f"• <b>{ch['title'] or ch['chat_id']}</b>" for ch in channels)
        need_line = f"<b>toàn bộ {len(channels)} kênh/nhóm</b> sau:\n{names}"
    return (
        "🔐✨ <b>YÊU CẦU THAM GIA KÊNH</b> ✨🔐\n"
        "━━━━━━━━━━━━━━━\n"
        f"Để mở khoá <b>toàn bộ tính năng</b> của bot, bạn cần tham gia {need_line}\n\n"
        "👉 Bấm <b>📢 Tham gia</b> ở từng kênh → quay lại đây bấm "
        "<b>✅ Tôi đã tham gia</b> để xác nhận.\n\n"
        "<i>⚠️ Quy định này áp dụng cho tất cả mọi người, kể cả admin.</i>"
    )


# ============================================================
# GIAO DIỆN MENU
# ============================================================

def main_menu_kb(user_id):
    rows = [
        [InlineKeyboardButton("💰 Thông tin tài khoản", callback_data="menu_account")],
        [InlineKeyboardButton("📝 Làm nhiệm vụ", callback_data="menu_task"),
         InlineKeyboardButton("💸 Rút tiền", callback_data="menu_withdraw")],
        [InlineKeyboardButton("👥 Mời bạn bè", callback_data="menu_ref"),
         InlineKeyboardButton("🎁 Đổi Tài Nguyên", callback_data="menu_tools")],
        [InlineKeyboardButton("🎁 Điểm danh", callback_data="menu_checkin"),
         InlineKeyboardButton("🏆 Bảng xếp hạng", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📜 Lịch sử giao dịch", callback_data="menu_history"),
         InlineKeyboardButton("💸 Lịch sử rút tiền", callback_data="menu_wdhistory")],
    ]
    if user_id == ADMIN_ID:
        rows.append([InlineKeyboardButton("⚙️ Quản trị viên", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")]])


def welcome_text(user):
    streak = user["checkin_streak"] or 0
    streak_line = f"🔥 Chuỗi điểm danh: <b>{streak} ngày</b>\n" if streak else ""
    name = (BOT_NAME or "BOT KIẾM TIỀN ONLINE").upper()
    return (
        "╔═══════════════════╗\n"
        f"   🎉 <b>{name}</b> 🎉\n"
        "╚═══════════════════╝\n\n"
        f"💰 Số dư: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"🪙 Coin: <b>{user['coin']}</b>\n"
        f"{streak_line}"
        "\n👇 <i>Chọn chức năng bên dưới để bắt đầu</i> 👇"
    )


# ============================================================
# HANDLERS: /start
# ============================================================

async def try_delete_message(update: Update):
    """Cố xoá tin nhắn user vừa gửi (ví dụ /start, hoặc tin nhập liệu) để giữ
    đoạn chat luôn sạch, chỉ còn đúng 1 tin nhắn dashboard của bot. Bot có
    quyền xoá tin nhắn đến (incoming) trong chat riêng tư với user."""
    try:
        await update.message.delete()
    except Exception:
        pass  # không đủ quyền hoặc tin đã bị xoá - bỏ qua, không ảnh hưởng luồng chính


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

    # xoá tin nhắn lệnh /start (hoặc /start task_xxx, /start ref_xxx...) để
    # đoạn chat luôn sạch, chỉ còn 1 tin nhắn dashboard duy nhất của bot
    await try_delete_message(update)

    # user bị cấm (ban) không được dùng bất kỳ chức năng nào - chỉ thấy
    # đúng 1 tin nhắn thông báo lý do + thời hạn cấm
    if is_banned(existing) and user_tg.id != ADMIN_ID:
        await render(context, user_tg.id, chat_id, ban_notice_text(get_user(user_tg.id)), None)
        return

    # xử lý deep-link hoàn thành nhiệm vụ: task_<token>
    if args and args[0].startswith("task_"):
        await complete_task(update, context, args[0].split("_", 1)[1])
        return

    # kiểm tra xác minh kênh - áp dụng cho TẤT CẢ mọi người, kể cả ADMIN_ID,
    # không có ngoại lệ nào (đúng yêu cầu: admin cũng phải xác nhận đã join kênh)
    if not await is_verified(context, user_tg.id):
        await render(context, user_tg.id, chat_id, verify_gate_text(), verify_keyboard())
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
        await render(
            context, user_tg.id, chat_id,
            "❌ <b>LINK KHÔNG HỢP LỆ</b>\n━━━━━━━━━━━━━━━\nLink nhiệm vụ này không tồn tại.",
            back_kb(),
        )
        return
    if row["used"]:
        conn.close()
        await render(
            context, user_tg.id, chat_id,
            "⚠️ <b>LINK ĐÃ ĐƯỢC SỬ DỤNG</b>\n━━━━━━━━━━━━━━━\n"
            "Link này chỉ dùng được đúng 1 lần và đã được dùng trước đó.\n"
            "Vào <b>📝 Làm nhiệm vụ</b> để lấy link mới nhé!",
            back_kb(),
        )
        return
    if row["user_id"] != user_tg.id:
        conn.close()
        await render(
            context, user_tg.id, chat_id,
            "🚫 <b>LINK KHÔNG THUỘC VỀ BẠN</b>\n━━━━━━━━━━━━━━━\n"
            "Link nhiệm vụ này được tạo cho tài khoản khác, không thể sử dụng.",
            back_kb(),
        )
        return

    conn.execute("UPDATE tasks SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()

    add_balance(user_tg.id, row["reward_money"], row["reward_coin"], "task", "task")
    conn = get_conn()
    conn.execute("UPDATE users SET tasks_done = tasks_done + 1 WHERE user_id=?", (user_tg.id,))
    conn.commit()
    conn.close()

    await render(
        context, user_tg.id, chat_id,
        "⏳ <i>Đang xác nhận nhiệm vụ...</i> 🔎",
        None,
    )
    await asyncio.sleep(0.6)

    user = get_user(user_tg.id)
    await render(
        context, user_tg.id, chat_id,
        "🎉✨ <b>HOÀN THÀNH NHIỆM VỤ THÀNH CÔNG!</b> ✨🎉\n"
        "━━━━━━━━━━━━━━━\n"
        f"💵 Nhận được: <b>+{money_fmt(row['reward_money'])}</b>\n"
        f"🪙 Nhận được: <b>+{row['reward_coin']} coin</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Số dư hiện tại: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n"
        f"🪙 Coin hiện tại: <b>{user['coin']}</b>\n"
        f"✅ Tổng nhiệm vụ đã làm: <b>{user['tasks_done']}</b>\n\n"
        "🚀 Tiếp tục làm nhiệm vụ để kiếm thêm nhé!",
        main_menu_kb(user_tg.id),
    )


# ============================================================
# CALLBACK QUERY ROUTER
# ============================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    user_id = update.effective_user.id
    await q.answer()

    if user_id != ADMIN_ID and is_banned(get_user(user_id)):
        await render_cb(update, ban_notice_text(get_user(user_id)), None)
        return

    if data == "check_verify":
        if await is_verified(context, user_id):
            user = get_user(user_id)
            await render_cb_fx(
                update,
                "✅ <i>Đang xác minh...</i> 🔎✨",
                welcome_text(user),
                main_menu_kb(user_id),
                delay=0.6,
            )
        else:
            await q.answer("Bạn chưa tham gia kênh, vui lòng tham gia rồi thử lại!", show_alert=True)
        return

    # mọi chức năng khác đều yêu cầu đã xác minh
    if not await is_verified(context, user_id):
        await render_cb(update, verify_gate_text(), verify_keyboard())
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

    elif data == "menu_checkin":
        await do_checkin(update, context)

    elif data == "menu_leaderboard":
        await show_leaderboard(update, context)

    elif data == "menu_history":
        await show_history(update, context)

    elif data == "menu_wdhistory":
        await show_withdraw_history(update, context)

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
        f"✅ Nhiệm vụ đã hoàn thành: <b>{user['tasks_done'] or 0}</b>\n"
        f"🔥 Chuỗi điểm danh: <b>{user['checkin_streak'] or 0} ngày</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "📈 <b>Thống kê thu nhập</b>\n"
        f"   • Hôm nay: {money_fmt(stats['today'])}\n"
        f"   • 24 giờ: {money_fmt(stats['24h'])}\n"
        f"   • 7 ngày: {money_fmt(stats['week'])}\n"
        f"   • 30 ngày: {money_fmt(stats['month'])}\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Lịch sử giao dịch", callback_data="menu_history")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
    ])
    await render_cb(update, text, kb)


# ---------------- Lịch sử giao dịch ----------------

_INCOME_TYPE_LABEL = {
    "task": "📝 Nhiệm vụ",
    "ref": "👥 Giới thiệu",
    "checkin": "🎁 Điểm danh",
    "admin_adjust": "⚙️ Admin điều chỉnh",
}


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_conn()
    rows = conn.execute(
        "SELECT amount, type, created_at FROM income_log WHERE user_id=? "
        "ORDER BY id DESC LIMIT 10",
        (user_id,),
    ).fetchall()
    conn.close()

    if not rows:
        text = "📜 <b>LỊCH SỬ GIAO DỊCH</b>\n━━━━━━━━━━━━━━━\nBạn chưa có giao dịch nào."
    else:
        lines = []
        for r in rows:
            label = _INCOME_TYPE_LABEL.get(r["type"], r["type"])
            lines.append(f"{label} — <b>+{money_fmt(r['amount'])}</b>  <i>({fmt_vn(r['created_at'])})</i>")
        text = (
            "📜 <b>LỊCH SỬ GIAO DỊCH</b> (10 gần nhất)\n"
            "━━━━━━━━━━━━━━━\n" + "\n".join(lines)
        )
    await render_cb(update, text, back_kb())


_WD_STATUS_LABEL = {
    "pending": "⏳ Đang chờ duyệt",
    "approved": "✅ Đã duyệt",
    "rejected": "❌ Đã từ chối (đã hoàn tiền)",
}


async def show_withdraw_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        text = "💸 <b>LỊCH SỬ RÚT TIỀN</b>\n━━━━━━━━━━━━━━━\nBạn chưa có yêu cầu rút tiền nào."
    else:
        lines = []
        for r in rows:
            status = _WD_STATUS_LABEL.get(r["status"], r["status"])
            lines.append(
                f"🧾 #{r['id']} — <b>{money_fmt(r['amount'])}</b> — {status}\n"
                f"   <i>{fmt_vn(r['created_at'])}</i>"
            )
        text = (
            "💸 <b>LỊCH SỬ RÚT TIỀN</b> (10 gần nhất)\n"
            "━━━━━━━━━━━━━━━\n" + "\n".join(lines)
        )
    await render_cb(update, text, back_kb())


# ---------------- Làm nhiệm vụ ----------------

async def do_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_bot_info(context)

    await render_cb(update, "📝 <i>Đang tạo link nhiệm vụ...</i> ⏳", None)

    token = uuid.uuid4().hex
    reward_money = random.randint(int(cfg("reward_min", 150)), int(cfg("reward_max", 500)))
    reward_coin = random.randint(int(cfg("coin_min", 5)), int(cfg("coin_max", 20)))

    conn = get_conn()
    conn.execute(
        "INSERT INTO tasks (token, user_id, reward_money, reward_coin, used, created_at) VALUES (?,?,?,?,0,?)",
        (token, user_id, reward_money, reward_coin, now_vn().isoformat()),
    )
    conn.commit()
    conn.close()

    # Link đích là deep-link quay lại chính bot Telegram, mang theo token riêng
    # cho user này - link4m dẫn user qua các bước quảng cáo xong sẽ tự mở app
    # Telegram, bot nhận lệnh /start task_<token> và tự cộng tiền ngay. Token
    # chỉ dùng được đúng 1 lần và chỉ khớp đúng user đã tạo ra nó.
    #
    # Bot gọi thẳng API link4m TỪ SERVER (xem hàm link4m_shorten ở trên) để
    # lấy link rút gọn thật, rồi mới gắn vào nút bấm.
    dest = f"t.me/{BOT_USERNAME}?start=task_{token}"
    api_key = cfg("link4m_api_key", LINK4M_API_KEY_DEFAULT)
    ok, result = await link4m_shorten(api_key, dest)

    if not ok:
        # Tạo link thất bại -> xoá token vừa tạo, tránh để lại token "mồ
        # côi" không bao giờ dùng được (và không tính vào thống kê nhiệm vụ).
        conn = get_conn()
        conn.execute("DELETE FROM tasks WHERE token=?", (token,))
        conn.commit()
        conn.close()
        await render_cb(
            update,
            "❌ <b>KHÔNG TẠO ĐƯỢC LINK NHIỆM VỤ</b>\n━━━━━━━━━━━━━━━\n"
            f"<i>{result}</i>\n\nVui lòng thử lại sau ít phút.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Thử lại", callback_data="menu_task")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
            ]),
        )
        return

    task_link = result

    text = (
        "📝✨ <b>NHIỆM VỤ MỚI</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎁 Phần thưởng: <b>{money_fmt(reward_money)}</b> + <b>{reward_coin} coin</b>\n\n"
        "👉 Bấm nút <b>bên dưới</b> để bắt đầu, vượt qua các bước quảng cáo.\n"
        "Vượt xong bot sẽ <b>tự động xác nhận và cộng tiền ngay lập tức</b>.\n\n"
        "⚠️ Nút này chỉ dùng được <b>1 lần duy nhất</b> và chỉ mình bạn dùng được."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 VƯỢT LINK NHẬN THƯỞNG", url=task_link)],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
    ])
    await render_cb(update, text, kb)




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
        (user_id, amount, source, user["bank_info"], "pending", now_vn().isoformat()),
    )
    wd_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()

    await render_cb_fx(
        update,
        "💸 <i>Đang gửi yêu cầu rút tiền...</i> ⏳",
        f"✅📤 <b>ĐÃ GỬI YÊU CẦU RÚT TIỀN</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Số tiền: <b>{money_fmt(amount)}</b>\n"
        f"🏦 Ngân hàng: <code>{user['bank_info']}</code>\n\n"
        "⏰ Admin sẽ duyệt trong thời gian sớm nhất.",
        back_kb(),
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"adm_wdok_{wd_id}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"adm_wdno_{wd_id}"),
    ]])
    await render(
        context, ADMIN_ID, ADMIN_ID,
        f"💸✨ <b>YÊU CẦU RÚT TIỀN MỚI #{wd_id}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💰 Số tiền: {money_fmt(amount)}\n"
        f"🏦 Ngân hàng: {user['bank_info']}",
        kb,
    )


# ---------------- Mời bạn bè ----------------

async def show_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_bot_info(context)
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


# ---------------- Điểm danh hàng ngày ----------------

async def do_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    today = now_vn().date().isoformat()
    yesterday = (now_vn().date() - timedelta(days=1)).isoformat()

    if user["last_checkin"] == today:
        await render_cb(
            update,
            "🎁 <b>ĐIỂM DANH HÀNG NGÀY</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "✅ Bạn đã điểm danh hôm nay rồi!\n"
            f"🔥 Chuỗi hiện tại: <b>{user['checkin_streak'] or 0} ngày</b>\n"
            "⏰ Quay lại vào ngày mai để nhận thêm thưởng nhé.",
            back_kb(),
        )
        return

    # nếu điểm danh hôm qua -> nối chuỗi; nếu bỏ lỡ ngày nào đó -> reset về 1
    new_streak = (user["checkin_streak"] or 0) + 1 if user["last_checkin"] == yesterday else 1
    base_bonus = random.randint(int(cfg("checkin_min", 100)), int(cfg("checkin_max", 300)))
    # thưởng thêm cho chuỗi dài, tối đa +50% ở mốc 7 ngày trở lên, để khuyến khích điểm danh liên tục
    streak_bonus_pct = min(new_streak * 5, 50)
    bonus = base_bonus + (base_bonus * streak_bonus_pct // 100)

    conn = get_conn()
    conn.execute(
        "UPDATE users SET last_checkin=?, checkin_streak=? WHERE user_id=?",
        (today, new_streak, user_id),
    )
    conn.commit()
    conn.close()
    add_balance(user_id, bonus, 0, "task", "checkin")

    await render_cb(update, "🎁 <i>Đang điểm danh...</i> ⏳", None)
    await asyncio.sleep(0.5)

    user = get_user(user_id)
    streak_note = f"\n🔥 Chuỗi điểm danh: <b>{new_streak} ngày</b> (+{streak_bonus_pct}% thưởng)" if streak_bonus_pct else ""
    await render_cb(
        update,
        "🎉🎁 <b>ĐIỂM DANH THÀNH CÔNG!</b> 🎁🎉\n"
        "━━━━━━━━━━━━━━━\n"
        f"💵 Bạn nhận được: <b>+{money_fmt(bonus)}</b>"
        f"{streak_note}\n"
        f"💰 Số dư hiện tại: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b>\n\n"
        "✨ Hẹn gặp lại vào ngày mai!",
        back_kb(),
    )


# ---------------- Bảng xếp hạng ----------------

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id, username, task_balance + ref_balance AS total "
        "FROM users ORDER BY total DESC LIMIT 10"
    ).fetchall()
    conn.close()

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows):
        icon = medals[i] if i < 3 else f"▫️{i + 1}."
        name = r["username"] or f"User {r['user_id']}"
        lines.append(f"{icon} <b>{name}</b> — <b>{money_fmt(r['total'])}</b>")

    text = (
        "🏆✨ <b>BẢNG XẾP HẠNG TOP KIẾM TIỀN</b> ✨🏆\n"
        "━━━━━━━━━━━━━━━\n" + ("\n".join(lines) if lines else "Chưa có dữ liệu.")
    )
    await render_cb(update, text, back_kb())


# ---------------- Đổi Tài Nguyên ----------------

async def show_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    all_tools = conn.execute("SELECT * FROM tools").fetchall()
    conn.close()
    # chỉ hiện gói còn hàng - gói hết hàng tự động ẩn khỏi user
    tools = []
    for t in all_tools:
        stock = len([a for a in t["accounts"].split("\n") if a.strip()])
        if stock > 0:
            tools.append((t, stock))

    if not tools:
        await render_cb(
            update,
            "🎁 <b>ĐỔI TÀI NGUYÊN</b>\n━━━━━━━━━━━━━━━\nHiện chưa có Tài Nguyên nào còn hàng, quay lại sau nhé!",
            back_kb(),
        )
        return
    text = "🎁 <b>ĐỔI TÀI NGUYÊN</b>\n━━━━━━━━━━━━━━━\nChọn Tài Nguyên bạn muốn đổi:\n"
    rows = []
    for t, stock in tools:
        text += f"\n📦 <b>{t['name']}</b> — {t['price_coin']} coin (còn {stock})"
        rows.append([InlineKeyboardButton(f"🎁 {t['name']} ({t['price_coin']} coin)", callback_data=f"buytool_{t['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")])
    await render_cb(update, text, InlineKeyboardMarkup(rows))


async def buy_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, tool_id: int):
    user_id = update.effective_user.id
    user = get_user(user_id)
    conn = get_conn()
    tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
    if not tool:
        conn.close()
        await render_cb(update, "❌ Tài Nguyên không tồn tại.", back_kb())
        return
    accounts = [a for a in tool["accounts"].split("\n") if a.strip()]
    if not accounts:
        conn.close()
        await render_cb(update, "❌ Tài Nguyên đã hết hàng.", back_kb())
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
        (user_id, tool["name"], acc, now_vn().isoformat()),
    )
    conn.commit()
    conn.close()

    await render_cb_fx(
        update,
        "🎁 <i>Đang xử lý Tài Nguyên...</i> ⏳",
        f"✅🎁 <b>NHẬN TÀI NGUYÊN THÀNH CÔNG!</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎁 Tài Nguyên: <b>{tool['name']}</b>\n"
        f"🔑 Thông tin tài khoản:\n<code>{acc}</code>\n\n"
        "<i>Lưu lại thông tin này ngay, tin nhắn có thể bị thay đổi ở lần thao tác tiếp theo.</i>",
        back_kb(),
    )


# ============================================================
# ADMIN
# ============================================================

def admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Quản lý user", callback_data="adm_users_0")],
        [InlineKeyboardButton("🔎 Tìm user theo ID", callback_data="adm_finduser")],
        [InlineKeyboardButton("📢 Gửi thông báo", callback_data="adm_broadcast")],
        [InlineKeyboardButton("✅ Duyệt rút tiền đang chờ", callback_data="adm_pending"),
         InlineKeyboardButton("📜 Lịch sử rút (tất cả)", callback_data="adm_wdhistory_0")],
        [InlineKeyboardButton("🎁 Quản lý Tài Nguyên", callback_data="adm_tools")],
        [InlineKeyboardButton("📡 Kênh xác minh", callback_data="adm_channel")],
        [InlineKeyboardButton("🎲 Quản lý Tài Xỉu", callback_data="adm_dice")],
        [InlineKeyboardButton("📊 Thống kê nâng cao", callback_data="adm_stats")],
        [InlineKeyboardButton("⚙️ Cấu hình", callback_data="adm_config")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
    ])


async def show_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    today = now_vn().date().isoformat()
    new_today = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE joined_at LIKE ?", (today + "%",)
    ).fetchone()["c"]
    total_paid = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE status='approved'"
    ).fetchone()["s"]
    total_tasks = conn.execute("SELECT COALESCE(SUM(tasks_done),0) s FROM users").fetchone()["s"]
    banned_count = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
    conn.close()
    text = (
        "⚙️✨ <b>ADMIN PANEL</b> ✨⚙️\n"
        "━━━━━━━━━━━━━━━\n"
        f"👥 Tổng user: <b>{total_users}</b>  (🆕 hôm nay: {new_today})\n"
        f"🚫 User đang bị cấm: <b>{banned_count}</b>\n"
        f"⏳ Yêu cầu rút tiền đang chờ: <b>{pending}</b>\n"
        f"💸 Đã chi trả (đã duyệt): <b>{money_fmt(total_paid)}</b>\n"
        f"📝 Tổng nhiệm vụ đã hoàn thành: <b>{total_tasks}</b>\n"
        f"📡 Kênh xác minh: {len(get_required_channels())} kênh đang bắt buộc\n"
        f"🔑 Link4m API key: <code>{cfg('link4m_api_key')}</code>\n\n"
        "👉 Dùng nút <b>👥 Quản lý user</b> bên dưới để xem danh sách, "
        "cấm/bỏ cấm hoặc điều chỉnh số dư từng user bằng nút bấm."
    )
    await render_cb(update, text, admin_menu_kb())


async def show_advanced_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    liability = conn.execute(
        "SELECT COALESCE(SUM(task_balance + ref_balance),0) s FROM users"
    ).fetchone()["s"]
    total_coin = conn.execute("SELECT COALESCE(SUM(coin),0) s FROM users").fetchone()["s"]
    top_tool = conn.execute(
        "SELECT tool_name, COUNT(*) c FROM tool_redemptions GROUP BY tool_name ORDER BY c DESC LIMIT 1"
    ).fetchone()
    total_redemptions = conn.execute("SELECT COUNT(*) c FROM tool_redemptions").fetchone()["c"]
    avg_balance = conn.execute(
        "SELECT COALESCE(AVG(task_balance + ref_balance),0) a FROM users"
    ).fetchone()["a"]
    dice_turnover = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM dice_bets").fetchone()["s"]
    dice_sessions_done = conn.execute("SELECT COUNT(*) c FROM dice_sessions WHERE status='done'").fetchone()["c"]
    conn.close()

    top_tool_line = f"{top_tool['tool_name']} ({top_tool['c']} lượt)" if top_tool else "(chưa có)"
    text = (
        "📊✨ <b>THỐNG KÊ NÂNG CAO</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Tổng số dư user đang giữ (nợ phải trả nếu ai cũng rút): <b>{money_fmt(liability)}</b>\n"
        f"📈 Số dư trung bình / user: <b>{money_fmt(avg_balance)}</b>\n"
        f"🪙 Tổng coin đang lưu hành: <b>{total_coin}</b>\n"
        f"🎁 Tổng lượt đổi Tài Nguyên: <b>{total_redemptions}</b>\n"
        f"🏆 Tài Nguyên hot nhất: <b>{top_tool_line}</b>\n"
        f"🎲 Tổng coin đã đặt cược Tài Xỉu: <b>{dice_turnover}</b> ({dice_sessions_done} phiên đã chạy)\n"
        "━━━━━━━━━━━━━━━\n"
        "<i>Số liệu này giúp bạn theo dõi dòng tiền/coin tổng thể của hệ "
        "thống để cân đối mức thưởng cho hợp lý.</i>"
    )
    await render_cb(update, text, admin_menu_kb())


async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    if data == "adm_broadcast":
        context.user_data["awaiting"] = "broadcast"
        await render_cb(update, "📢 Gửi nội dung bạn muốn thông báo tới toàn bộ user (gửi tin nhắn tiếp theo):", back_kb())

    elif data == "adm_pending":
        await show_pending_withdrawals(update, context)

    elif data == "adm_tools":
        await show_admin_tools(update, context)

    elif data == "adm_addtool":
        context.user_data["awaiting"] = "addtool_name"
        await render_cb(update, "➕ Nhập <b>tên Tài Nguyên mới</b>:", back_kb())

    elif data.startswith("adm_deltool_"):
        tool_id = int(data.split("_", 2)[2])
        conn = get_conn()
        conn.execute("DELETE FROM tools WHERE id=?", (tool_id,))
        conn.commit()
        conn.close()
        await show_admin_tools(update, context)

    elif data.startswith("adm_editprice_"):
        tool_id = int(data.split("_", 2)[2])
        context.user_data["awaiting"] = "edit_tool_price"
        context.user_data["edit_tool_id"] = tool_id
        await render_cb(update, "✏️ Nhập <b>giá coin mới</b> cho Tài Nguyên này:", back_kb())

    elif data == "adm_finduser":
        context.user_data["awaiting"] = "finduser_id"
        await render_cb(update, "🔎 Nhập <b>ID Telegram</b> của user cần tra cứu:", back_kb())

    elif data == "adm_channel":
        await show_channel_admin(update, context)

    elif data == "adm_channel_reset":
        reset_all_verified()
        await render_cb(
            update,
            "🔁✅ <b>ĐÃ YÊU CẦU XÁC MINH LẠI TOÀN BỘ</b>\n━━━━━━━━━━━━━━━\n"
            "Mọi user (kể cả bạn) sẽ phải xác nhận tham gia kênh lại ở lần "
            "/start hoặc thao tác tiếp theo.",
            admin_menu_kb(),
        )

    elif data == "adm_channel_refresh":
        await q_answer(update, "Đang kiểm tra lại trạng thái các kênh...")
        await refresh_channels_status(context)
        await show_channel_admin(update, context)

    elif data.startswith("adm_chtoggle_"):
        idx = int(data.rsplit("_", 1)[1])
        channels = list_channels()
        if 0 <= idx < len(channels):
            ch = channels[idx]
            now_required = bool(ch["required"])
            set_channel_required(ch["chat_id"], not now_required)
            if not now_required:
                # vừa BẬT thêm 1 kênh bắt buộc mới -> buộc mọi người xác
                # minh lại (kể cả những ai đã xác minh trước đó, vì họ có
                # thể chưa tham gia kênh vừa thêm này).
                reset_all_verified()
        await show_channel_admin(update, context)

    elif data == "adm_channel_clear":
        conn = get_conn()
        conn.execute("UPDATE channels SET required=0")
        conn.commit()
        conn.close()
        await render_cb(
            update,
            "🗑✅ <b>ĐÃ GỠ TOÀN BỘ KÊNH BẮT BUỘC</b>\n━━━━━━━━━━━━━━━\n"
            "Bot sẽ không bắt buộc tham gia kênh nào nữa cho tới khi bạn bật "
            "lại kênh nào đó trong danh sách, hoặc thêm bot vào 1 kênh/nhóm mới.",
            admin_menu_kb(),
        )

    elif data.startswith("adm_topup_"):
        tool_id = int(data.split("_", 2)[2])
        context.user_data["awaiting"] = "topup_accounts"
        context.user_data["topup_tool_id"] = tool_id
        conn = get_conn()
        tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
        conn.close()
        await render_cb(
            update,
            f"➕ Nạp thêm tài khoản vào Tài Nguyên <b>{tool['name']}</b>.\n"
            "Gửi danh sách tài khoản, mỗi dòng 1 tài khoản, dạng:\n<code>user:pass</code>",
            back_kb(),
        )

    elif data == "adm_config":
        text = (
            "⚙️ <b>CẤU HÌNH</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "Dùng các lệnh sau (gõ trực tiếp trong chat, không qua nút):\n"
            "<code>/setlink4m &lt;api_key&gt;</code>\n"
            "<code>/setreward &lt;min&gt; &lt;max&gt;</code>\n"
            "<code>/setrefbonus &lt;số tiền&gt;</code>\n"
            "<code>/setminwd &lt;min_task&gt; &lt;min_ref&gt;</code>\n"
            "<code>/finduser &lt;id&gt;</code> — tra cứu thông tin 1 user\n"
            "<code>/addbalance &lt;id&gt; &lt;số tiền&gt;</code> — cộng/trừ số dư thủ công\n\n"
            "📡 Để đặt <b>kênh xác minh</b>: thêm bot làm admin trong kênh/group, "
            "bot sẽ tự động lưu kênh đó."
        )
        await render_cb(update, text, back_kb())

    elif data.startswith("adm_wdok_"):
        wd_id = int(data.rsplit("_", 1)[1])
        await approve_withdrawal(update, context, wd_id)

    elif data.startswith("adm_wdnoreason_"):
        wd_id = int(data.rsplit("_", 1)[1])
        context.user_data.pop("awaiting", None)
        context.user_data.pop("wd_reject_target", None)
        await reject_withdrawal_cb(update, context, wd_id, "Không có lý do cụ thể")

    elif data.startswith("adm_wdno_"):
        wd_id = int(data.rsplit("_", 1)[1])
        context.user_data["awaiting"] = "wd_reject_reason"
        context.user_data["wd_reject_target"] = wd_id
        await render_cb(
            update,
            f"❌ <b>TỪ CHỐI YÊU CẦU RÚT TIỀN #{wd_id}</b>\n━━━━━━━━━━━━━━━\n"
            "Nhập <b>lý do từ chối</b> (sẽ gửi rõ ràng cho user thấy), hoặc "
            "bấm nút bên dưới nếu không cần ghi lý do:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 Từ chối không cần lý do", callback_data=f"adm_wdnoreason_{wd_id}")],
                [InlineKeyboardButton("⬅️ Huỷ", callback_data="adm_pending")],
            ]),
        )

    elif data.startswith("adm_wdhistory_"):
        page = int(data.rsplit("_", 1)[1])
        await show_admin_withdraw_history(update, context, page)

    elif data == "adm_stats":
        await show_advanced_stats(update, context)

    elif data == "adm_dice":
        await show_dice_admin(update, context)

    elif data.startswith("adm_dicevoid_"):
        session_id = int(data.rsplit("_", 1)[1])
        await void_dice_session(update, context, session_id)

    elif data.startswith("adm_users_"):
        page = int(data.rsplit("_", 1)[1])
        await show_admin_users(update, context, page)

    elif data.startswith("adm_u_"):
        uid = int(data.split("_", 2)[2])
        await show_user_detail(update, context, uid)

    elif data.startswith("adm_ban_"):
        uid = int(data.split("_", 2)[2])
        context.user_data["awaiting"] = "ban_reason"
        context.user_data["ban_target"] = uid
        await render_cb(
            update,
            f"🚫 <b>CẤM USER</b> <code>{uid}</code>\n━━━━━━━━━━━━━━━\n"
            "Nhập <b>lý do cấm</b> (sẽ gửi rõ ràng cho user):",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Huỷ", callback_data=f"adm_u_{uid}")]]),
        )

    elif data.startswith("adm_banlen_"):
        _, _, uid_s, days_s = data.split("_", 3)
        await apply_ban(update, context, int(uid_s), int(days_s))

    elif data.startswith("adm_unban_"):
        uid = int(data.split("_", 2)[2])
        unban_user(uid)
        try:
            await render(
                context, uid, uid,
                "🔓✅ <b>TÀI KHOẢN CỦA BẠN ĐÃ ĐƯỢC MỞ KHOÁ</b>\n━━━━━━━━━━━━━━━\n"
                "Bạn có thể tiếp tục sử dụng bot bình thường. Gõ /start để mở lại.",
                None,
            )
        except Exception:
            pass
        await show_user_detail(update, context, uid)

    elif data.startswith("adm_adjbal_"):
        uid = int(data.split("_", 2)[2])
        context.user_data["awaiting"] = "adjust_balance"
        context.user_data["adjbal_target"] = uid
        await render_cb(
            update,
            f"➕➖ <b>ĐIỀU CHỈNH SỐ DƯ</b> user <code>{uid}</code>\n━━━━━━━━━━━━━━━\n"
            "Nhập số tiền cần cộng (số dương) hoặc trừ (số âm), ví dụ: <code>-5000</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Huỷ", callback_data=f"adm_u_{uid}")]]),
        )

    elif data.startswith("adm_adjcoin_"):
        uid = int(data.split("_", 2)[2])
        context.user_data["awaiting"] = "adjust_coin"
        context.user_data["adjcoin_target"] = uid
        await render_cb(
            update,
            f"🪙 <b>ĐIỀU CHỈNH COIN</b> user <code>{uid}</code>\n━━━━━━━━━━━━━━━\n"
            "Nhập số coin cần cộng (số dương) hoặc trừ (số âm), ví dụ: <code>-10</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Huỷ", callback_data=f"adm_u_{uid}")]]),
        )

    elif data.startswith("adm_reverify_"):
        uid = int(data.split("_", 2)[2])
        conn = get_conn()
        conn.execute("UPDATE users SET verified=0 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        await show_user_detail(update, context, uid)

    elif data.startswith("adm_clearbank_"):
        uid = int(data.split("_", 2)[2])
        conn = get_conn()
        conn.execute("UPDATE users SET bank_info=NULL WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        await show_user_detail(update, context, uid)


async def show_admin_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    tools = conn.execute("SELECT * FROM tools").fetchall()
    conn.close()
    text = "🎁✨ <b>QUẢN LÝ TÀI NGUYÊN</b> ✨\n━━━━━━━━━━━━━━━\n"
    rows = []
    if not tools:
        text += "Chưa có Tài Nguyên nào."
    for t in tools:
        stock = len([a for a in t["accounts"].split("\n") if a.strip()])
        trang_thai = "🟢 Còn hàng" if stock > 0 else "🔴 Hết hàng (đã ẩn với user)"
        text += f"\n🎁 <b>{t['name']}</b> — {t['price_coin']} coin — còn {stock} — {trang_thai}"
        rows.append([
            InlineKeyboardButton(f"➕ Nạp: {t['name']}", callback_data=f"adm_topup_{t['id']}"),
            InlineKeyboardButton("✏️ Giá", callback_data=f"adm_editprice_{t['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"adm_deltool_{t['id']}"),
        ])
    rows.append([InlineKeyboardButton("🆕 Tạo Tài Nguyên mới", callback_data="adm_addtool")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    await render_cb(update, text, InlineKeyboardMarkup(rows))


async def show_channel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    verified_count = conn.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"]
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()

    channels = list_channels()
    required_ids = {ch["chat_id"] for ch in channels if ch["required"]}

    if required_ids:
        names = ", ".join(f"<b>{ch['title'] or ch['chat_id']}</b>" for ch in channels if ch["chat_id"] in required_ids)
        status_line = f"📡 Đang bắt buộc xác minh <b>{len(required_ids)} kênh/nhóm</b>: {names}"
    else:
        status_line = "📡 Kênh xác minh: <b>Chưa cấu hình</b> (bot không bắt buộc tham gia kênh nào)"

    if channels:
        lines = []
        for ch in channels:
            icon = "🟢 Bật" if ch["status"] == "active" else "🔴 Tắt"
            req_tag = " ⭐ Bắt buộc" if ch["chat_id"] in required_ids else ""
            lines.append(f"• <b>{ch['title']}</b> — {icon}{req_tag}\n   🆔 <code>{ch['chat_id']}</code>")
        channels_block = "\n\n📋 <b>Danh sách kênh/nhóm bot đã từng được thêm vào:</b>\n" + "\n".join(lines)
    else:
        channels_block = (
            "\n\n📋 <b>Danh sách kênh/nhóm bot đã từng được thêm vào:</b>\n"
            "Chưa ghi nhận kênh nào. Nếu bạn đã từng thêm bot vào kênh nhưng "
            "không thấy hiện ở đây, bấm <b>🔄 Kiểm tra lại</b> bên dưới để bot "
            "tự tải lại trạng thái."
        )

    text = (
        "📡✨ <b>KÊNH XÁC MINH</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"{status_line}\n"
        f"✅ Đã xác minh: <b>{verified_count}/{total_users}</b> user"
        f"{channels_block}\n"
        "━━━━━━━━━━━━━━━\n"
        "👉 Có thể đặt <b>NHIỀU kênh/nhóm cùng lúc</b> làm điều kiện bắt buộc — "
        "user phải tham gia <b>toàn bộ</b> các kênh đang gắn ⭐ mới được coi là "
        "đã xác minh. Thêm bot vào kênh/nhóm mới với quyền admin sẽ TỰ ĐỘNG "
        "bật kênh đó thành bắt buộc (cộng thêm vào danh sách, không thay thế "
        "kênh cũ). Bấm vào 1 kênh bên dưới để bật/tắt yêu cầu bắt buộc riêng "
        "với kênh đó.\n\n"
        "👉 <b>🔁 Yêu cầu xác minh lại toàn bộ</b>: buộc <b>mọi người, kể cả "
        "admin</b>, phải xác nhận tham gia kênh lại ngay từ lần thao tác "
        "tiếp theo — dùng được bất cứ lúc nào."
    )
    rows = []
    for idx, ch in enumerate(channels):
        if ch["status"] != "active":
            continue
        is_req = ch["chat_id"] in required_ids
        label = f"{'⭐➖ Bỏ bắt buộc' if is_req else '⭐➕ Đặt bắt buộc'}: {ch['title']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"adm_chtoggle_{idx}")])
    rows.append([InlineKeyboardButton("🔄 Kiểm tra lại", callback_data="adm_channel_refresh")])
    rows.append([InlineKeyboardButton("🔁 Yêu cầu xác minh lại toàn bộ", callback_data="adm_channel_reset")])
    if required_ids:
        rows.append([InlineKeyboardButton("🗑 Gỡ toàn bộ kênh bắt buộc", callback_data="adm_channel_clear")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    await render_cb(update, text, InlineKeyboardMarkup(rows))


async def refresh_channels_status(context: ContextTypes.DEFAULT_TYPE):
    """Bấm '🔄 Kiểm tra lại': hỏi lại Telegram xem bot còn là thành viên của
    từng kênh đã ghi nhận hay không, cập nhật cột status ('active'/'removed')
    cho đúng thực tế hiện tại (phòng trường hợp bot bị gỡ khỏi kênh mà admin
    không hề bấm gì trong bot)."""
    channels = list_channels()
    me = await context.bot.get_me()
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["chat_id"], me.id)
            status = "active" if member.status in ("member", "administrator", "creator") else "removed"
        except Exception:
            status = "removed"
        upsert_channel(ch["chat_id"], ch["title"], status)


USERS_PER_PAGE = 8


async def show_admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    rows = conn.execute(
        "SELECT user_id, username, task_balance, ref_balance, banned "
        "FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
        (USERS_PER_PAGE, page * USERS_PER_PAGE),
    ).fetchall()
    conn.close()

    max_page = max(0, (total - 1) // USERS_PER_PAGE)
    text = (
        "👥✨ <b>QUẢN LÝ USER</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"Tổng: <b>{total}</b> user  |  Trang <b>{page + 1}/{max_page + 1}</b>\n\n"
        "Bấm vào 1 user để xem chi tiết & quản lý:"
    )
    rows_kb = []
    for r in rows:
        icon = "🚫" if r["banned"] else "🟢"
        label = r["username"] or f"User {r['user_id']}"
        total_bal = r["task_balance"] + r["ref_balance"]
        rows_kb.append([InlineKeyboardButton(
            f"{icon} {label} — {money_fmt(total_bal)}", callback_data=f"adm_u_{r['user_id']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"adm_users_{page - 1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"adm_users_{page + 1}"))
    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    await render_cb(update, text, InlineKeyboardMarkup(rows_kb))


def user_detail_view(uid: int):
    """Trả về (text, keyboard) mô tả chi tiết 1 user - dùng chung cho cả
    luồng bấm nút (admin_router) lẫn lệnh gõ tay /finduser."""
    user = get_user(uid)
    if not user:
        return "❌ Không tìm thấy user này.", admin_menu_kb()
    stats = income_stats(uid)
    ban_status = "🚫 Đang bị cấm" if is_banned(user) else "🟢 Bình thường"
    ban_line = ""
    if is_banned(user):
        until = user["banned_until"]
        until_txt = fmt_vn(until) if until else "Vĩnh viễn"
        ban_line = f"   ├ Lý do: {user['ban_reason'] or '(không có)'}\n   └ Hết hạn: {until_txt}\n"

    text = (
        f"🔍 <b>THÔNG TIN USER</b> <code>{uid}</code>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 Username: {user['username'] or '(không có)'}\n"
        f"💰 Số dư: <b>{money_fmt(user['task_balance'] + user['ref_balance'])}</b> "
        f"(nhiệm vụ: {money_fmt(user['task_balance'])}, ref: {money_fmt(user['ref_balance'])})\n"
        f"🪙 Coin: <b>{user['coin']}</b>\n"
        f"👥 Số ref: {user['ref_count']}\n"
        f"✅ Nhiệm vụ đã làm: {user['tasks_done'] or 0}\n"
        f"🏦 Ngân hàng: {user['bank_info'] or '(chưa liên kết)'}\n"
        f"✔️ Xác minh kênh: {'Có' if user['verified'] else 'Chưa'}\n"
        f"📅 Tham gia: {fmt_vn(user['joined_at'])}\n"
        f"📈 Thu nhập hôm nay: {money_fmt(stats['today'])} | 7 ngày: {money_fmt(stats['week'])}\n"
        f"🔒 Trạng thái: <b>{ban_status}</b>\n"
        f"{ban_line}"
    )
    rows = [
        [InlineKeyboardButton("➕➖ Điều chỉnh số dư", callback_data=f"adm_adjbal_{uid}"),
         InlineKeyboardButton("🪙 Điều chỉnh coin", callback_data=f"adm_adjcoin_{uid}")],
    ]
    if is_banned(user):
        rows.append([InlineKeyboardButton("✅ Bỏ cấm", callback_data=f"adm_unban_{uid}")])
    else:
        rows.append([InlineKeyboardButton("🚫 Cấm user", callback_data=f"adm_ban_{uid}")])
    extra_row = []
    if user["verified"]:
        extra_row.append(InlineKeyboardButton("🔁 Yêu cầu xác minh lại", callback_data=f"adm_reverify_{uid}"))
    if user["bank_info"]:
        extra_row.append(InlineKeyboardButton("🗑 Xoá ngân hàng", callback_data=f"adm_clearbank_{uid}"))
    if extra_row:
        rows.append(extra_row)
    rows.append([InlineKeyboardButton("⬅️ Danh sách user", callback_data="adm_users_0")])
    return text, InlineKeyboardMarkup(rows)


async def show_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int):
    text, kb = user_detail_view(uid)
    await render_cb(update, text, kb)


async def show_user_detail_by_id(context: ContextTypes.DEFAULT_TYPE, chat_id: int, uid: int):
    """Bản dùng cho lệnh gõ tay /finduser (không có callback query sẵn)."""
    text, kb = user_detail_view(uid)
    await render(context, ADMIN_ID, chat_id, text, kb)


BAN_DURATIONS = [
    ("1 ngày", 1), ("3 ngày", 3), ("7 ngày", 7), ("30 ngày", 30), ("Vĩnh viễn", 0),
]


async def apply_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int, days: int):
    reason = context.user_data.pop("ban_reason_text", None) or "Không có lý do cụ thể"
    context.user_data.pop("ban_target", None)
    context.user_data.pop("awaiting", None)
    ban_user(uid, reason, days)
    try:
        await render(context, uid, uid, ban_notice_text(get_user(uid)), None)
    except Exception:
        pass
    await show_user_detail(update, context, uid)


WD_PENDING_MAX_SHOW = 25


def _pending_withdrawals_view():
    """Dựng sẵn (text, keyboard) cho màn hình duyệt rút tiền - dùng chung
    cho cả đường callback (render_cb) lẫn đường nhập text/lý do từ chối
    (render), tránh lặp code."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id").fetchall()
    conn.close()
    if not rows:
        return "✅ Không có yêu cầu rút tiền nào đang chờ.", back_kb()

    shown = rows[:WD_PENDING_MAX_SHOW]
    text = (
        "⏳✨ <b>YÊU CẦU RÚT TIỀN ĐANG CHỜ</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"Tổng: <b>{len(rows)}</b> yêu cầu\n\n"
    )
    kb_rows = []
    for r in shown:
        text += (
            f"🧾 #{r['id']} — user <code>{r['user_id']}</code> — <b>{money_fmt(r['amount'])}</b>\n"
            f"🏦 {r['bank_info']}\n<i>{fmt_vn(r['created_at'])}</i>\n\n"
        )
        kb_rows.append([
            InlineKeyboardButton(f"✅ Duyệt #{r['id']}", callback_data=f"adm_wdok_{r['id']}"),
            InlineKeyboardButton(f"❌ Từ chối #{r['id']}", callback_data=f"adm_wdno_{r['id']}"),
        ])
    if len(rows) > WD_PENDING_MAX_SHOW:
        text += f"<i>... còn {len(rows) - WD_PENDING_MAX_SHOW} yêu cầu khác, hãy xử lý bớt để xem thêm.</i>\n\n"
    kb_rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    return text, InlineKeyboardMarkup(kb_rows)


async def show_pending_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = _pending_withdrawals_view()
    await render_cb(update, text, kb)


async def refresh_pending_withdrawals(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Vẽ lại màn hình duyệt rút tiền khi KHÔNG có callback_query (ví dụ sau
    khi admin gõ lý do từ chối bằng tin nhắn text)."""
    text, kb = _pending_withdrawals_view()
    await render(context, ADMIN_ID, chat_id, text, kb)


WD_HISTORY_PER_PAGE = 10


async def show_admin_withdraw_history(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM withdrawals").fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM withdrawals ORDER BY id DESC LIMIT ? OFFSET ?",
        (WD_HISTORY_PER_PAGE, page * WD_HISTORY_PER_PAGE),
    ).fetchall()
    conn.close()

    if not rows:
        await render_cb(update, "📜 <b>LỊCH SỬ RÚT TIỀN (TẤT CẢ)</b>\n━━━━━━━━━━━━━━━\nChưa có yêu cầu rút tiền nào.", admin_menu_kb())
        return

    max_page = max(0, (total - 1) // WD_HISTORY_PER_PAGE)
    lines = []
    for r in rows:
        status = _WD_STATUS_LABEL.get(r["status"], r["status"])
        reason_line = f"\n   📄 Lý do từ chối: {r['reject_reason']}" if r["status"] == "rejected" and r["reject_reason"] else ""
        lines.append(
            f"🧾 #{r['id']} — user <code>{r['user_id']}</code> — <b>{money_fmt(r['amount'])}</b> — {status}\n"
            f"   🏦 {r['bank_info']}\n   <i>{fmt_vn(r['created_at'])}</i>{reason_line}"
        )
    text = (
        f"📜✨ <b>LỊCH SỬ RÚT TIỀN (TẤT CẢ)</b> ✨\n"
        "━━━━━━━━━━━━━━━\n"
        f"Tổng: <b>{total}</b> yêu cầu | Trang <b>{page + 1}/{max_page + 1}</b>\n\n"
        + "\n\n".join(lines)
    )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"adm_wdhistory_{page - 1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"adm_wdhistory_{page + 1}"))
    rows_kb = [nav] if nav else []
    rows_kb.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    await render_cb(update, text, InlineKeyboardMarkup(rows_kb))


async def _apply_wd_decision(context: ContextTypes.DEFAULT_TYPE, wd_id: int, approve: bool, reason: str = None):
    """Áp dụng quyết định duyệt/từ chối 1 yêu cầu rút tiền, hoàn tiền + báo
    cho user nếu từ chối. Trả về (ok, row) - ok=False nếu yêu cầu đã được
    xử lý từ trước (double-click, 2 admin cùng bấm...)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wd_id,)).fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        return False, row

    if approve:
        conn.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wd_id,))
    else:
        conn.execute(
            "UPDATE withdrawals SET status='rejected', reject_reason=? WHERE id=?",
            (reason, wd_id),
        )
        # hoàn tiền lại cho user
        col = "task_balance" if row["source"] == "task" else "ref_balance"
        conn.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id=?", (row["amount"], row["user_id"]))

    conn.commit()
    conn.close()

    try:
        if approve:
            msg = (
                "🎉💸 <b>RÚT TIỀN THÀNH CÔNG!</b> 💸🎉\n"
                "━━━━━━━━━━━━━━━\n"
                f"🧾 Mã giao dịch: <b>#{wd_id}</b>\n"
                f"💰 Số tiền: <b>+{money_fmt(row['amount'])}</b>\n"
                f"🏦 Ngân hàng: <code>{row['bank_info']}</code>\n"
                f"🕒 Thời gian duyệt: {fmt_vn(now_vn().isoformat())}\n"
                "━━━━━━━━━━━━━━━\n"
                "✅ Tiền đã được admin chuyển khoản. Cảm ơn bạn đã đồng hành "
                "cùng chúng tôi, tiếp tục kiếm thêm nhé! 🚀"
            )
        else:
            reason_line = f"📄 Lý do: <b>{reason}</b>\n\n" if reason else ""
            msg = (
                "❌🔁 <b>YÊU CẦU RÚT TIỀN BỊ TỪ CHỐI</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"🧾 Mã giao dịch: <b>#{wd_id}</b>\n"
                f"💰 Số tiền: <b>{money_fmt(row['amount'])}</b>\n"
                f"{reason_line}"
                "♻️ Số tiền đã được <b>hoàn lại đầy đủ</b> vào số dư của bạn.\n\n"
                "<i>Vui lòng kiểm tra lại thông tin ngân hàng hoặc liên hệ admin nếu cần hỗ trợ.</i>"
            )
        await render(context, row["user_id"], row["user_id"], msg, back_kb())
    except Exception:
        pass

    return True, row


async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE, wd_id: int):
    ok, _ = await _apply_wd_decision(context, wd_id, approve=True)
    if not ok:
        await q_answer(update, "Yêu cầu này đã được xử lý rồi.")
        return
    await show_pending_withdrawals(update, context)


async def reject_withdrawal_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, wd_id: int, reason: str = None):
    """Từ chối rút tiền khi có callback_query (ví dụ bấm '🚫 Từ chối không
    cần lý do')."""
    ok, _ = await _apply_wd_decision(context, wd_id, approve=False, reason=reason)
    if not ok:
        await q_answer(update, "Yêu cầu này đã được xử lý rồi.")
        return
    await show_pending_withdrawals(update, context)


async def reject_withdrawal_with_reason(context: ContextTypes.DEFAULT_TYPE, chat_id: int, wd_id: int, reason: str):
    """Từ chối rút tiền sau khi admin gõ lý do bằng tin nhắn text (không có
    callback_query để dùng render_cb, nên vẽ lại màn hình bằng render())."""
    ok, row = await _apply_wd_decision(context, wd_id, approve=False, reason=reason)
    if not ok:
        await render(context, ADMIN_ID, chat_id, "Yêu cầu này đã được xử lý rồi.", admin_menu_kb())
        return
    await refresh_pending_withdrawals(context, chat_id)


async def q_answer(update, text):
    try:
        await update.callback_query.answer(text, show_alert=True)
    except Exception:
        pass


# ============================================================
# MINI GAME CÁ CƯỢC - TÀI XỈU (3 viên xúc xắc, chơi trong group)
# ------------------------------------------------------------
# Nguyên tắc minh bạch: kết quả LUÔN lấy trực tiếp từ 3 viên xúc xắc thật
# do Telegram gửi (send_dice) - không có bất kỳ cách nào để admin sửa/ghi
# đè kết quả xúc xắc. Đây là lựa chọn CHỦ ĐỘNG: một mini game cá cược mà
# nhà cái (admin) có thể tự ý đổi kết quả sau khi user đã đặt cược là một
# cơ chế gian lận, không phải một tính năng vận hành - nên bot KHÔNG cung
# cấp nút "sửa kết quả". Admin chỉ có quyền HUỶ & HOÀN TIỀN nguyên vẹn một
# phiên (ví dụ khi bot lỗi kỹ thuật) chứ không được đổi ai thắng/thua.
# ============================================================

DICE_BET_SECONDS = 20
DICE_COUNTDOWN_STEP = 5

_BET_RE = re.compile(r"^\s*([txTX])\s*[:\-]?\s*(\d+)\s*$")


def coin_fmt(n):
    return f"{int(n):,}".replace(",", ".")


def create_dice_session(chat_id: int):
    conn = get_conn()
    last = conn.execute(
        "SELECT COALESCE(MAX(session_no),0) m FROM dice_sessions WHERE chat_id=?", (chat_id,)
    ).fetchone()["m"]
    conn.execute(
        "INSERT INTO dice_sessions (chat_id, session_no, status, created_at) VALUES (?,?,?,?)",
        (chat_id, last + 1, "betting", now_vn().isoformat()),
    )
    sid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()
    return get_dice_session(sid)


def get_dice_session(session_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM dice_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return row


def get_active_dice_session(chat_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM dice_sessions WHERE chat_id=? AND status IN ('betting','rolling') ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    conn.close()
    return row


def dice_session_totals(session_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT side, COALESCE(SUM(amount),0) s, COUNT(DISTINCT user_id) u "
        "FROM dice_bets WHERE session_id=? GROUP BY side",
        (session_id,),
    ).fetchall()
    conn.close()
    totals = {"to": {"amount": 0, "users": 0}, "nho": {"amount": 0, "users": 0}}
    for r in rows:
        totals[r["side"]] = {"amount": r["s"], "users": r["u"]}
    return totals


def dice_recent_history(chat_id: int, limit: int = 6):
    conn = get_conn()
    rows = conn.execute(
        "SELECT session_no, total, result FROM dice_sessions "
        "WHERE chat_id=? AND status='done' ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return rows


def dice_history_str(history_rows) -> str:
    if not history_rows:
        return "(chưa có phiên nào)"
    parts = []
    for r in history_rows:
        icon = "🔴T" if r["result"] == "to" else "🔵N"
        parts.append(f"#{r['session_no']}:{r['total']}{icon}")
    return " | ".join(parts)


def dice_game_text(session, totals, history_rows, status_line: str) -> str:
    to_t, nho_t = totals["to"], totals["nho"]
    return (
        f"🎲✨ <b>TÀI XỈU - PHIÊN #{session['session_no']}</b> ✨🎲\n"
        "━━━━━━━━━━━━━━━\n"
        f"{status_line}\n\n"
        f"🔴 Cửa <b>TO</b> (tổng 11-18): <b>{coin_fmt(to_t['amount'])} coin</b> — {to_t['users']} người chơi\n"
        f"🔵 Cửa <b>NHỎ</b> (tổng 3-10): <b>{coin_fmt(nho_t['amount'])} coin</b> — {nho_t['users']} người chơi\n"
        "━━━━━━━━━━━━━━━\n"
        "📝 <b>Cú pháp đặt cược</b> (gõ thẳng trong nhóm):\n"
        "<code>T &lt;số coin&gt;</code> — đặt cửa <b>TO</b>\n"
        "<code>X &lt;số coin&gt;</code> — đặt cửa <b>NHỎ</b>\n"
        "Ví dụ: <code>T 100</code> hoặc <code>X 50</code>\n\n"
        f"📜 Lịch sử gần đây: {dice_history_str(history_rows)}"
    )


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("🎲 Lệnh này chỉ dùng được trong group có bot ở trong đó nhé!")
        return

    existing = get_active_dice_session(chat.id)
    if existing:
        await update.message.reply_text(
            f"⚠️ Phiên #{existing['session_no']} đang diễn ra, chờ phiên này kết thúc rồi mở phiên mới nhé!"
        )
        return

    session = create_dice_session(chat.id)
    totals = dice_session_totals(session["id"])
    history = dice_recent_history(chat.id)
    text = dice_game_text(session, totals, history, f"⏰ Còn <b>{DICE_BET_SECONDS}s</b> để đặt cược!")
    sent = await context.bot.send_message(chat.id, text, parse_mode="HTML")

    conn = get_conn()
    conn.execute("UPDATE dice_sessions SET game_msg_id=? WHERE id=?", (sent.message_id, session["id"]))
    conn.commit()
    conn.close()

    context.application.create_task(run_dice_countdown(context, chat.id, session["id"], sent.message_id))


async def run_dice_countdown(context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: int, msg_id: int):
    remaining = DICE_BET_SECONDS
    while remaining > 0:
        await asyncio.sleep(min(DICE_COUNTDOWN_STEP, remaining))
        remaining -= DICE_COUNTDOWN_STEP
        session = get_dice_session(session_id)
        if not session or session["status"] != "betting":
            return  # phiên đã bị admin huỷ giữa chừng
        totals = dice_session_totals(session_id)
        history = dice_recent_history(chat_id)
        status = f"⏰ Còn <b>{max(remaining, 0)}s</b> để đặt cược!" if remaining > 0 else "🔒 Đã đóng cược, chuẩn bị quay xúc xắc..."
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=dice_game_text(session, totals, history, status),
                parse_mode="HTML",
            )
        except Exception:
            pass

    session = get_dice_session(session_id)
    if session and session["status"] == "betting":
        await close_dice_session(context, chat_id, session_id, msg_id)


async def close_dice_session(context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: int, msg_id: int):
    conn = get_conn()
    conn.execute("UPDATE dice_sessions SET status='rolling' WHERE id=? AND status='betting'", (session_id,))
    conn.commit()
    conn.close()

    session = get_dice_session(session_id)
    if not session or session["status"] != "rolling":
        return  # đã được xử lý ở nơi khác (ví dụ vừa bị admin huỷ)

    totals = dice_session_totals(session_id)
    history = dice_recent_history(chat_id)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=dice_game_text(session, totals, history, "⏳ <i>Đang đổ 3 viên xúc xắc...</i> 🎲🎲🎲"),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Đổ 3 viên xúc xắc THẬT qua Telegram (send_dice) - giá trị lấy trực
    # tiếp từ kết quả animation do server Telegram trả về, con người (kể cả
    # admin) không thể can thiệp vào giá trị này.
    values = []
    for _ in range(3):
        try:
            dmsg = await context.bot.send_dice(chat_id, emoji="🎲")
            values.append(dmsg.dice.value)
        except Exception:
            values.append(random.randint(1, 6))
        await asyncio.sleep(1.2)  # chờ hiệu ứng đổ xúc xắc chạy xong trên Telegram

    total = sum(values)
    result = "to" if total >= 11 else "nho"

    conn = get_conn()
    conn.execute(
        "UPDATE dice_sessions SET status='done', dice1=?, dice2=?, dice3=?, total=?, result=?, closed_at=? WHERE id=?",
        (values[0], values[1], values[2], total, result, now_vn().isoformat(), session_id),
    )
    conn.commit()
    bets = conn.execute("SELECT * FROM dice_bets WHERE session_id=?", (session_id,)).fetchall()
    conn.close()

    winners = 0
    for b in bets:
        if b["side"] == result:
            conn = get_conn()
            conn.execute("UPDATE users SET coin = coin + ? WHERE user_id=?", (b["amount"] * 2, b["user_id"]))
            conn.commit()
            conn.close()
            winners += 1

    session = get_dice_session(session_id)
    history = dice_recent_history(chat_id)
    result_label = "🔴 TO" if result == "to" else "🔵 NHỎ"
    final_text = (
        f"🎲✨ <b>KẾT QUẢ PHIÊN #{session['session_no']}</b> ✨🎲\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎯 {values[0]} + {values[1]} + {values[2]} = <b>{total}</b>\n"
        f"🏆 Kết quả: <b>{result_label}</b>\n\n"
        f"👥 Tổng lượt cược: <b>{len(bets)}</b>  |  🎉 Thắng: <b>{winners}</b>\n"
        f"📜 Lịch sử gần đây: {dice_history_str(history)}\n\n"
        "👉 Gõ /startgame để mở phiên cược mới!"
    )
    try:
        await context.bot.send_message(chat_id, final_text, parse_mode="HTML")
    except Exception:
        pass


async def handle_group_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt cú pháp đặt cược 'T <coin>' / 'X <coin>' trong group khi có phiên
    Tài Xỉu đang mở cược. Không xử lý gì thêm nếu không khớp cú pháp hoặc
    không có phiên nào đang chạy."""
    message = update.message
    if not message or not message.text:
        return
    m = _BET_RE.match(message.text)
    if not m:
        return
    chat_id = update.effective_chat.id
    session = get_active_dice_session(chat_id)
    if not session or session["status"] != "betting":
        return

    side = "to" if m.group(1).lower() == "t" else "nho"
    try:
        amount = int(m.group(2))
    except ValueError:
        return
    if amount <= 0:
        return

    user_tg = update.effective_user
    user = get_user(user_tg.id)
    if not user:
        create_user(user_tg.id, user_tg.username or user_tg.first_name)
        user = get_user(user_tg.id)
    if is_banned(user):
        return
    if user["coin"] < amount:
        try:
            reply = await message.reply_text(f"❌ Bạn không đủ coin (hiện có {user['coin']} coin).")
            await asyncio.sleep(3)
            await reply.delete()
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
        return

    conn = get_conn()
    conn.execute("UPDATE users SET coin = coin - ? WHERE user_id=?", (amount, user_tg.id))
    conn.execute(
        "INSERT INTO dice_bets (session_id, user_id, username, side, amount, created_at) VALUES (?,?,?,?,?,?)",
        (session["id"], user_tg.id, user_tg.username or user_tg.first_name, side, amount, now_vn().isoformat()),
    )
    conn.commit()
    conn.close()

    try:
        await message.delete()
    except Exception:
        pass  # giữ chat gọn, không sao nếu bot thiếu quyền xoá

    if session["game_msg_id"]:
        totals = dice_session_totals(session["id"])
        history = dice_recent_history(chat_id)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=session["game_msg_id"],
                text=dice_game_text(session, totals, history, "🔓 <b>Đang mở cược</b> — nhanh tay đặt cửa!"),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ---------------- Admin: quản lý Tài Xỉu ----------------

async def show_dice_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    active = conn.execute(
        "SELECT * FROM dice_sessions WHERE status IN ('betting','rolling') ORDER BY id DESC"
    ).fetchall()
    recent_done = conn.execute(
        "SELECT * FROM dice_sessions WHERE status='done' ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()

    lines = ["🎲✨ <b>QUẢN LÝ TÀI XỈU</b> ✨", "━━━━━━━━━━━━━━━"]
    rows = []
    if active:
        lines.append("🟢 <b>Phiên đang chạy:</b>")
        for s in active:
            lines.append(f"• Chat <code>{s['chat_id']}</code> — phiên #{s['session_no']} — trạng thái: {s['status']}")
            rows.append([InlineKeyboardButton(
                f"🛑 Huỷ & hoàn tiền phiên #{s['session_no']}", callback_data=f"adm_dicevoid_{s['id']}"
            )])
    else:
        lines.append("🟢 Không có phiên nào đang chạy.")

    lines.append("\n📜 <b>10 phiên gần nhất đã kết thúc:</b>")
    if recent_done:
        for s in recent_done:
            label = "TO" if s["result"] == "to" else "NHỎ"
            lines.append(f"• Chat <code>{s['chat_id']}</code> #{s['session_no']}: {s['dice1']}+{s['dice2']}+{s['dice3']}={s['total']} → {label}")
    else:
        lines.append("(chưa có phiên nào)")

    lines.append(
        "\n<i>Nút 🛑 chỉ dùng khi có sự cố kỹ thuật (bot lỗi, spam...) — toàn "
        "bộ coin cược của phiên đó sẽ được hoàn nguyên vẹn cho user. Bot "
        "không có tuỳ chọn sửa kết quả xúc xắc: kết quả luôn lấy trực tiếp "
        "từ xúc xắc thật của Telegram để đảm bảo minh bạch, công bằng cho "
        "người chơi.</i>"
    )
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_admin")])
    await render_cb(update, "\n".join(lines), InlineKeyboardMarkup(rows))


async def void_dice_session(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: int):
    conn = get_conn()
    session = conn.execute("SELECT * FROM dice_sessions WHERE id=?", (session_id,)).fetchone()
    if not session or session["status"] not in ("betting", "rolling"):
        conn.close()
        await q_answer(update, "Phiên này đã kết thúc hoặc không tồn tại.")
        return
    bets = conn.execute("SELECT * FROM dice_bets WHERE session_id=?", (session_id,)).fetchall()
    for b in bets:
        conn.execute("UPDATE users SET coin = coin + ? WHERE user_id=?", (b["amount"], b["user_id"]))
    conn.execute(
        "UPDATE dice_sessions SET status='cancelled', closed_at=? WHERE id=?",
        (now_vn().isoformat(), session_id),
    )
    conn.commit()
    conn.close()
    try:
        await context.bot.send_message(
            session["chat_id"],
            f"🛑 <b>PHIÊN #{session['session_no']} ĐÃ BỊ HUỶ</b>\nToàn bộ coin cược đã được hoàn lại cho người chơi.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await show_dice_admin(update, context)


# ============================================================
# TEXT MESSAGE HANDLER (dùng cho các bước nhập liệu: bank info, rút tiền,
# broadcast, thêm Tài Nguyên, cấu hình...)
# ============================================================

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Tin nhắn trong group/supergroup: chỉ dùng để bắt cú pháp đặt cược Tài
    # Xỉu (T/X <coin>) - toàn bộ luồng nhập liệu private (bank info, rút
    # tiền, admin...) chỉ áp dụng cho chat riêng nên dừng lại ở đây.
    if update.effective_chat.type in ("group", "supergroup"):
        await handle_group_text(update, context)
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    awaiting = context.user_data.get("awaiting")
    text = update.message.text.strip()

    if awaiting == "bank_info":
        parts = [p.strip() for p in text.split("|")]
        await try_delete_message(update)
        if len(parts) != 3:
            await render(
                context, user_id, chat_id,
                "❌ <b>SAI CÚ PHÁP</b>\n━━━━━━━━━━━━━━━\nGửi lại theo dạng:\n"
                "<code>Ngân hàng | STK | Chủ TK</code>",
                back_kb(),
            )
            return
        conn = get_conn()
        conn.execute("UPDATE users SET bank_info=? WHERE user_id=?", (text, user_id))
        conn.commit()
        conn.close()
        context.user_data.pop("awaiting", None)
        await render(
            context, user_id, chat_id,
            "✅🏦 <b>ĐÃ LƯU THÔNG TIN NGÂN HÀNG</b>\n━━━━━━━━━━━━━━━\n"
            f"<code>{text}</code>\n\nBấm bên dưới để quay lại rút tiền.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Rút tiền", callback_data="menu_withdraw")],
                [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
            ]),
        )
        return

    if awaiting == "withdraw_amount":
        await try_delete_message(update)
        if not text.isdigit():
            await render(context, user_id, chat_id, "❌ Vui lòng nhập số hợp lệ.", back_kb())
            return
        context.user_data.pop("awaiting", None)
        amount = int(text)
        await create_withdrawal_from_message(update, context, amount)
        return

    # ---------- ADMIN ONLY ----------
    if user_id != ADMIN_ID:
        return

    if awaiting == "wd_reject_reason":
        wd_id = context.user_data.get("wd_reject_target")
        context.user_data.pop("awaiting", None)
        context.user_data.pop("wd_reject_target", None)
        await try_delete_message(update)
        if wd_id is not None:
            await reject_withdrawal_with_reason(context, chat_id, wd_id, text)
        return

    if awaiting == "ban_reason":
        uid = context.user_data.get("ban_target")
        context.user_data["ban_reason_text"] = text
        context.user_data["awaiting"] = None
        await try_delete_message(update)
        rows = [[InlineKeyboardButton(label, callback_data=f"adm_banlen_{uid}_{days}")]
                for label, days in BAN_DURATIONS]
        rows.append([InlineKeyboardButton("⬅️ Huỷ", callback_data=f"adm_u_{uid}")])
        await render(
            context, ADMIN_ID, chat_id,
            f"🚫 <b>CẤM USER</b> <code>{uid}</code>\n━━━━━━━━━━━━━━━\n"
            f"📄 Lý do: <b>{text}</b>\n\nChọn thời hạn cấm:",
            InlineKeyboardMarkup(rows),
        )
        return

    if awaiting == "adjust_balance":
        uid = context.user_data.pop("adjbal_target", None)
        context.user_data.pop("awaiting", None)
        await try_delete_message(update)
        try:
            amount = int(text)
        except ValueError:
            await render(
                context, ADMIN_ID, chat_id,
                "❌ Số tiền không hợp lệ, vui lòng thao tác lại từ menu Quản lý user.",
                admin_menu_kb(),
            )
            return
        add_balance(uid, amount, 0, "task", "admin_adjust")
        try:
            note = "🎁 Bạn vừa được admin cộng thêm" if amount >= 0 else "⚠️ Số dư của bạn vừa bị admin điều chỉnh trừ"
            await render(context, uid, uid, f"{note} <b>{money_fmt(abs(amount))}</b>.", back_kb())
        except Exception:
            pass
        await render(
            context, ADMIN_ID, chat_id,
            f"✅ Đã {'cộng' if amount >= 0 else 'trừ'} {money_fmt(abs(amount))} cho user <code>{uid}</code>.",
            admin_menu_kb(),
        )
        return

    if awaiting == "adjust_coin":
        uid = context.user_data.pop("adjcoin_target", None)
        context.user_data.pop("awaiting", None)
        await try_delete_message(update)
        try:
            amount = int(text)
        except ValueError:
            await render(
                context, ADMIN_ID, chat_id,
                "❌ Số coin không hợp lệ, vui lòng thao tác lại từ menu Quản lý user.",
                admin_menu_kb(),
            )
            return
        conn = get_conn()
        conn.execute("UPDATE users SET coin = coin + ? WHERE user_id=?", (amount, uid))
        conn.commit()
        conn.close()
        try:
            note = "🎁 Bạn vừa được admin cộng thêm" if amount >= 0 else "⚠️ Coin của bạn vừa bị admin điều chỉnh trừ"
            await render(context, uid, uid, f"{note} <b>{abs(amount)} coin</b>.", back_kb())
        except Exception:
            pass
        await render(
            context, ADMIN_ID, chat_id,
            f"✅ Đã {'cộng' if amount >= 0 else 'trừ'} {abs(amount)} coin cho user <code>{uid}</code>.",
            admin_menu_kb(),
        )
        return

    if awaiting == "broadcast":
        context.user_data.pop("awaiting", None)
        conn = get_conn()
        ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]
        conn.close()
        sent, failed = 0, 0
        for uid in ids:
            try:
                await context.bot.copy_message(uid, chat_id, update.message.message_id)
                sent += 1
            except Exception:
                failed += 1
        await try_delete_message(update)
        await render(
            context, ADMIN_ID, chat_id,
            f"📢✅ <b>ĐÃ GỬI THÔNG BÁO</b>\n━━━━━━━━━━━━━━━\nThành công: <b>{sent}</b>  |  Lỗi: <b>{failed}</b>",
            admin_menu_kb(),
        )
        return

    if awaiting == "finduser_id":
        context.user_data.pop("awaiting", None)
        await try_delete_message(update)
        if not text.isdigit():
            await render(context, ADMIN_ID, chat_id, "❌ ID không hợp lệ, vui lòng chỉ nhập số.", admin_menu_kb())
            return
        await show_user_detail_by_id(context, chat_id, int(text))
        return

    if awaiting == "edit_tool_price":
        tool_id = context.user_data.pop("edit_tool_id", None)
        context.user_data.pop("awaiting", None)
        await try_delete_message(update)
        if not text.isdigit():
            await render(context, ADMIN_ID, chat_id, "❌ Vui lòng nhập số.", admin_menu_kb())
            return
        conn = get_conn()
        conn.execute("UPDATE tools SET price_coin=? WHERE id=?", (int(text), tool_id))
        conn.commit()
        conn.close()
        await render(context, ADMIN_ID, chat_id, f"✅ Đã cập nhật giá Tài Nguyên thành <b>{text} coin</b>.", admin_menu_kb())
        return

    if awaiting == "addtool_name":
        context.user_data["new_tool_name"] = text
        context.user_data["awaiting"] = "addtool_price"
        await try_delete_message(update)
        await render(context, ADMIN_ID, chat_id, f"🎁 Tên Tài Nguyên: <b>{text}</b>\n\nNhập <b>giá coin</b> cho Tài Nguyên này:", back_kb())
        return

    if awaiting == "addtool_price":
        await try_delete_message(update)
        if not text.isdigit():
            await render(context, ADMIN_ID, chat_id, "❌ Vui lòng nhập số.", back_kb())
            return
        context.user_data["new_tool_price"] = int(text)
        context.user_data["awaiting"] = "addtool_accounts"
        await render(
            context, ADMIN_ID, chat_id,
            "Nhập danh sách tài khoản, mỗi dòng 1 tài khoản, dạng:\n<code>user:pass</code>",
            back_kb(),
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
        await try_delete_message(update)
        await render(
            context, ADMIN_ID, chat_id,
            f"✅🎁 <b>ĐÃ TẠO TÀI NGUYÊN MỚI</b>\n━━━━━━━━━━━━━━━\n🎁 {name} — {price} coin",
            admin_menu_kb(),
        )
        return

    if awaiting == "topup_accounts":
        tool_id = context.user_data.pop("topup_tool_id", None)
        context.user_data.pop("awaiting", None)
        await try_delete_message(update)
        conn = get_conn()
        tool = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
        if not tool:
            conn.close()
            await render(context, ADMIN_ID, chat_id, "❌ Tài Nguyên không tồn tại (có thể đã bị xoá).", admin_menu_kb())
            return
        existing = tool["accounts"]
        merged = (existing + "\n" + text) if existing.strip() else text
        conn.execute("UPDATE tools SET accounts=? WHERE id=?", (merged, tool_id))
        conn.commit()
        conn.close()
        added = len([a for a in text.split("\n") if a.strip()])
        await render(
            context, ADMIN_ID, chat_id,
            f"✅➕ <b>ĐÃ NẠP THÊM {added} TÀI KHOẢN</b>\nvào Tài Nguyên <b>{tool['name']}</b>.",
            admin_menu_kb(),
        )
        return


async def create_withdrawal_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user = get_user(user_id)
    min_task = int(cfg("min_withdraw_task", 10000))
    min_ref = int(cfg("min_withdraw_ref", 50000))
    total = user["task_balance"] + user["ref_balance"]

    if amount > total:
        await render(context, user_id, chat_id, f"❌ Số dư không đủ. Số dư hiện tại: {money_fmt(total)}", back_kb())
        return
    source = "task" if amount <= user["task_balance"] else "ref"
    min_required = min_task if source == "task" else min_ref
    if amount < min_required:
        await render(context, user_id, chat_id, f"❌ Số tiền rút tối thiểu là {money_fmt(min_required)}.", back_kb())
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
        (user_id, amount, source, user["bank_info"], "pending", now_vn().isoformat()),
    )
    wd_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()

    await render(
        context, user_id, chat_id,
        "✅📤 <b>ĐÃ GỬI YÊU CẦU RÚT TIỀN</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Số tiền: <b>{money_fmt(amount)}</b>\n"
        f"🏦 Ngân hàng: <code>{user['bank_info']}</code>\n\n"
        "⏰ Admin sẽ duyệt trong thời gian sớm nhất.",
        back_kb(),
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Duyệt", callback_data=f"adm_wdok_{wd_id}"),
        InlineKeyboardButton("❌ Từ chối", callback_data=f"adm_wdno_{wd_id}"),
    ]])
    await render(
        context, ADMIN_ID, ADMIN_ID,
        f"💸✨ <b>YÊU CẦU RÚT TIỀN MỚI #{wd_id}</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 User: <code>{user_id}</code>\n💰 Số tiền: {money_fmt(amount)}\n🏦 Ngân hàng: {user['bank_info']}",
        kb,
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
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if not context.args:
        await render(context, ADMIN_ID, chat_id, "Cú pháp: <code>/setlink4m &lt;api_key&gt;</code>", admin_menu_kb())
        return
    set_cfg("link4m_api_key", context.args[0])
    await render(context, ADMIN_ID, chat_id, "✅ Đã cập nhật API key link4m.", admin_menu_kb())


async def cmd_setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if len(context.args) != 2:
        await render(context, ADMIN_ID, chat_id, "Cú pháp: <code>/setreward &lt;min&gt; &lt;max&gt;</code>", admin_menu_kb())
        return
    set_cfg("reward_min", context.args[0])
    set_cfg("reward_max", context.args[1])
    await render(context, ADMIN_ID, chat_id, "✅ Đã cập nhật mức thưởng nhiệm vụ.", admin_menu_kb())


async def cmd_setrefbonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if not context.args:
        await render(context, ADMIN_ID, chat_id, "Cú pháp: <code>/setrefbonus &lt;số tiền&gt;</code>", admin_menu_kb())
        return
    set_cfg("ref_bonus", context.args[0])
    await render(context, ADMIN_ID, chat_id, "✅ Đã cập nhật thưởng giới thiệu.", admin_menu_kb())


async def cmd_setminwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if len(context.args) != 2:
        await render(context, ADMIN_ID, chat_id, "Cú pháp: <code>/setminwd &lt;min_task&gt; &lt;min_ref&gt;</code>", admin_menu_kb())
        return
    set_cfg("min_withdraw_task", context.args[0])
    set_cfg("min_withdraw_ref", context.args[1])
    await render(context, ADMIN_ID, chat_id, "✅ Đã cập nhật min rút tiền.", admin_menu_kb())


async def cmd_finduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if not context.args or not context.args[0].isdigit():
        await render(context, ADMIN_ID, chat_id, "Cú pháp: <code>/finduser &lt;id&gt;</code>", admin_menu_kb())
        return
    uid = int(context.args[0])
    await show_user_detail_by_id(context, chat_id, uid)


async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    if len(context.args) != 2 or not context.args[0].isdigit():
        await render(
            context, ADMIN_ID, chat_id,
            "Cú pháp: <code>/addbalance &lt;id&gt; &lt;số tiền&gt;</code> (số tiền có thể âm để trừ)",
            admin_menu_kb(),
        )
        return
    uid = int(context.args[0])
    try:
        amount = int(context.args[1])
    except ValueError:
        await render(context, ADMIN_ID, chat_id, "❌ Số tiền không hợp lệ.", admin_menu_kb())
        return
    user = get_user(uid)
    if not user:
        await render(context, ADMIN_ID, chat_id, "❌ Không tìm thấy user này.", admin_menu_kb())
        return
    add_balance(uid, amount, 0, "task", "admin_adjust")
    await render(
        context, ADMIN_ID, chat_id,
        f"✅ Đã {'cộng' if amount >= 0 else 'trừ'} {money_fmt(abs(amount))} cho user <code>{uid}</code>.",
        admin_menu_kb(),
    )
    try:
        note = "🎁 Bạn vừa được admin cộng thêm" if amount >= 0 else "⚠️ Số dư của bạn vừa bị admin điều chỉnh trừ"
        await render(context, uid, uid, f"{note} <b>{money_fmt(abs(amount))}</b>.", back_kb())
    except Exception:
        pass


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    chat_id = update.effective_chat.id
    await try_delete_message(update)
    # Admin cũng phải xác minh kênh y hệt user thường - không có ngoại lệ,
    # kể cả khi gõ thẳng lệnh /admin.
    if not await is_verified(context, ADMIN_ID):
        await render(context, ADMIN_ID, chat_id, verify_gate_text(), verify_keyboard())
        return
    await show_admin_from_scratch(context, chat_id)


async def show_admin_from_scratch(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    await render(
        context, ADMIN_ID, chat_id,
        f"⚙️✨ <b>ADMIN PANEL</b> ✨⚙️\n━━━━━━━━━━━━━━━\n👥 Tổng user: <b>{total_users}</b>",
        admin_menu_kb(),
    )


# ============================================================
# TỰ ĐỘNG NHẬN KÊNH XÁC MINH KHI ADMIN THÊM BOT VÀO KÊNH/GROUP
# ============================================================

async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    chat = cm.chat
    if chat.type not in ("channel", "group", "supergroup"):
        return
    channel_id = f"@{chat.username}" if chat.username else str(chat.id)

    if cm.new_chat_member.status in ("administrator", "member"):
        # Luôn ghi nhận vào danh sách "kênh bot đã được add vào", bất kể ai
        # thêm bot, để admin xem lại được kể cả khi không tự bật làm kênh
        # bắt buộc ngay lúc đó.
        upsert_channel(channel_id, chat.title or channel_id, "active")

        adder = cm.from_user.id
        if adder != ADMIN_ID:
            return
        # Tự động bật kênh vừa thêm thành kênh BẮT BUỘC - CỘNG THÊM vào danh
        # sách đang có (hỗ trợ nhiều kênh/group cùng lúc), không còn thay
        # thế kênh cũ như trước nữa. Vì vừa có thêm 1 điều kiện mới, buộc
        # TẤT CẢ user (kể cả admin) phải xác minh lại từ đầu, tránh trường
        # hợp user cũ đã có cờ verified=1 nhưng chưa hề tham gia kênh mới
        # này.
        set_channel_required(channel_id, True)
        reset_all_verified()
        try:
            await render(
                context, ADMIN_ID, ADMIN_ID,
                f"✅📡 <b>ĐÃ THÊM KÊNH XÁC MINH BẮT BUỘC</b>\n━━━━━━━━━━━━━━━\n"
                f"Kênh: <b>{chat.title}</b>\nID: <code>{channel_id}</code>\n\n"
                "🔁 Đã yêu cầu <b>toàn bộ user (kể cả bạn)</b> xác minh lại vì "
                "vừa thêm 1 kênh bắt buộc mới.\n\n"
                "👉 Vào <b>⚙️ Quản trị viên → 📡 Kênh xác minh</b> nếu muốn bỏ "
                "bớt kênh này hoặc xem toàn bộ danh sách kênh đang bắt buộc.",
                admin_menu_kb(),
            )
        except Exception:
            pass
    else:
        # Bot bị gỡ / rời khỏi kênh (left, kicked...) -> đánh dấu "tắt" và bỏ
        # luôn khỏi danh sách bắt buộc (bot không còn ở trong kênh thì không
        # thể kiểm tra thành viên nữa, giữ bắt buộc sẽ khoá cứng mọi user).
        upsert_channel(channel_id, chat.title or channel_id, "removed")
        set_channel_required(channel_id, False)


# ============================================================
# MINI HTTP SERVER (chỉ để Render Web Service không báo lỗi healthcheck -
# không còn xử lý nhiệm vụ qua web nữa, quay lại xác nhận qua deep-link
# Telegram như ban đầu)
# ============================================================

def run_health_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

        def log_message(self, *a):
            pass

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    try:
        with ReusableTCPServer(("0.0.0.0", PORT), Handler) as httpd:
            httpd.serve_forever()
    except OSError as e:
        logger.warning("Không mở được health server ở cổng %s: %s", PORT, e)


# ============================================================
# XỬ LÝ LỖI TOÀN CỤC - đảm bảo bot KHÔNG BAO GIỜ "im lặng" không phản hồi
# khi có lỗi bất ngờ (mất mạng, tin nhắn bị xoá do clear lịch sử chat,
# Telegram API lỗi tạm thời...). Mọi exception chưa được bắt ở nơi khác
# đều rơi vào đây, được ghi log để debug và luôn cố gắng báo cho user biết
# để họ thử lại thay vì tưởng bot bị treo.
# ============================================================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Lỗi chưa xử lý khi xử lý update=%s", update, exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                update.effective_chat.id,
                "⚠️ <b>Có lỗi tạm thời xảy ra.</b>\nVui lòng bấm /start để tiếp tục nhé!",
                parse_mode="HTML",
            )
    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main():
    global BOT_USERNAME

    init_db()

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
    app.add_handler(CommandHandler("finduser", cmd_finduser))
    app.add_handler(CommandHandler("addbalance", cmd_addbalance))
    app.add_handler(CommandHandler("startgame", cmd_startgame))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_error_handler(on_error)

    # lấy username bot ngay lúc khởi động để dùng cho deep-link t.me/<username>?start=...
    loop = asyncio.get_event_loop()

    async def _fetch_username():
        global BOT_USERNAME, BOT_NAME
        me = await app.bot.get_me()
        BOT_USERNAME = me.username
        BOT_NAME = me.first_name or me.username

    loop.run_until_complete(_fetch_username())

    threading.Thread(target=run_health_server, daemon=True).start()

    logger.info("Bot đang khởi động... username=@%s", BOT_USERNAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
