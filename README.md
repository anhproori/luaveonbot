# Bot Telegram Kiếm Tiền Online (link4m) - bản có web xác nhận nhiệm vụ

## ⚠️ BẢO MẬT — làm ngay trước khi deploy
Token bot đã từng bị dán ra ngoài trong lịch sử chat. Nếu bạn chưa thu hồi:
1. Vào **@BotFather** → `/mybots` → chọn bot → **API Token** → **Revoke current token**.
2. Lấy token mới, set qua biến môi trường (không hardcode vào code).

## Kiến trúc mới (theo đúng yêu cầu)
- Khi user bấm "Làm nhiệm vụ", bot tạo 1 token riêng (32 ký tự) và tạo link đích dạng:
  `https://ten-app-cua-ban.onrender.com/<user_id>/<token>`
- Link đó được gửi qua API link4m để rút gọn.
- User vượt qua các bước quảng cáo trên link4m xong sẽ được đưa tới đúng URL
  `/<user_id>/<token>` ở trên — đây là 1 trang web thật (Flask) do chính bot
  chạy, có giao diện đẹp, kiểm tra:
  - Token có tồn tại không
  - Token đã dùng chưa (chỉ dùng được đúng 1 lần)
  - Token có đúng là của user đó không (không dùng ké được)
  → Nếu hợp lệ: cộng tiền + coin ngay trong DB, đồng thời tự động gửi/edit tin
  nhắn Telegram báo cho user biết đã cộng tiền (không cần user tự bấm gì thêm
  trong bot).

## Cài đặt local (test thử)
```bash
pip install -r requirements.txt
export BOT_TOKEN="token_moi_cua_ban"
export ADMIN_ID="8685327154"
export LINK4M_API_KEY="6a93e433c1e0cd622c1112a8"
export PORT=10000
python bot.py
```
Web sẽ chạy ở `http://localhost:10000`. Muốn test link4m thật, cần 1 domain
public trỏ tới máy bạn (vd dùng ngrok), rồi `/setweburl <domain_ngrok>` trong bot.

## Deploy trên Render — PHẢI dùng kiểu "Web Service"
Khác với bản trước, bản này **bắt buộc** deploy dạng **Web Service** (không
phải Background Worker nữa), vì cần 1 địa chỉ web public để link4m redirect
user về sau khi hoàn thành quảng cáo.

1. Đẩy các file `bot.py`, `requirements.txt`, `Procfile`, `runtime.txt` lên GitHub repo.
2. Trên Render: **New → Web Service**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
3. Tab **Environment**, thêm biến:
   - `BOT_TOKEN` = token mới
   - `ADMIN_ID` = 8685327154
   - `LINK4M_API_KEY` = api key link4m của bạn
4. Deploy. Render sẽ tự cấp cho bạn 1 domain dạng `https://ten-app.onrender.com`
   và bot **tự động nhận domain này** làm `web_base_url` (qua biến môi trường
   `RENDER_EXTERNAL_URL` mà Render tự set sẵn) — không cần làm gì thêm.
   Nếu vì lý do nào đó bot không tự nhận được, dùng lệnh:
   `/setweburl https://ten-app.onrender.com`
5. Nếu muốn dữ liệu (`bot.db`) không mất khi redeploy, thêm **Disk** trên Render
   mount vào 1 thư mục, rồi set biến `DB_PATH=/data/bot.db`.

## Cách dùng sau khi bot chạy
- `/start` mở menu chính. `/admin` (chỉ ADMIN_ID) mở bảng quản trị.
- Thêm bot vào kênh/group với quyền admin → bot tự lưu làm kênh xác minh bắt buộc.
- `/setlink4m <api_key>` — đổi api key link4m
- `/setreward <min> <max>` — đổi mức thưởng nhiệm vụ (đơn vị đồng)
- `/setrefbonus <số tiền>` — đổi thưởng giới thiệu
- `/setminwd <min_task> <min_ref>` — đổi mức rút tối thiểu
- `/setweburl <url>` — đổi thủ công địa chỉ web xác nhận nhiệm vụ
- Thêm gói tool để đổi coin: `/admin` → "➕ Thêm gói tool"
- Duyệt rút tiền: mỗi yêu cầu rút gửi kèm 2 nút Duyệt / Từ chối cho admin.

## Debug nếu "Không tạo được link nhiệm vụ"
Vào Render → tab **Logs**, tìm dòng `link4m API status=...` — dòng này in
nguyên văn phản hồi thật của link4m. Gửi dòng đó lại để chỉnh chính xác cách
đọc phản hồi trong hàm `create_link4m()`.

## Lưu ý logic đã cài sẵn
- Mỗi nhiệm vụ có đúng 1 token dùng 1 lần, chỉ khớp đúng user tạo ra nó.
- Trang web xác nhận có giao diện riêng cho 3 trường hợp: thành công / đã dùng
  rồi / không hợp lệ, kèm nút quay lại bot Telegram.
- Số dư tách "tiền nhiệm vụ" / "tiền giới thiệu" để áp đúng mức rút tối thiểu
  (10k / 50k theo yêu cầu ban đầu).
- Thưởng giới thiệu chỉ cộng khi người được mời xác minh kênh thành công lần đầu.
- Doanh thu thật của bạn đến từ link4m trả cho lượt hoàn thành thật — hãy set
  mức thưởng trả cho user (`/setreward`) thấp hơn mức bạn nhận từ link4m để
  không bị lỗ.
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
