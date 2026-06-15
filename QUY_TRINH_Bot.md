# 📋 Quy Trình Vận Hành RoKBot từ Bước B0 đến B6

Tài liệu này mô tả chi tiết các bước xử lý từ **B0 đến B6** trong mã nguồn của dự án **RoKBot**. Quy trình này được phân bổ trong các file chính:

1. [cli/commands/bot.py](file:///f:/lam_demo/rok/cli/commands/bot.py) (chạy đơn máy)
2. [cli/commands/fleet.py](file:///f:/lam_demo/rok/cli/commands/fleet.py) (chạy tuần tự/song song nhiều máy)
3. [core/bot/runtime.py](file:///f:/lam_demo/rok/core/bot/runtime.py) (vòng lặp chính của bot)
4. [core/bot/signals.py](file:///f:/lam_demo/rok/core/bot/signals.py) (dừng bot / pause-resume hotkey)
5. [core/bot/input_lock.py](file:///f:/lam_demo/rok/core/bot/input_lock.py) (khoá chuột Windows)

---

## 📋 Bảng tổng hợp các bước từ B0 đến B6

| Bước | Tên bước | Tệp tin & Dòng code liên quan | Chi tiết hành động chính |
| :--- | :--- | :--- | :--- |
| **B0** | **Khởi tạo & Nạp cấu hình** | [bot.py](file:///f:/lam_demo/rok/cli/commands/bot.py) · [fleet.py](file:///f:/lam_demo/rok/cli/commands/fleet.py) · [input_lock.py](file:///f:/lam_demo/rok/core/bot/input_lock.py) · [signals.py](file:///f:/lam_demo/rok/core/bot/signals.py) | **Khoá toàn bộ chuột PC** (nếu bật `enable_input_lock` trong `devices.yaml`) ngay khi bắt đầu. Đăng ký phím tắt **Ctrl+Space** (pause/resume). Đọc cấu hình `devices.yaml`. |
| **B1** | **Bật và Kiểm tra Bluestacks** | [bot.py](file:///f:/lam_demo/rok/cli/commands/bot.py) · [fleet.py](file:///f:/lam_demo/rok/cli/commands/fleet.py) | Phát hiện cổng của giả lập Bluestacks. Chưa bật → khởi động + chờ 10s. Đã bật → skip và chuyển B2. |
| **B2** | **Kiểm tra Bluestacks & Mở Game** | [runtime.py L728–L756](file:///f:/lam_demo/rok/core/bot/runtime.py#L728-L756) | Kiểm tra game. Game **chưa chạy** → `start_game()` + **chờ 25s**. Game **đã chạy** → đưa lên tiền cảnh + **chờ 5s**. Khóa nút BACK trong 2 phút. |
| **B3** | **Ấn màn hình & Khởi đầu** | [runtime.py](file:///f:/lam_demo/rok/core/bot/runtime.py) | Bấm giữa màn hình bỏ qua popup khởi động → chờ ngẫu nhiên 5–15s. Đưa game về WORLD. |
| **B4** | **Hành động & Farm chính** | [runtime.py L815–L925](file:///f:/lam_demo/rok/core/bot/runtime.py#L815-L925) | **Xáo trộn ngẫu nhiên** các hành động theo tỷ lệ: `getres` (100%), `farm` (100%), `alliance` (100% - riêng trợ giúp 100%, các việc khác 30%), và `vip` (30%). Chuyển tài khoản khi hàng đợi đầy. |
| **B5** | **Dọn dẹp & Giữ Bluestacks** | [runtime.py L59–L70](file:///f:/lam_demo/rok/core/bot/runtime.py#L59-L70) | Dọn dẹp ảnh captures debug cũ, mở khóa chuột PC. **Giữ nguyên trạng thái Bluestacks** (không tắt). |
| **B6** | **Chờ và chạy lại bot** | [bot.py L159–L169](file:///f:/lam_demo/rok/cli/commands/bot.py#L159-L169) | Chờ khoảng 2 giờ (120 phút +- 10 phút ngẫu nhiên) trước khi lặp lại chu trình bot từ đầu. |

---

## 🔍 Chi tiết kỹ thuật từng bước

### 🔹 B0 — Phím tắt Ctrl+Space (Pause / Resume)

- **Vị trí:** [signals.py](file:///f:/lam_demo/rok/core/bot/signals.py) — `install_pause_hotkey()`, `wait_if_paused()`.
- Gọi `install_pause_hotkey()` 1 lần khi bot khởi động.
- Dùng Windows API `RegisterHotKey(Ctrl+Space)` qua `ctypes` (không cần cài thêm thư viện).
- **Nhấn Ctrl+Space lần 1** → in banner `⏸ BOT ĐÃ TẠM DỪNG`; giải phóng khóa chuột PC ngay lập tức.
- **Nhấn Ctrl+Space lần 2** → in banner `▶ BOT ĐÃ TIẾP TỤC`; khóa lại chuột PC và chạy tiếp tục.

### 🔹 Di chuyển chuột mượt mà (Human-like Mouse Movement)

- **Vị trí:** [input_lock.py](file:///f:/lam_demo/rok/core/bot/input_lock.py) — `move_lock_position_smooth()` · [device.py](file:///f:/lam_demo/rok/core/device.py) — `_physical_click()`, `_physical_long_click()`, `_physical_swipe()`.
- Sử dụng thuật toán nội suy phi tuyến tính **Quadratic Ease-Out** giúp con trỏ chuột tăng tốc nhẹ và giảm tốc mềm mại khi chuẩn bị dừng tại đích.
- Quãng đường di chuyển được chia nhỏ thành nhiều bước cách nhau 10ms, trượt mượt mà trong thời gian 150ms.
- Sau khi click xong, chuột di chuyển mượt mà quay trở lại vị trí nghỉ ban đầu (`_IDLE_COORD`).

### 🔹 Tọa độ bấm Gaussian (Gaussian Click Coordinates)

- **Vị trí:** [mouse.py](file:///f:/lam_demo/rok/core/mouse.py) — `get_gaussian_click_coords()` · [device.py](file:///f:/lam_demo/rok/core/device.py) — `tap()`, `long_tap()`.
- Tọa độ bấm được lệch ngẫu nhiên quanh tâm mục tiêu bằng phân phối chuẩn Gaussian với `sigma=5` (bell curve), tránh click lặp lại cùng một điểm tuyệt đối.

### 🔹 B2 — Thời gian chờ khởi động game

- **Vị trí:** `_run_body()` tại [runtime.py L728–L756](file:///f:/lam_demo/rok/core/bot/runtime.py#L728-L756).
- Game **chưa chạy** → `device.start_game()` + **chờ 25s**.
- Game **đã chạy** → bring-to-front + **chờ 5s**.
- Khóa phím BACK trong 2 phút (`device._back_locked_until = time.monotonic() + 120.0`).

### 🔹 B3 — Đưa game về WORLD & Khởi đầu

- **Vị trí:** [runtime.py](file:///f:/lam_demo/rok/core/bot/runtime.py).
- Bấm vào tâm màn hình `(1200, 540)` để bỏ qua các popup mở đầu, chờ ngẫu nhiên từ 5 đến 15 giây, sau đó gọi `_prepare_world_only(device)` để chuẩn bị đưa game về giao diện WORLD.

### 🔹 B4 — Khởi tạo chu trình ngẫu nhiên khi vào Acc (Randomized Workflows)

- **Vị trí:** [runtime.py L775–L779](file:///f:/lam_demo/rok/core/bot/runtime.py#L775-L779), [runtime.py L836–L840](file:///f:/lam_demo/rok/core/bot/runtime.py#L836-L840) và [runtime.py L874–L897](file:///f:/lam_demo/rok/core/bot/runtime.py#L874-L897).
- Mỗi lần khởi động bot hoặc chuyển tài khoản mới, danh sách hành động khởi động được xây dựng và **xáo trộn ngẫu nhiên (shuffle)** dựa trên tỷ lệ cấu hình:
  - **`getres`** (Tỷ lệ **100%**): Thu thập tài nguyên nổi trong thành phố (City).
  - **`farm`** (Tỷ lệ **100%**): Gửi quân đi farm bên ngoài bản đồ thế giới (World).
  - **`alliance`** (Tỷ lệ **100%**): Thực hiện các hành động liên minh. Trong đó hành động **Trợ giúp bắt tay (Alliance Help)** chạy với tỷ lệ **100%**, các hành động phụ khác (nhận quà liên minh, thu hoạch tài nguyên lãnh thổ, đóng góp công nghệ) chạy với tỷ lệ **30%**.
  - **`vip`** (Tỷ lệ **30%**): Vào City, nhận điểm VIP và rương miễn phí hàng ngày.

### 🔹 B4 — Đọc số lượng slot thực tế (huy hiệu n/N)

- **Vị trí:** [runtime.py L792–L800](file:///f:/lam_demo/rok/core/bot/runtime.py#L792-L800) — `_read_initial_slot_badge_with_retries(device)`.
- Chụp ảnh OCR huy hiệu `n/N` trên góc trái bản đồ thế giới để lấy số quân đang di chuyển và sức chứa hàng chờ tối đa thực tế của tài khoản. Thử tối đa 4 lần.

### 🔹 B4 — Xoay vòng tài nguyên (cycle mode)

- **Vị trí:** [runtime.py L84–L87](file:///f:/lam_demo/rok/core/bot/runtime.py#L84-L87).
- Khi chọn chế độ `resource: cycle`, bot sẽ shuffle ngẫu nhiên danh sách `[corn, stone, gold, wood]` ở 4 lượt đầu, sau đó chọn ngẫu nhiên 1 trong 4 tài nguyên ở các lượt tiếp theo.

### 🔹 B4 — Chuẩn hoá camera (City-World Toggle)

- **Vị trí:** [runtime.py L906–L920](file:///f:/lam_demo/rok/core/bot/runtime.py#L906-L920) — `_go_home_then_world()`.
- Tránh camera bám đuôi quân đi farm. Tự động vào City rồi quay lại World để reset góc nhìn về vị trí trung tâm thành phố. Xác suất chạy và chế độ bật/tắt được điều chỉnh qua `devices.yaml`.

### 🔹 B4 — Khoá nút BACK (`device._back_locked_until`)

- **Vị trí:** [device.py L341–L350](file:///f:/lam_demo/rok/core/device.py#L341-L350).
- Tránh bấm BACK làm tắt ứng dụng game khi đang trong màn hình tải/chuyển tiếp. Bị khóa tự động trong vòng 2 phút đầu sau khi mở game hoặc chuyển tài khoản.

### 🔹 B4 — Chống kẹt (Anti-stuck)

- **Hard-ceiling:** Reset về trạng thái `UNKNOWN` nếu gặp kẹt liên tục 6 vòng lặp.
- **Ping-pong detection:** Reset nếu phát hiện 6 trạng thái xen kẽ lặp đi lặp lại dạng `A B A B A B`.

### 🔹 B5 — Dọn dẹp & Kết thúc

- **Vị trí:** [runtime.py L59–L70](file:///f:/lam_demo/rok/core/bot/runtime.py#L59-L70).
- Xóa các ảnh captures PNG debug thành công để tiết kiệm bộ nhớ, chỉ giữ lại ảnh lỗi. Mở khóa chuột PC.

### 🔹 B6 — Chờ và chạy lại bot

- **Vị trí:** [bot.py L159–L169](file:///f:/lam_demo/rok/cli/commands/bot.py#L159-L169).
- Sau khi hoàn thành lượt chạy, bot sẽ ngủ chờ ngẫu nhiên khoảng 2 giờ (120 phút +- 10 phút lệch chuẩn) trước khi lặp lại từ Bước B1.

### 🔹 Khôi phục kết nối khi Bluestacks bị đóng giữa chừng

- **Vị trí:** [runtime.py L566–L618](file:///f:/lam_demo/rok/core/bot/runtime.py#L566-L618).
- Tự động bật lại giả lập, kết nối lại ADB, khởi chạy game và phục hồi luồng hoạt động mà không làm dừng chương trình chính.

---

## ⌨️ Bảng Phím Tắt Điều Khiển

| Phím tắt | Phạm vi | Chức năng |
| :--- | :--- | :--- |
| **Ctrl+Space** | Toàn hệ thống | Tạm dừng (Pause) / Tiếp tục (Resume) bot. Giải phóng chuột. |
| **Ctrl+C** | Terminal | Dừng bot nhẹ nhàng (Graceful Stop). Bấm lần 2 để thoát ngay. |
| File `STOP.flag` | Thư mục gốc | Tạo file này để dừng tất cả thiết bị trong hệ thống fleet. |
| File `STOP_<serial>.flag` | Thư mục gốc | Tạo file này để dừng riêng thiết bị có serial tương ứng. |

---

## 🗂️ Cấu Hình `devices.yaml` Tham Khảo

```yaml
defaults:
  resource: cycle          # barb / corn / wood / stone / gold / cycle (xoay vòng)
  target_level: 5          # Cấp độ tài nguyên cần tìm kiếm
  max_slots: 4             # Sức chứa hàng chờ quân đội
  skip_level_adjust: false # Giữ nguyên slider tìm kiếm của game
  turn_wait_min: 60        # Thời gian ngủ (phút) nếu hàng chờ đầy
  control_mode: adb        # adb hoặc physical_mouse (chiếm chuột thật PC)
  enable_input_lock: true  # Khóa chuột PC vật lý khi bot hoạt động
  enable_vip_claim: true   # Tự động nhận VIP hàng ngày
```

> [!WARNING]
> Cấu hình `control_mode: physical_mouse` chỉ hoạt động ổn định khi chạy **đơn máy** (`bot`) hoặc chạy **tuần tự** (`fleet --sequential`). Không sử dụng khi chạy song song vì chuột sẽ bị tranh chấp giữa các cửa sổ giả lập.
