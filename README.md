# Bot Telegram Kiếm Tiền Online (link4m)

## ⚠️ BẢO MẬT — làm ngay trước khi deploy
Token bot bạn gửi trong yêu cầu đã bị lộ ra ngoài (trong đoạn chat này).
1. Vào **@BotFather** → `/mybots` → chọn bot → **API Token** → **Revoke current token**.
2. Lấy token mới, **không dán trực tiếp vào code** — set qua biến môi trường ở bước deploy bên dưới.

## Cài đặt local (test thử)
```bash
pip install -r requirements.txt
export BOT_TOKEN="token_moi_cua_ban"
export ADMIN_ID="8685327154"
export LINK4M_API_KEY="6a93e433c1e0cd622c1112a8"
python bot.py
```

## Deploy trên Render
1. Đẩy 3 file `bot.py`, `requirements.txt`, `Procfile` lên 1 GitHub repo.
2. Trên Render: **New → Background Worker** (khuyên dùng, đơn giản, không cần mở port)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
3. Vào tab **Environment** thêm các biến:
   - `BOT_TOKEN` = token mới
   - `ADMIN_ID` = 8685327154
   - `LINK4M_API_KEY` = api key link4m của bạn
4. Deploy. Bot dùng SQLite (`bot.db`) tự tạo khi chạy — nếu muốn dữ liệu không mất khi
   redeploy, vào Render thêm **Disk** mount vào thư mục chứa `bot.db`, hoặc set
   `DB_PATH=/data/bot.db` sau khi mount disk ở `/data`.

(Nếu chọn deploy kiểu **Web Service** thay vì Background Worker cũng chạy được —
file đã tự mở sẵn 1 HTTP server nhỏ ở cổng `$PORT` để healthcheck của Render pass.)

## Cách dùng sau khi bot chạy
- Gõ `/start` để mở menu chính.
- Gõ `/admin` (chỉ ADMIN_ID dùng được) để mở bảng quản trị.
- **Đặt kênh xác minh bắt buộc**: thêm bot vào kênh/group của bạn và cấp quyền
  admin cho bot → bot tự động lưu kênh đó làm kênh xác minh.
- **Đổi API key link4m**: `/setlink4m <api_key>`
- **Đổi mức thưởng nhiệm vụ**: `/setreward <min> <max>` (đơn vị đồng)
- **Đổi thưởng giới thiệu**: `/setrefbonus <số tiền>`
- **Đổi mức rút tối thiểu**: `/setminwd <min_nhiệm_vụ> <min_giới_thiệu>`
- **Thêm gói tool để đổi coin**: vào `/admin` → "➕ Thêm gói tool", nhập tên,
  giá coin, rồi danh sách tài khoản (mỗi dòng 1 acc dạng `user:pass`).
- **Duyệt rút tiền**: mỗi khi có user gửi yêu cầu, bạn sẽ nhận tin nhắn kèm 2 nút
  Duyệt / Từ chối. Từ chối sẽ tự hoàn tiền lại cho user.

## Lưu ý về logic đã cài sẵn
- Mỗi nhiệm vụ tạo ra 1 link4m link gắn với 1 token dùng đúng 1 lần, khớp đúng
  user đã tạo ra nó — người khác không dùng lại được.
- Số dư tách riêng "tiền nhiệm vụ" và "tiền giới thiệu" để áp dụng đúng mức rút
  tối thiểu (10k / 50k) theo đúng yêu cầu — khi rút, hệ thống trừ tiền nhiệm vụ
  trước, thiếu bao nhiêu mới trừ thêm tiền giới thiệu.
- Thưởng giới thiệu chỉ được cộng khi người được mời **xác minh tham gia kênh
  thành công lần đầu**, để hạn chế tạo tài khoản ảo mời khống.
- Toàn bộ điều hướng dùng edit lại đúng 1 tin nhắn — không spam tin nhắn mới.

## Bạn nên tự kiểm tra thêm
- link4m có thể đổi format JSON trả về — hãy thử `do_task()` thực tế 1 lần, nếu
  link không tạo được, in log console để xem field JSON đúng tên là gì rồi sửa
  trong hàm `create_link4m()`.
- Đây là mô hình kiếm tiền qua lượt xem quảng cáo (CPA) — doanh thu thật của bạn
  đến từ link4m trả cho lượt hoàn thành thật, không phải "tiền tự sinh ra", nên
  hãy cân đối mức thưởng trả cho user thấp hơn mức bạn nhận từ link4m để không bị lỗ.
