# Bot Telegram Kiếm Tiền Online (link4m) - bản deep-link + nút bấm

## 🆕 Bản cập nhật MỚI NHẤT (API link4m gọi từ server + fix duyệt rút tiền + kênh xác minh nhiều kênh)
- **🔗 Tạo link nhiệm vụ lại gọi API link4m TỪ SERVER** (endpoint
  `api-shorten/v2`, đúng cấu trúc PHP link4m hướng dẫn), thay vì chỉ ghép
  chuỗi `/st?api=...` gắn thẳng vào nút như bản trước. Bot gọi API, đọc
  JSON trả về (`status`/`shortenedUrl`), và chỉ gắn nút bấm khi có link rút
  gọn hợp lệ thật sự từ link4m; nếu gọi lỗi, token nhiệm vụ vừa tạo được
  xoá luôn (không để lại token "mồ côi") và user thấy thông báo lỗi kèm nút
  "🔄 Thử lại".
  ⚠️ **Lưu ý:** bản trước đã đổi SANG cách ghép chuỗi chính vì link4m đứng
  sau Cloudflare, và gọi từ server có thể bị chặn 403 "Just a moment...".
  Nếu sau khi cập nhật bạn thấy nhiều nhiệm vụ báo lỗi "Không tạo được link
  nhiệm vụ", rất có thể đang gặp lại đúng vấn đề đó — xem log Render (dòng
  `link4m API status=...`) để biết chi tiết lỗi thật link4m trả về.
- **💸 Fix lỗi "duyệt rút tiền": trước đây màn hình "Yêu cầu rút tiền đang
  chờ" chỉ hiện DANH SÁCH CHỮ, không có nút bấm nào** — nút Duyệt/Từ chối
  chỉ tồn tại trên tin nhắn thông báo tức thời gửi cho admin lúc user vừa
  bấm rút, và tin đó dễ bị đè mất do nguyên tắc "1 tin nhắn duy nhất". Bản
  này gắn nút **✅ Duyệt** / **❌ Từ chối** ngay trên từng dòng của màn hình
  danh sách, nên admin luôn duyệt được dù có bỏ lỡ thông báo ban đầu.
  Bấm **❌ Từ chối** giờ hỏi thêm **lý do từ chối** (hoặc chọn "Từ chối
  không cần lý do") — lý do này được gửi rõ ràng cho user và lưu lại trong
  lịch sử rút tiền của admin.
- **📡 Kênh xác minh giờ áp dụng được NHIỀU kênh/group cùng lúc**, không
  còn giới hạn chỉ 1 kênh duy nhất như trước. Admin có thể bật/tắt từng
  kênh trong danh sách "kênh bot từng được thêm vào" làm điều kiện bắt
  buộc — user phải tham gia **toàn bộ** các kênh đang bật mới được coi là
  đã xác minh. Thêm bot làm admin vào 1 kênh/nhóm mới sẽ tự động **CỘNG
  THÊM** kênh đó vào danh sách bắt buộc (không còn thay thế kênh cũ như
  trước), và tự yêu cầu mọi người xác minh lại vì vừa có thêm điều kiện
  mới.

## 🆕 Bản cập nhật trước đó (kênh xác minh nâng cấp + lịch sử rút tiền + giờ VN + mini game Tài Xỉu)
- **📡 Kênh xác minh nâng cấp**: màn hình "Kênh xác minh" giờ hiện **danh
  sách toàn bộ kênh/nhóm bot từng được thêm vào** (kể cả kênh không phải
  kênh xác minh hiện tại), kèm trạng thái 🟢 Bật / 🔴 Tắt. Nút **"🔄 Kiểm
  tra lại"** cho bot tự hỏi lại Telegram xem còn ở trong từng kênh không để
  cập nhật đúng thực tế. Có thể bấm thẳng vào 1 kênh trong danh sách để đặt
  làm kênh xác minh mới. Nút **"🔁 Yêu cầu xác minh lại toàn bộ"** vẫn hoạt
  động y như trước: buộc **mọi người, kể cả admin**, phải xác minh lại.
- **💸 Lịch sử rút tiền**: user xem được 10 yêu cầu rút gần nhất của chính
  mình (nút "💸 Lịch sử rút tiền" ở menu chính). Admin có màn hình riêng
  **"📜 Lịch sử rút (tất cả)"** xem được toàn bộ lịch sử rút tiền của mọi
  user, có phân trang.
- **🎉 Thông báo rút tiền thành công** được làm đẹp, chuyên nghiệp hơn: có
  mã giao dịch, thời gian duyệt, khung viền rõ ràng.
- **🕒 Đổi toàn bộ mốc thời gian sang giờ Việt Nam (UTC+7)**: mọi thời gian
  lưu DB và hiển thị cho user/admin (lịch sử giao dịch, lịch sử rút tiền,
  thông tin user, thông báo cấm...) đều theo giờ VN thay vì UTC như trước.
- **📊 Admin - Thống kê nâng cao**: tổng số dư user đang giữ, số dư trung
  bình/user, tổng coin đang lưu hành, Tài Nguyên được đổi nhiều nhất, tổng
  coin đã đặt cược ở mini game Tài Xỉu.
- **🎲 Mini game cá cược Tài Xỉu (đổ 3 viên xúc xắc, cược bằng coin)**:
  - Gõ lệnh `/startgame` **trong group** có bot để mở 1 phiên mới, mỗi
    phiên có **20 giây** để đặt cược.
  - Cú pháp đặt cược: gõ thẳng trong nhóm `T <số coin>` (cửa **To**, tổng
    11-18) hoặc `X <số coin>` (cửa **Nhỏ**, tổng 3-10). Ví dụ: `T 100`.
  - Hết giờ, bot tự đổ 3 viên xúc xắc 🎲 (dùng tính năng xúc xắc gốc của
    Telegram — kết quả animation do server Telegram trả về thật, không ai
    can thiệp được), cộng dồn điểm và trả thưởng 1 ăn 1 cho bên thắng.
  - Tin nhắn phiên hiển thị đẹp: tổng số người & tổng coin ở mỗi cửa To/Nhỏ,
    lịch sử vài phiên gần nhất kèm mã phiên (`#12: 15🔴T`...).
  - Admin có màn hình **"🎲 Quản lý Tài Xỉu"**: xem phiên đang chạy, xem
    lịch sử phiên đã xong, và có thể **huỷ + hoàn tiền nguyên vẹn** 1 phiên
    nếu có sự cố kỹ thuật.
  - ⚠️ **Không có tính năng admin tự sửa kết quả xúc xắc.** Kết quả luôn
    lấy trực tiếp từ xúc xắc thật của Telegram để đảm bảo minh bạch và công
    bằng cho người chơi — đây là giới hạn được thiết kế có chủ đích, không
    phải thiếu sót.

## 🆕 Bản cập nhật trước đó (đổi tên Tài Nguyên + fix xác minh kênh + quản lý user)
- **Đổi tên "Tool" → "Tài Nguyên"**: toàn bộ nút bấm, tiêu đề, thông báo liên
  quan tới "gói tool" nay hiển thị là **"Tài Nguyên"** (nút menu chính, màn
  hình đổi, màn hình admin quản lý, thông báo tạo/nạp/nhận). Admin còn có
  thêm nút **✏️ Sửa giá** và **🗑 Xoá** ngay trên từng Tài Nguyên, không cần
  gõ lệnh.
- **Sửa gốc lỗi "admin bấm /start không bị hỏi xác minh kênh"**: nguyên nhân
  là cờ `verified` được cache theo từng user - nếu admin (hoặc bất kỳ ai)
  từng được đánh dấu đã xác minh từ trước (ví dụ từ kênh cũ), bot sẽ không
  hỏi lại dù kênh đã đổi. Bản này:
  - Tự động **yêu cầu xác minh lại toàn bộ user (kể cả admin)** ngay khi
    admin thêm bot vào một **kênh mới khác kênh đang cấu hình**.
  - Thêm màn hình **"📡 Kênh xác minh"** trong Admin Panel: xem kênh đang
    cấu hình, xem số user đã xác minh/tổng số user, nút **"🔁 Yêu cầu xác
    minh lại toàn bộ"** (dùng bất cứ lúc nào, không cần đổi kênh) và nút
    **"🗑 Gỡ bỏ kênh xác minh"**.
  - Thêm nút **"🔁 Yêu cầu xác minh lại"** ngay trong màn hình chi tiết
    từng user, để reset xác minh cho đúng 1 người thay vì toàn bộ.
- **Quản lý user chỉnh sửa được nhiều hơn**: ngoài cộng/trừ số dư và
  cấm/bỏ cấm sẵn có, giờ thêm **🪙 Điều chỉnh coin**, **🔁 Yêu cầu xác minh
  lại**, **🗑 Xoá liên kết ngân hàng** — tất cả bằng nút bấm ngay trong màn
  hình chi tiết user. Admin Panel cũng có thêm nút **"🔎 Tìm user theo ID"**
  bằng nút bấm (không bắt buộc gõ lệnh `/finduser` nữa).
- **Dọn nốt các chỗ còn gửi tin nhắn rời thay vì edit**: thông báo báo admin
  có yêu cầu rút tiền mới, thông báo cho user khi bị cấm/mở cấm, khi yêu
  cầu rút tiền được duyệt/từ chối, khi số dư/coin bị admin điều chỉnh, và
  thông báo thưởng giới thiệu — tất cả giờ đều **edit thẳng vào đúng 1 tin
  nhắn dashboard** của người nhận (nếu có) thay vì luôn tạo tin nhắn mới,
  đúng nguyên tắc "1 tin nhắn duy nhất" xuyên suốt toàn bộ bot.


## ⚠️ BẢO MẬT — làm ngay trước khi deploy
Nếu bạn chưa thu hồi token cũ (đã từng bị dán ra trong lịch sử chat):
1. Vào **@BotFather** → `/mybots` → chọn bot → **API Token** → **Revoke current token**.
2. Lấy token mới, set qua biến môi trường (không hardcode vào code).

Bản cập nhật này đã **xoá token/API key mặc định bị hardcode trong code** —
bot giờ **bắt buộc** phải có `BOT_TOKEN` và `ADMIN_ID` qua biến môi trường,
nếu thiếu bot sẽ báo lỗi và không khởi động (tránh lặp lại rủi ro rò rỉ token).

## 🆕 Bản cập nhật MỚI NHẤT (fix lỗi /start đứng + dọn tin nhắn rác)
- **Fix lỗi "/start bị đứng, không phản hồi" sau khi user xoá lịch sử chat**:
  nguyên nhân là hàm gửi/edit tin nhắn cũ chỉ bắt được 1 loại lỗi cụ thể
  (`BadRequest`) — khi Telegram trả về loại lỗi khác (mất mạng tạm thời, tin
  đã bị xoá hẳn do "Clear History", bot từng bị chặn rồi mở lại...) thì
  handler bị crash âm thầm, bot không trả lời gì cả. Bản này bắt **toàn bộ**
  lỗi Telegram (`TelegramError`) ở mọi nơi gửi/edit tin nhắn, luôn có
  phương án gửi tin mới thay thế nếu edit thất bại — bot không bao giờ
  "im lặng" nữa.
- **Thêm khoá (lock) riêng từng user**: chặn tình trạng bấm `/start` liên
  tục nhiều lần dồn dập khiến 2 tiến trình xử lý song song ghi đè lẫn nhau,
  sinh ra tin nhắn dashboard bị lệch/trùng.
- **Thêm error handler toàn cục**: nếu có lỗi bất ngờ nào khác xảy ra, bot
  sẽ luôn gửi 1 tin nhắn báo "có lỗi tạm thời, bấm /start lại" thay vì im
  lặng, đồng thời log lại để debug.
- **Dọn sạch tin nhắn rác ở TẤT CẢ các luồng nhập liệu còn sót**: liên kết
  ngân hàng, nhập số tiền rút tuỳ ý, broadcast, tạo/nạp gói tool, và cả các
  lệnh gõ tay của admin (`/setlink4m`, `/setreward`, `/finduser`,
  `/addbalance`...) — giờ đều xoá tin nhắn vừa nhập và **edit thẳng vào
  đúng 1 tin nhắn dashboard**, không còn gửi tin nhắn kết quả mới nữa.
- **`/admin` bắt buộc xác minh kênh y hệt user thường**: trước đây gõ thẳng
  lệnh `/admin` sẽ vào thẳng admin panel mà không cần qua bước xác minh
  kênh. Giờ dù là admin, gõ `/admin` hay `/start` đều phải xác nhận đã
  tham gia kênh trước, không có ngoại lệ.
- Màn hình yêu cầu tham gia kênh và màn hình xác minh thành công được làm
  đẹp hơn, có hiệu ứng "đang xác minh..." trước khi mở khoá dashboard.

## 🆕 Bản cập nhật trước đó (quản lý user + hệ thống cấm)
- **Tên bot trong dashboard giờ lấy tự động từ chính tên Telegram của bot**
  (`first_name` của bot, lấy qua `get_me()`) thay vì chữ cố định trong code —
  đổi tên bot trong BotFather là dashboard tự đổi theo, không cần sửa code.
- **👥 Quản lý user (toàn bộ bằng nút bấm)**: admin panel có thêm nút
  "👥 Quản lý user" → danh sách user (phân trang), bấm vào 1 user để xem chi
  tiết đầy đủ (số dư, coin, ref, ngân hàng, trạng thái) kèm 2 nút hành động
  ngay tại chỗ: **➕➖ Điều chỉnh số dư** và **🚫 Cấm / ✅ Bỏ cấm**.
- **Hệ thống cấm (ban) user**: admin bấm "🚫 Cấm user" → nhập lý do → chọn
  thời hạn (1/3/7/30 ngày hoặc vĩnh viễn) bằng nút. User bị cấm nhận ngay
  tin nhắn nêu rõ **lý do + thời hạn + thời điểm bị cấm**, và không dùng
  được bất kỳ chức năng nào của bot cho tới khi hết hạn hoặc được bỏ cấm
  (cấm có thời hạn sẽ tự động hết hiệu lực đúng giờ, không cần admin thao
  tác thủ công).
- Toàn bộ luồng nhập liệu mới (lý do cấm, số tiền điều chỉnh) đều theo đúng
  nguyên tắc **1 tin nhắn duy nhất**: tin nhập của admin bị xoá ngay, kết
  quả được edit thẳng vào tin nhắn dashboard đang có.

## 🆕 Bản cập nhật trước đó đã sửa/thêm gì
- **Sửa lỗi "làm nhiệm vụ" báo 403 "Just a moment..."**: nguyên nhân là bot
  cũ tự gọi API link4m **từ server** để lấy link rút gọn — server không phải
  trình duyệt thật nên bị Cloudflare (đứng trước link4m) chặn. Bản này bỏ
  hẳn việc gọi API từ server: bot chỉ **ghép chuỗi URL đúng định dạng**
  `https://link4m.co/st?api=<key>&url=<link_đích>` (y hệt cách link4m hướng
  dẫn dùng) rồi gắn thẳng vào nút bấm. Khi user bấm nút, chính trình duyệt/app
  Telegram của user mới là bên "truy cập" link — luôn được tính là truy cập
  thật, không còn bị chặn 403 nữa. (Nhờ vậy cũng bỏ được thư viện
  `cloudscraper` không cần thiết nữa.)
- **Hiệu ứng khi thao tác**: làm nhiệm vụ, điểm danh, rút tiền, đổi tool giờ
  có bước "đang xử lý..." trước khi hiện kết quả, thêm khung/emoji cho đẹp
  và chuyên nghiệp hơn.
- **Chuỗi điểm danh (streak)**: điểm danh liên tục nhiều ngày được cộng thêm
  % thưởng (tối đa +50%), mất chuỗi nếu bỏ lỡ 1 ngày.
- **📜 Lịch sử giao dịch**: user xem được 10 giao dịch gần nhất (nhiệm vụ,
  ref, điểm danh...).
- **Thống kê tài khoản** giờ hiện thêm số nhiệm vụ đã hoàn thành.
- **Admin panel** hiện thêm: user mới hôm nay, tổng tiền đã chi trả, tổng
  nhiệm vụ toàn hệ thống.
- **Lệnh admin mới**:
  - `/finduser <id>` — tra cứu chi tiết 1 user (số dư, ref, ngân hàng...)
  - `/addbalance <id> <số tiền>` — cộng/trừ số dư thủ công cho user (số tiền
    có thể âm để trừ), dùng khi cần hỗ trợ/đền bù thủ công.
  - Cả 2 việc trên giờ cũng làm được **hoàn toàn bằng nút bấm** qua
    "⚙️ Quản trị viên" → "👥 Quản lý user" (xem mục cập nhật mới nhất ở trên),
    không bắt buộc phải gõ lệnh nữa.

## Kiến trúc
- Khi user bấm "📝 Làm nhiệm vụ", bot tạo 1 token riêng (32 ký tự) và tạo link đích dạng:
  `t.me/<bot_username>?start=task_<token>`
- Bot gọi thẳng **API link4m TỪ SERVER** (`https://link4m.co/api-shorten/v2?api=<key>&url=<destination_url>`)
  để lấy link rút gọn thật, rồi gắn link đó vào **nút bấm** (không hiện text thô).
  User bấm nút, vượt qua các bước quảng cáo trên link4m, xong sẽ tự động
  được đưa quay lại app Telegram và mở bot với lệnh `/start task_<token>`.
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
- Thêm bot vào kênh/group với quyền admin → bot tự thêm kênh đó vào danh
  sách kênh xác minh bắt buộc (cộng thêm, có thể có nhiều kênh cùng lúc).
- `/setlink4m <api_key>` — đổi api key link4m
- `/setreward <min> <max>` — đổi mức thưởng nhiệm vụ (đơn vị đồng)
- `/setrefbonus <số tiền>` — đổi thưởng giới thiệu
- `/setminwd <min_task> <min_ref>` — đổi mức rút tối thiểu

## Tính năng
- 💰 Thông tin tài khoản: số dư (tách nhiệm vụ/ref), coin, thống kê thu nhập
  hôm nay / 24h / 7 ngày / 30 ngày.
- 📝 Làm nhiệm vụ: tạo link4m gắn token riêng từng user, nút bấm, dùng 1 lần.
- 💸 Rút tiền: bắt liên kết ngân hàng `Ngân hàng | STK | Chủ TK`, min 10k
  (tiền nhiệm vụ) / 50k (tiền ref), admin duyệt/từ chối bằng nút ngay trên
  màn hình danh sách "Yêu cầu đang chờ" (từ chối có thể kèm lý do, tự
  hoàn tiền cho user).
- 👥 Mời bạn bè: link riêng, +1.000đ khi người được mời xác minh kênh thành công.
- 🎁 Đổi Tài Nguyên: dùng coin đổi tài khoản, **hết hàng tự động ẩn** khỏi
  user, admin có màn hình riêng "🎁 Quản lý Tài Nguyên" để xem tồn kho,
  **nạp thêm tài khoản vào gói có sẵn**, **sửa giá** và **xoá** ngay bằng
  nút bấm (không cần tạo mới mỗi lần).
- 📡 Kênh xác minh: hỗ trợ **nhiều kênh/group cùng lúc** — user phải tham
  gia đủ toàn bộ kênh đang bật mới dùng được bot.
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
