# Gathering Boost Export

Folder này gom riêng logic và ảnh cho tính năng dùng buff tăng tốc farm tài nguyên.

## Có gì bên trong

- `gathering_boost_action.py`: code độc lập mô tả action check buff và dùng item.
- `manifest.json`: thông tin ảnh, threshold image matching, tọa độ bấm.
- `images/buffs/enhanced_gathering_blue.png`: ảnh icon buff xanh đang active trên map.
- `images/buffs/enhanced_gathering_purple.png`: ảnh icon buff tím đang active trên map.
- `images/items/enhanced_gathering_blue.png`: ảnh item buff xanh trong túi.
- `images/items/enhanced_gathering_purple.png`: ảnh item buff tím trong túi.

## Luồng action

1. Về map.
2. So sánh ảnh để xem buff xanh hoặc tím đang active chưa.
3. Nếu đã active thì không làm gì.
4. Nếu chưa active thì mở menu.
5. Mở Items.
6. Chọn tab Boosts.
7. Tìm item blue, bấm item, bấm Use.
8. Nếu không thấy item blue thì thử item purple.

## Tọa độ gốc

- Items icon: `(930, 675)`
- Boosts tab: `(610, 80)`
- Use button: `(980, 600)`
- Screen size gốc: `1280x720`
- Threshold match ảnh: `0.70`

## Lưu ý khi đưa sang project khác

Code không đọc text/tên/thông số item trong game. Nó chỉ dùng image matching và bấm tọa độ cố định.

Trong project gốc, `ENHANCED_GATHER_PURPLE` của item đang trỏ nhầm sang ảnh blue. Folder export này đã để đúng ảnh purple:

```python
ImageProps("images/items/enhanced_gathering_purple.png")
```

Để tích hợp, tạo adapter có 4 hàm:

```python
back_to_map()
menu_should_open(should_open: bool)
tap(x, y, sleep_time=0.1)
check_any(image_props) -> (found: bool, pos: tuple | None)
```
