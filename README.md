# Bot Telegram Kiếm Tiền Online (link4m) - bản deep-link + nút bấm

## ⚠️ BẢO MẬT — làm ngay trước khi deploy
Nếu bạn chưa thu hồi token cũ (đã từng bị dán ra trong lịch sử chat):
1. Vào **@BotFather** → `/mybots` → chọn bot → **API Token** → **Revoke current token**.
2. Lấy token mới, set qua biến môi trường (không hardcode vào code).

## Kiến trúc (đã quay lại đúng dạng ban đầu bạn yêu cầu)
- Khi user bấm "📝 Làm nhiệm vụ", bot tạo 1 token riêng (32 ký tự) và tạo link đích dạng:
  `t.me/<bot_username>?start=task_<token>`
- Link đó được gửi qua API link4m để rút gọn:
  `https://link4m.co/st?api=<key>&url=<destination_url>`
- Link rút gọn được gắn vào **nút bấm** (không hiện text thô) — user bấm nút, vượt
  qua các bước quảng cáo trên link4m, xong sẽ tự động được đưa quay lại app
  Telegram và mở bot với lệnh `/start task_<token>`.
- Bot nhận lệnh đó, kiểm tra: token tồn tại? chưa dùng lần nào? đúng user đã
  tạo ra nó? → nếu hợp lệ, cộng tiền + coin ngay lập tức và edit tin nhắn báo
  hoàn thành. Token dùng 1 lần duy nhất, ai tạo người đó dùng, không thể tái
  sử dụng hay chia sẻ.
- **Chỉ 1 tin nhắn duy nhất tồn tại trong đoạn chat**: `/start` được tự động
  xoá ngay sau khi xử lý, mọi thao tác khác đều edit lại đúng tin nhắn dashboard
  cũ (không gửi tin nhắn mới trừ khi tin cũ không edit được, lúc đó sẽ xoá tin
  cũ trước khi gửi tin mới).

## Cài đặt local (test thử)
```bash
pip install -r requirements.txt
export BOT_TOKEN="token_moi_cua_ban"
export ADMIN_ID="8685327154"
export LINK4M_API_KEY="6a93e433c1e0cd622c1112a8"
python bot.py
```

## Deploy trên Render
Bản này không còn cần web server public nữa (không dùng Flask), nên đơn giản hơn:
1. Đẩy 4 file `bot.py`, `requirements.txt`, `Procfile`, `runtime.txt` lên GitHub repo.
2. Trên Render: **New → Background Worker** (khuyên dùng — đơn giản, rẻ hơn Web Service)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
3. Tab **Environment**, thêm biến:
   - `BOT_TOKEN` = token mới
   - `ADMIN_ID` = 8685327154
   - `LINK4M_API_KEY` = api key link4m của bạn
4. Deploy.
5. Nếu muốn dữ liệu (`bot.db`) không mất khi redeploy, thêm **Disk** trên Render
   mount vào 1 thư mục, rồi set biến `DB_PATH=/data/bot.db`.

(Nếu service hiện tại của bạn đang là kiểu Web Service từ trước, vẫn deploy
bình thường được — file vẫn tự mở 1 HTTP server nhỏ ở cổng `$PORT` để
healthcheck không báo lỗi, dù không còn dùng cho nghiệp vụ nữa.)

## Cách dùng sau khi bot chạy
- `/start` mở menu chính (dashboard 1 tin nhắn duy nhất, đầy đủ nút bấm).
- `/admin` (chỉ ADMIN_ID) mở bảng quản trị.
- Thêm bot vào kênh/group với quyền admin → bot tự lưu làm kênh xác minh bắt buộc.
- `/setlink4m <api_key>` — đổi api key link4m
- `/setreward <min> <max>` — đổi mức thưởng nhiệm vụ (đơn vị đồng)
- `/setrefbonus <số tiền>` — đổi thưởng giới thiệu
- `/setminwd <min_task> <min_ref>` — đổi mức rút tối thiểu

## Tính năng
- 💰 Thông tin tài khoản: số dư (tách nhiệm vụ/ref), coin, thống kê thu nhập
  hôm nay / 24h / 7 ngày / 30 ngày.
- 📝 Làm nhiệm vụ: tạo link4m gắn token riêng từng user, nút bấm, dùng 1 lần.
- 💸 Rút tiền: bắt liên kết ngân hàng `Ngân hàng | STK | Chủ TK`, min 10k
  (tiền nhiệm vụ) / 50k (tiền ref), admin duyệt/từ chối bằng nút (từ chối tự
  hoàn tiền).
- 👥 Mời bạn bè: link riêng, +1.000đ khi người được mời xác minh kênh thành công.
- 🔄 Đổi tool: dùng coin đổi tài khoản, **gói hết hàng tự động ẩn** khỏi user,
  admin có màn hình riêng "📦 Quản lý gói tool" để xem tồn kho và **nạp thêm
  tài khoản vào gói có sẵn** (không cần tạo gói mới mỗi lần).
- 🎁 Điểm danh hàng ngày: thưởng ngẫu nhiên 1 lần/ngày.
- 🏆 Bảng xếp hạng: top 10 user kiếm được nhiều nhất.
- ⚙️ Admin panel ẩn hoàn toàn với user thường: broadcast, duyệt rút tiền,
  quản lý tool, đổi cấu hình.

## Debug nếu "Không tạo được link nhiệm vụ"
Vào Render → tab **Logs**, tìm dòng `link4m API status=...` — in nguyên văn
phản hồi thật của link4m. Code đã kiểm tra chặt: chỉ chấp nhận URL thật sự
thuộc domain `link4m.co`/`link4m.com` và không được trùng/chứa link đích bên
trong (tránh bug hoàn thành nhiệm vụ mà không cần vượt quảng cáo nào).

## Lưu ý logic đã cài sẵn
- Mỗi nhiệm vụ có đúng 1 token dùng 1 lần, chỉ khớp đúng user tạo ra nó.
- Số dư tách "tiền nhiệm vụ" / "tiền giới thiệu" để áp đúng mức rút tối thiểu.
- Thưởng giới thiệu chỉ cộng khi người được mời xác minh kênh thành công lần đầu.
- Doanh thu thật của bạn đến từ link4m trả cho lượt hoàn thành thật — hãy set
  mức thưởng trả cho user (`/setreward`) thấp hơn mức bạn nhận từ link4m để
  không bị lỗ.
