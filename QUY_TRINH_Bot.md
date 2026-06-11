# Quy trình vận hành RoKBot từ Bước B0 đến B6

Tài liệu này mô tả chi tiết các bước xử lý từ **B0 đến B6** trong mã nguồn của dự án **RoKBot**. Quy trình này được phân bổ trong các file chính:

1. `cli/commands/bot.py` (chạy đơn máy)
2. `cli/commands/fleet.py` (chạy tuần tự/song song nhiều máy)
3. `core/bot/runtime.py` (vòng lặp chính của bot)
4. `core/bot/signals.py` (dừng bot / pause-resume hotkey)
5. `core/bot/input_lock.py` (khoá chuột Windows)

---

## 📋 Bảng tổng hợp các bước từ B0 đến B6

| Bước       | Tên bước                               | Tệp tin & Dòng code liên quan                                                                                                                                                                                                                                                                                                                                                             | Chi tiết hành động chính                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| :----------- | :---------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B0** | **Khởi tạo & Nạp cấu hình**    | [bot.py L37–L99](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/bot.py#L37-L99) · [fleet.py L25–L48](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L25-L48) · [input_lock.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/input_lock.py) · [signals.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/signals.py) | **Khoá toàn bộ chuột** (nếu bật `enable_input_lock` trong `devices.yaml`, kết hợp `BlockInput` và giới hạn `ClipCursor` 1x1 qua luồng chạy ngầm, không yêu cầu quyền Admin) ngay khi bot bắt đầu — người dùng không thể di chuột làm nhiễu. Tự động mở khoá khi bot kết thúc (kể cả khi crash). Đăng ký phím tắt **Ctrl+Space** (pause/resume). Đọc cấu hình `devices.yaml`, thiết lập các tham số tài nguyên, cấp độ farm mục tiêu. Nếu thiếu/trống `devices`, bot tự quét Bluestacks lấy 4 máy làm mặc định. Ưu tiên: **CLI > devices.yaml > mặc định hệ thống**. |
| **B1** | **Bật và Kiểm tra Bluestacks**   | [bot.py L101–L128](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/bot.py#L101-L128) · [fleet.py L96–L115](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L96-L115)                                                                                                                                                                               | Phát hiện cổng của giả lập Bluestacks. Chưa bật → khởi động + chờ 10s. Đã bật → skip và chuyển B2. Không phải Bluestacks → bỏ qua.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **B2** | **Kiểm tra Bluestacks & Mở Game** | [runtime.py L416–L468](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L416-L468)                                                                                                                                                                                                                                                                                     | Kiểm tra giả lập + game cùng lúc. Game**chưa chạy** → `start_game()` + **chờ 25s**. Game **đã chạy** → bring-to-front (`monkey`) + **chờ 5s**. Sau đó khoá BACK 2 phút (`device._back_locked_until`).                                                                                                                                                                                                                                                                                                                                                              |
| **B3** | **Ấn màn hình & Khởi đầu**    | [runtime.py L470–L481](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L470-L481)                                                                                                                                                                                                                                                                                     | tap giữa `(1200, 540)` bỏ qua pop-up → chờ ngẫu nhiên từ `delay_after_popup_min` đến `delay_after_popup_max` (mặc định **5–15s**) → gọi `_initial_navigate_to_world()` đưa game về WORLD.                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **B4** | **Vòng lặp Farm chính**          | [runtime.py L551–L955](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L551-L955)                                                                                                                                                                                                                                                                                     | Vòng lặp chính: nhận diện state → gửi quân → xoay vòng tài nguyên ngẫu nhiên (4 lượt đầu shuffle [ngô, đá, vàng, gỗ], sau đó random 1 trong 4). Sau mỗi lần gửi quân thành công, kích hoạt ngẫu nhiên cơ chế vào city rồi về world (camera normalization) dựa trên tỉ lệ thiết lập để tránh bám đuôi camera quân đi farm, sau đó chờ ngẫu nhiên từ `delay_after_dispatch_min` đến `delay_after_dispatch_max` (mặc định **10–20s**). Đọc huy hiệu n/N ngay từ đầu để biết slot thực tế. Khi hàng đợi đầy → chuyển acc, khoá BACK 2 phút. Chống kẹt: hard-ceiling 6 vòng + ping-pong A↔B. Khi handler crash: bấm BACK (nếu không trong vùng khoá), chờ 2s, tiếp tục. |
| **B5** | **Dọn dẹp & Giữ Bluestacks**     | [runtime.py L375–L389](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L375-L389) · [fleet.py L251–L258](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L251-L258)                                                                                                                                                                         | Sau khi bot kết thúc (thành công hoặc lỗi): dọn ảnh captures, mở khoá chuột.**Giữ nguyên Bluestacks** (không tắt).                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

---

## 🔍 Chi tiết kỹ thuật từng bước

### 🔹 B0 — Phím tắt Ctrl+Space (Pause / Resume)

- **Vị trí:** [signals.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/signals.py) — `install_pause_hotkey()`, `wait_if_paused()`.
- Gọi `install_pause_hotkey()` 1 lần khi bot khởi động (cả `bot` đơn máy lẫn `fleet --sequential`).
- Dùng Windows API `RegisterHotKey(Ctrl+Space)` qua `ctypes` — **không cần cài thêm thư viện**.
- **Nhấn Ctrl+Space lần 1** → banner `⏸ BOT ĐÃ TẠM DỪNG` in ra console; các khoá chuột (`BlockInput` và `ClipCursor`) được giải phóng hoàn toàn **ngay lập tức** từ luồng phím tắt để người dùng sử dụng chuột bình thường; luồng chính của bot sẽ dừng lại ở đầu vòng lặp hoặc bước chờ tiếp theo.
- **Nhấn Ctrl+Space lần 2** → banner `▶ BOT ĐÃ TIẾP TỤC`; kích hoạt lại hệ thống khóa chuột; bot chạy tiếp từ điểm đã dừng.

### 🔹 Di chuyển chuột mượt mà (Human-like Mouse Movement)

- **Vị trí:** [input_lock.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/input_lock.py) — `move_lock_position_smooth()` · [device.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/device.py) — `_physical_click()`, `_physical_long_click()`, `_physical_swipe()`.
- Để tránh việc con trỏ chuột nhảy dịch chuyển tức thời (teleport) gây nghi ngờ hoặc không tự nhiên khi di chuyển đến tọa độ click/swipe, bot tích hợp cơ chế di chuyển mượt mà:
  - Sử dụng hàm nội suy phi tuyến tính **Quadratic Ease-Out** giúp con trỏ chuột tăng tốc nhẹ và giảm tốc mềm mại khi chuẩn bị dừng tại đích.
  - Quãng đường từ vị trí hiện tại đến vị trí click/swipe được chia nhỏ thành nhiều bước cách nhau 10ms, trượt mượt mà trong thời gian 150ms.
  - Sau khi click hoặc vuốt xong, chuột cũng di chuyển mượt mà quay trở lại vị trí nghỉ ban đầu (`_IDLE_COORD`).

### 🔹 Tọa độ bấm Gaussian (Gaussian Click Coordinates)

- **Vị trí:** [mouse.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/mouse.py) — `get_gaussian_click_coords()` · [device.py](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/device.py) — `tap()`, `long_tap()`.
- Trước khi thực hiện thao tác bấm, bot không dùng nguyên tọa độ tâm tuyệt đối mà lấy mẫu tọa độ mới quanh điểm gốc bằng phân phối chuẩn Gaussian.
- Mặc định `sigma=5`: phần lớn lượt bấm nằm rất gần tọa độ gốc, các điểm lệch xa hơn xuất hiện thưa dần theo dạng bell curve.
- Cơ chế này chỉ thay đổi **tọa độ được bấm** cho `tap()` và `long_tap()`. Nó không thay đổi thuật toán di chuyển chuột mượt, và không áp dụng cho `swipe()`.

### 🔹 B2 — Thời gian chờ khởi động game

- **Vị trí:** `_run_body()` tại [runtime.py L416–L468](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L416-L468) và `_initial_navigate_to_world()` tại [runtime.py L113–L204](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L113-L204).
- Game **chưa chạy** → `device.start_game()` + **chờ 25s**.
- Game **đã chạy** → `monkey` bring-to-front + **chờ 5s**.
- Sau cả 2 trường hợp: khoá BACK 2 phút (`device._back_locked_until = time.monotonic() + 120.0`).

### 🔹 B4 — Đọc số lượng slot thực tế (huy hiệu n/N)

- **Vị trí:** [runtime.py L492–L514](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L492-L514) — `_read_initial_slot_badge_with_retries(device)`.
- Ngay sau B3, bot chụp màn hình OCR huy hiệu `n/N` trên bản đồ thế giới để biết:
  - **n** = số quân đã gửi đi (dispatched_count thực tế).
  - **N** = MAX_SLOTS thực của tài khoản (phụ thuộc VIP / tài năng).
- Thử **tối đa 4 lần**, chờ 2s mỗi lần thử. Nếu vẫn không đọc được → coi như `0/MAX_SLOTS`.
- Tương tự: đọc lại huy hiệu sau mỗi lần chuyển tài khoản.

### 🔹 B4 — Xoay vòng tài nguyên (cycle mode)

- **Vị trí:** [runtime.py L813–L833](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L813-L833).
- Khi `resource: cycle` trong `devices.yaml`:
  - Khởi tạo 1 lần: shuffle ngẫu nhiên danh sách `[corn, stone, gold, wood]` → lưu vào `config.CYCLE_RESOURCES`.
  - Lượt 1→4: dùng đúng thứ tự trong danh sách đã shuffle.
  - Lượt 5+: random 1 trong 4 loại tài nguyên.
  - Reset (`config.CYCLE_RESOURCES = None`) khi chuyển tài khoản.

### 🔹 B4 — Chuẩn hoá camera (City-World Toggle)

- **Vị trí:** [runtime.py L909–L920](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L909-L920) — `_go_home_then_world()`.
- Sau khi gửi quân thành công, game mặc định bám đuôi đạo quân di chuyển (camera chasing).
- Để khắc phục và đưa màn hình tự động căn giữa lại thành phố chính, bot tích hợp cơ chế: vào CITY rồi quay lại WORLD.
- Cơ chế này có thể bật/tắt và chạy ngẫu nhiên tùy chỉnh qua `devices.yaml`:
  - `enable_city_world_toggle`: Bật (`true`) hoặc Tắt (`false`) cơ chế này.
  - `city_world_toggle_probability`: Xác suất kích hoạt sau mỗi lần gửi quân (từ `0.0` đến `1.0`, ví dụ `0.5` tương đương 50% cơ hội thực hiện).

### 🔹 B4 — Khoá nút BACK (`device._back_locked_until`)

- **Vị trí:** [device.py L341–L350](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/device.py#L341-L350) — `def key()`.
- Bất kỳ lệnh `device.key("BACK")` nào cũng bị **tự động chặn** nếu `time.monotonic() < device._back_locked_until`.
- Khoá BACK được đặt trong 2 tình huống:
  1. **Ngay sau bật game** (B2): khoá 2 phút.
  2. **Ngay sau chuyển tài khoản**: khoá 2 phút.
- Khi handler crash trong thời gian khoá: bot log cảnh báo và bỏ qua BACK, chờ 2s rồi tiếp tục.

### 🔹 B4 — Chống kẹt (Anti-stuck)

- **Hard-ceiling**: nếu `stuck_count >= 6` → reset state về `UNKNOWN` để handler unknown xử lý.
- **Ping-pong detection**: nếu 6 state liên tiếp là `A B A B A B` → ép reset về `UNKNOWN`.
- **TILE_INFO → UNKNOWN pattern**: OCR lại huy hiệu, đồng bộ `dispatched_count`, nếu đầy thì chuyển acc.

### 🔹 B5 — Dọn dẹp & Kết thúc

- Hàm `_cleanup_captures()` xoá toàn bộ ảnh PNG trong thư mục `captures/` **ngoại trừ** file có tên chứa `FAILED`, `UNKNOWN`, `FIRST_WORLD` (giữ lại để debug).
- Khi chạy fleet tuần tự, sau khi hoàn thành một lượt chạy cho tất cả các thiết bị cấu hình trong `devices.yaml`, bot sẽ tiến hành dọn dẹp, mở khóa chuột và tự động thoát chương trình.

### 🔹 Khôi phục kết nối khi Bluestacks bị đóng giữa chừng

- **Vị trí:** [runtime.py L566–L618](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L566-L618) — `except Exception` khi `device.snapshot()` thất bại.
- Bot tự phát hiện Bluestacks → bật lại → kết nối lại ADB (khởi tạo lại `Android()`) → kiểm tra game → khởi chạy nếu cần → khôi phục hoạt động mà **không dừng chương trình**.

---

## ⌨️ Phím tắt

| Phím tắt                  | Chức năng                                                                           |
| :-------------------------- | :------------------------------------------------------------------------------------ |
| **Ctrl+Space**        | Toggle**Tạm dừng / Tiếp tục** bot. Khi paused: chuột được tự do dùng. |
| **Ctrl+C**            | Dừng bot nhẹ nhàng (graceful stop). Ctrl+C lần 2 trong 3s → thoát ngay.         |
| File `STOP.flag`          | Tạo file này trong thư mục gốc → dừng tất cả máy trong fleet.               |
| File `STOP_<serial>.flag` | Tạo file này → dừng riêng 1 máy trong fleet.                                    |

---

## 🗂️ Cấu hình `devices.yaml`

```yaml
defaults:
  resource: cycle          # barb / corn / wood / stone / gold / cycle
  target_level: 5
  max_slots: 4
  skip_level_adjust: false
  turn_wait_min: 60
  control_mode: adb        # adb (mặc định) hoặc physical_mouse
  enable_input_lock: true  # Bật/tắt chế độ khóa chuột/phím PC khi chạy bot (nếu dùng phone thật nên tắt đi)

  # Cấu hình thời gian chờ:
  delay_after_popup_min: 5     # Thời gian chờ tối thiểu sau khi tắt popup (giây)
  delay_after_popup_max: 15    # Thời gian chờ tối đa sau khi tắt popup (giây)
  delay_after_dispatch_min: 10 # Thời gian chờ tối thiểu sau khi gửi quân (giây)
  delay_after_dispatch_max: 20 # Thời gian chờ tối đa sau khi gửi quân (giây)
  enable_city_world_toggle: true       # Bật/tắt cơ chế vào city rồi lại về world sau khi gửi quân (tránh bám đuôi camera)
  city_world_toggle_probability: 0.5    # Xác suất thực hiện cơ chế vào city rồi về world (0.0 đến 1.0)

# Danh sách thiết bị. 
# Nếu block 'devices' này trống hoặc bị comment lại, bot sẽ tự động quét
# bluestacks.conf và kết nối 4 máy ảo đang chạy trên Bluestacks với tên
# được đặt theo tên hiển thị (ví dụ: 1, 2, 3, 4...).
#
# devices:
#   - name: phone-1
#     serial: 127.0.0.1:5555
#   - name: phone-2
#     serial: 127.0.0.1:5615
#   - name: phone-3
#     serial: 127.0.0.1:5625
#   - name: phone-4
#     serial: 127.0.0.1:5635
```

> **Lưu ý:** `control_mode: physical_mouse` chỉ dùng được khi chạy **đơn máy** (`bot`) hoặc **tuần tự** (`fleet --sequential`). Không thể chạy song song vì chuột sẽ bị nhảy loạn giữa các cửa sổ.

---

## ▶️ Lệnh chạy

```bash
# Đơn máy (hỏi tương tác)
python main.py bot

# Đơn máy (chỉ định serial)
python main.py bot --serial 127.0.0.1:5615

# Fleet song song (tất cả máy trong devices.yaml)
python main.py fleet

# Fleet tuần tự (1 máy tại 1 thời điểm, hỗ trợ physical_mouse + Ctrl+Space pause)
python main.py fleet --sequential
```
