# RoKBot

Bot tu dong cho Rise of Kingdoms, ho tro chay tren may that qua ADB va cac
luong dieu khien da cau hinh trong project.

## Moi truong

- Dung Python 3.12.
- Tao moi moi truong bang `setup_env.bat --clean`.
- Khong copy thu muc `.venv` giua cac may.
- Dependency va ghi chu scrcpy optional nam trong `requirements.txt`.

## Cai dat

```bat
setup_env.bat --clean
```

Kiem tra device:

```bat
.venv\Scripts\python.exe main.py devices
```

Chay nhanh tren may that hien tai:

```bat
.venv\Scripts\python.exe main.py bot --serial YOUR_SERIAL --control-mode adb --max-iter 1
```

Chay bang file `.bat` de khong can activate `.venv`:

```bat
run_bot.bat
```

Neu can truyen them tham so:

```bat
run_bot.bat --serial YOUR_SERIAL --control-mode adb
```

Chay rieng luong claim VIP:

```bat
.venv\Scripts\python.exe main.py bot --serial YOUR_SERIAL --control-mode adb --only-claim-vip
```

## Quy trinh bot

Bot chay theo cac buoc chinh sau:

1. `B0 - Khoi tao`: doc `devices.yaml`, nap cau hinh, dang ky phim tat
   `Ctrl+Space` de pause/resume, bat input lock neu duoc cau hinh.
2. `B1 - Kiem tra moi truong thiet bi`: voi Bluestacks thi kiem tra/bat
   instance; voi may that thi bo qua phan Bluestacks va dung ADB serial hien co.
3. `B2 - Dua game len truoc`: kiem tra game da chay chua, start app neu can,
   bring-to-front neu game da mo, sau do cho giao dien on dinh.
4. `B3 - Chuan bi man hinh`: bo qua popup dau vao, quet logo `18+`, dua game ve
   state phu hop (`world`/`city`) de bat dau workflow.
5. `B4 - Chay workflow`: xao tron va thuc hien cac viec nhu `getres`,
   `alliance`, `farm`, `vip`; doc slot hanh quan, chinh slider tai nguyen, gui
   quan farm, chuyen nhan vat va chuyen account khi ca 2 nhan vat da xong.
6. `B5 - Don dep`: xoa capture debug tam, mo khoa input, dong/giu app theo cau
   hinh va giai phong ket noi device.
7. `B6 - Cho vong tiep theo`: neu chay lien tuc, bot ngu theo thoi gian cau
   hinh roi lap lai tu dau.

Luot claim VIP co the chay rieng bang `--only-claim-vip`; bot se vao city, mo
VIP, OCR vung chu `NHAN`, tap nhan diem/rong free neu con, roi dong popup VIP.

## Luong nhan vat va account

Bot chay moi account theo 2 nhan vat:

1. Chay workflow cho `char 1`.
2. Khi `char 1` xong het workflow / day hang doi, bot vao game menu va chuyen
   sang `char 2`.
3. Chay workflow cho `char 2`.
4. Khi `char 2` xong, bot vao `Trung Tam Nguoi Dung` va chuyen sang account
   tiep theo trong `account.txt`.
5. Account moi se quay lai buoc 1, bat dau tu `char 1`.

Thu tu account duoc tinh theo `account.txt`:

- Neu account dau tien bot nhan dien la dong cuoi danh sach, bot chay nguoc
  tu cuoi len dau.
- Moi truong hop con lai, ke ca khi account dau tien nam giua danh sach, bot
  chay xuoi tu dong dau tien.

Vi du voi `account.txt` hien tai:

```text
ngduclam6@gmail.com
ngduclam29@gmail.com
ngduclam999@gmail.com
ngduclam1999@gmail.com
```

- Neu bat dau o `ngduclam1999@gmail.com`, thu tu la `1999 -> 999 -> 29 -> 6`.
- Neu bat dau o `ngduclam6@gmail.com`, `ngduclam29@gmail.com`, hoac
  `ngduclam999@gmail.com`, thu tu la `6 -> 29 -> 999 -> 1999`.

Khi account cuoi cung chay xong `char 2`, bot se chuyen lai account dau tien
theo thu tu chay, dua ve `char 1`, roi kill app game `com.rok.gp.vn`. Bot chi
dong app Rise of Kingdoms, khong tat may hay tat gia lap.

## Control modes

- `adb`: mac dinh, on dinh tren may that.
- `physical_mouse`: dung chuot vat ly voi cua so gia lap.
- `scrcpy`: nhanh hon ve ly thuyet, lay frame tu `last_frame` va gui touch qua
  control socket. Hien de optional vi `scrcpy-client` phu thuoc PyAV 9.2, co
  the loi build tren Windows neu thieu FFmpeg development libraries.

Neu muon thu `scrcpy`, mo comment hai dong optional cuoi `requirements.txt` roi
cai lai requirements. Neu import `scrcpy` khong kha dung, bot tu fallback ve ADB.

## Tai lieu

- `devices.yaml.example`: mau cau hinh device.
