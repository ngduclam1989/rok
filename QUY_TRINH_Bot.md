# Quy trình vận hành RoKBot từ Bước B0 đến B6

Tài liệu này mô tả chi tiết các bước xử lý từ **B0 đến B6** trong mã nguồn của dự án **RoKBot**. Quy trình này được phân bổ trong các file chính:

1. `cli/commands/bot.py` (chạy đơn máy)
2. `cli/commands/fleet.py` (chạy tuần tự/song song nhiều máy)
3. `core/bot/runtime.py` (vòng lặp chính của bot)

---

## 📋 Bảng tổng hợp các bước từ B0 đến B6

| Bước | Tên bước | Tệp tin & Dòng code liên quan | Chi tiết hành động chính |
| :--- | :--- | :--- | :--- |
| **B0** | **Khởi tạo & Nạp cấu hình** | [bot.py L37–L99](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/bot.py#L37-L99) · [fleet.py L25–L45](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L25-L45) | Đọc cấu hình `devices.yaml`, thiết lập các tham số tài nguyên, cấp độ farm mục tiêu, giới hạn hàng chờ (slots). Ưu tiên: **CLI > devices.yaml > mặc định hệ thống**. |
| **B1** | **Bật và Kiểm tra Bluestacks** | [bot.py L101–L128](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/bot.py#L101-L128) · [fleet.py L96–L109](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L96-L109) | Phát hiện cổng của giả lập Bluestacks. Chưa bật → khởi động + chờ 10s. Đã bật → skip và chuyển B2. Không phải Bluestacks → bỏ qua. |
| **B2** | **Kiểm tra Bluestacks & Mở Game** | [runtime.py L344–L408](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L344-L408) | Kiểm tra giả lập + game cùng lúc. Game chưa chạy → `start_game()` + **chờ 25s**. Game đã chạy → bring-to-front + **chờ 5s**. **Tuyệt đối KHÔNG bấm BACK** khi UNKNOWN (xem flag `_back_safe` ở B4). |
| **B3** | **Ấn màn hình & Khởi đầu** | [runtime.py L393–L410](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L393-L410) | Chụp màn hình, tap giữa (1200, 540) bỏ qua pop-up, chờ 5s, gọi `_initial_navigate_to_world` để đưa game về WORLD. |
| **B4** | **Vòng lặp Farm chính** | [runtime.py L485–L840](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L485-L840) | Vòng lặp chính: nhận diện state, gửi quân, xoay vòng tài nguyên `cycle` (1 ngô→1 đá→1 vàng→2 gỗ). Chống kẹt: hard-ceiling 6 vòng + ping-pong A↔B. Crash check mỗi 5 vòng. **Flag `_back_safe`**: `False` lúc khởi động, bật `True` khi lần đầu xác nhận WORLD, reset `False` sau mỗi lần chuyển acc. Khi handler crash: **chỉ BACK nếu `_back_safe=True`**. |
| **B5** | **Dọn dẹp & Giữ Bluestacks** | [bot.py L135–L146](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/bot.py#L135-L146) · [fleet.py L131–L141](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L131-L141) | Sau khi bot kết thúc (thành công hoặc lỗi): `_return_to_world`, dọn ảnh captures, chờ 5s. **Giữ nguyên Bluestacks** (không tắt). |
| **B6** | **Quét tuần tự & Chờ chu kỳ** | [fleet.py L43–L157](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L43-L157) | **Chu kỳ đầu (lúc khởi động)**: thứ tự mặc định `1→2→3→4`. **Từ chu kỳ 2 trở đi**: máy 1 cố định đứng đầu, các máy 2–N xáo trộn ngẫu nhiên. **Sau khi quét xong TOÀN BỘ chu kỳ** (hết tất cả thiết bị): chờ ngẫu nhiên **2h–2h10' (7200–7800s)** rồi bắt đầu chu kỳ mới. |

---

## 🔍 Chi tiết kỹ thuật từng bước

### 🔹 B2 — Thời gian chờ khởi động game

- **Vị trí:** `run()` tại [runtime.py L374–L392](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L374-L392) và `_initial_navigate_to_world()` tại [runtime.py L139–L150](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L139-L150).
- Game **chưa chạy** → `device.start_game()` + **chờ 25s**.
- Game **đã chạy** → `monkey` bring-to-front + **chờ 5s**.

### 🔹 B4 — Flag `_back_safe` (Guard BACK)

- **Vị trí:** [runtime.py L421, L591–L593, L643, L722, L769, L815](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L421).

```
Khởi động bot
    │  _back_safe = False  ← cấm BACK
    ▼
Vòng lặp chính — lần đầu phát hiện WORLD
    │  _back_safe = True   ← mở khoá BACK
    ▼
Hàng chờ đầy → chuyển tài khoản + chờ 10s
    │  _back_safe = False  ← cấm BACK lại
    ▼
Vòng lặp tiếp tục — phát hiện WORLD lại
       _back_safe = True   ← mở khoá lại
```

**Quy tắc:** Trong `except Exception` khi handler crash — chỉ gửi phím `BACK` nếu `_back_safe = True`.

### 🔹 B6 — Cơ chế `is_first_cycle`

- **Vị trí:** [fleet.py L46–L80](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/cli/commands/fleet.py#L46-L80).
- `is_first_cycle = True` được khai báo 1 lần trước `while True`.
- **Chu kỳ 1**: `ordered_members = list(members_cfg)` (thứ tự gốc), sau đó `is_first_cycle = False`.
- **Chu kỳ 2+**: `primary = members_cfg[:1]` + `shuffle(members_cfg[1:])`.
- **Sau vòng `for`**: chờ `random.randint(7200, 7800)` giây, log dạng: `[B6] Đã quét xong 4 thiết bị. Chờ 2h03' trước chu kỳ tiếp theo...`

### 🔹 Khôi phục kết nối khi Bluestacks bị đóng giữa chừng

- **Vị trí:** [runtime.py L511–L560](file:///e:/bot%20rok/automation-farm-rise-of-kingdom/core/bot/runtime.py#L511-L560) — `except Exception` khi `device.snapshot()` thất bại.
- Bot tự phát hiện Bluestacks → bật lại → kết nối lại ADB → khởi chạy game → khôi phục hoạt động mà **không dừng chương trình**.

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

devices:
  - name: phone-1
    serial: 127.0.0.1:5555
  - name: phone-2
    serial: 127.0.0.1:5615
  - name: phone-3
    serial: 127.0.0.1:5625
  - name: phone-4
    serial: 127.0.0.1:5635
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

# Fleet tuần tự (1 máy tại 1 thời điểm, hỗ trợ physical_mouse)
python main.py fleet --sequential
```
