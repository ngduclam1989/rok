# RoKBot

Bot tu dong cho Rise of Kingdoms, chay tren may that qua ADB/scrcpy hoac
Bluestacks. Cau hinh chinh nam trong `devices.yaml`; chay nhanh bang
`run_bot.bat`.

## Moi truong

- Python: dung Python 3.12.
- Tao moi moi truong bang:

```bat
setup_env.bat --clean
```

- Khong copy thu muc `.venv` giua cac may.
- Dependency chinh nam trong `requirements.txt`.
- `scrcpy-client` dang de optional trong `requirements.txt`; neu muon dung
  `control_mode: scrcpy` thi cai trong `.venv` cua may dang chay.

Kiem tra device:

```bat
.venv\Scripts\python.exe main.py devices
```

## Lenh chay

Chay theo serial dau tien trong `devices.yaml`:

```bat
run_bot.bat
```

Chay 1 may cu the:

```bat
run_bot.bat --serial YOUR_SERIAL --control-mode scrcpy
```

Chay truc tiep bang Python:

```bat
.venv\Scripts\python.exe main.py bot --serial YOUR_SERIAL
```

Chay fleet song song cho tat ca may trong `devices.yaml`:

```bat
.venv\Scripts\python.exe main.py fleet
```

Chay fleet tuan tu tung may:

```bat
.venv\Scripts\python.exe main.py fleet --sequential
```

Chay rieng hanh trinh VIP/Boost:

```bat
.venv\Scripts\python.exe main.py bot --serial YOUR_SERIAL --only-claim-vip
```

Chay rieng vong chuyen account de debug loi switch acc:

```bat
.venv\Scripts\python.exe main.py switchacc --serial YOUR_SERIAL --control-mode scrcpy --loops 0
```

`--loops 0` la chay vo han. Neu chi muon test nhanh 4 luot:

```bat
.venv\Scripts\python.exe main.py switchacc --serial YOUR_SERIAL --control-mode scrcpy --loops 4
```

Khi `--loops` lon hon `0`, het so luot test bot se ep chuyen ve account dau
tien trong `account.txt` (`lam6`) truoc khi ket thuc command.

## Cau hinh devices.yaml

Vi du cau hinh dang dung:

```yaml
defaults:
  resource: cycle_random
  farm_scenario: random
  target_level: 5
  max_slots: 5
  skip_level_adjust: true
  turn_wait_min: 60
  control_mode: scrcpy
  enable_vip_claim: true
  cycle_wait_min: 60
  cycle_wait_variance_min: 10
  alliance_gifts_probability: 1.0
  alliance_territory_probability: 1.0
  alliance_tech_probability: 1.0

devices:
  - name: phone-redmi
    serial: zhkrinrsww7d6hbu
```

Tai nguyen hop le:

- `corn`, `wood`, `stone`, `gold`, `barb`
- `cycle_random`, `cycle_1`, `cycle_2`, `cycle_3`, `cycle_4`, `cycle_5`
- Co the tach rieng:

```yaml
resource: cycle
farm_scenario: random   # random / 1 / 2 / 3 / 4 / 5
```

`cycle_wait_min`:

- `0`: sau khi chay het mot vong bot se thoat va force-stop game
  `com.rok.gp.vn`.
- Lon hon `0`: bot ngu theo `cycle_wait_min +/- cycle_wait_variance_min` roi
  chay lai vong moi.

## Luong action chinh

Moi account/nhan vat se co mot danh sach action phang:

```text
farm + tung viec vat rieng le
```

Thu tu `farm` va tung viec vat duoc shuffle rieng cho tung account/nhan vat.
Vi du co the la `vip/boost -> farm -> nhan qua -> cong nghe -> ...`, hoac
`farm -> tai nguyen noi thanh -> tro giup -> ...`. Khi toan bo action trong
danh sach da xong, bot moi chuyen nhan vat/account tiep theo.

Tat ca viec vat deu la action rieng va duoc random ngang hang voi `farm`.

### chores

`chores` gom cac viec vat sau:

- Lay tai nguyen noi thanh: 100%, toi da 4 diem.
- Tro giup lien minh: 100%.
- Nhan qua lien minh: 100%.
- Thu tai nguyen lanh tho: 100%.
- Dong gop cong nghe lien minh: 100%.
- VIP/Boost: chi them vao chores neu `enable_vip_claim: true`.

Thu tu cac viec vat duoc random cung voi `farm`, nhung tat ca deu bat buoc chay.
Truoc va sau moi viec, bot co gang dua man hinh ve WORLD/CITY de viec tiep theo
khong bi lech state.

### farm

1. Doc huy hieu hang doi `n/N` khi bat dau.
2. Neu hang doi da day thi danh dau farm xong, khong dung giua chung workflow
   khac.
3. Neu `resource` la tai nguyen co dinh thi farm dung loai do.
4. Neu `resource: cycle` thi lay ke hoach theo `farm_scenario`.
5. Tim tai nguyen, chinh cap neu `skip_level_adjust: false`, gui quan.
6. Sau moi lan gui thanh cong, doc lai hang doi; day hang doi thi farm xong.

Kich ban `cycle`:

- `1`: 4 luot dau gom du `corn/stone/gold/wood` theo thu tu random; luot 5
  random 1 trong 4 loai.
- `2`: 2 luot dau la `gold`; 3 luot sau gom du `corn/stone/wood` theo thu tu
  random.
- `3`: luot dau la `gold`; 4 luot sau gom du `corn/stone/gold/wood` theo thu
  tu random.
- `4`: chay theo thu tu `gold`, `stone`, `wood`, `corn`, `corn`.
- `5`: luot dau la `corn`; 4 luot sau gom du `corn/stone/gold/wood` theo thu
  tu random.
- `random`: chon ngau nhien 1 trong 5 kich ban tren khi bat dau plan.

#### VIP / Boost

Trong `chores`, muc `VIP/Boost` chay nhu sau:

1. Dua ve WORLD.
2. Scan buff gathering boost active bang template:
   - `assets/templates/gathering_boost/buffs/enhanced_gathering_blue.png`
   - `assets/templates/gathering_boost/buffs/enhanced_gathering_purple.png`
3. Neu da co boost active: bo qua ca VIP va boost, ket thuc workflow.
4. Neu chua co boost active: random thu tu chay giua `vip` va `boost`, sau do
   chay lan luot ca hai action.

Action VIP:

1. Chuyen sang CITY neu dang o WORLD.
2. Mo VIP.
3. OCR vung nut `NHAN` cua diem VIP va ruong VIP mien phi.
4. Neu thay `NHAN` thi tap nhan diem va ruong.
5. Dong giao dien VIP va dua ve WORLD.

Action Boost:

1. Ve WORLD/map.
2. Scan boost active lan nua.
3. Neu chua active thi mo menu hien tai.
4. OCR muc `Dao Cu`; neu doc duoc thi tap vao vung do.
5. Tap tab boost.
6. Tim item `enhanced_gathering_blue` va `enhanced_gathering_purple` trong
   assets:
   - `assets/templates/gathering_boost/items/enhanced_gathering_blue.png`
   - `assets/templates/gathering_boost/items/enhanced_gathering_purple.png`
7. Neu thay ca blue va purple thi uu tien blue.
8. Tap item center +/-20px.
9. Tap nut su dung trong vung cau hinh.
10. Tap nut X trong vung cau hinh.
11. Scan lai buff active de xac nhan.
12. Neu B8 khong thay item nao thi tap X va ket thuc boost action.

## Nhan vat va account

Moi account chay 2 nhan vat:

1. Chay het workflow cho `char 1`.
2. Chuyen sang `char 2`.
3. Chay het workflow cho `char 2`.
4. Chuyen sang account tiep theo trong `account.txt`.

Thu tu account duoc tinh theo `account.txt`:

```text
ngduclam6@gmail.com
ngduclam29@gmail.com
ngduclam999@gmail.com
ngduclam1999@gmail.com
```

Quy tac chay:

- Neu account dau tien bot nhan dien la dong cuoi danh sach
  `ngduclam1999@gmail.com`, bot chay nguoc:
  `lam1999 -> lam999 -> lam29 -> lam6`.
- Moi truong hop con lai, ke ca khi dang bat dau o account giua danh sach, bot
  chay xuoi tu dau danh sach:
  `lam6 -> lam29 -> lam999 -> lam1999`.

Voi thu tu hien tai cua anh, chu trinh day du la:

```text
MOI ACCOUNT / MOI CHAR:
random(farm, lay tai nguyen noi thanh, tro giup, nhan qua, lanh tho, cong nghe, vip/boost)

ACCOUNT:
lam6 char 1  -> lam6 char 2
lam29 char 1 -> lam29 char 2
lam999 char 1 -> lam999 char 2
lam1999 char 1 -> lam1999 char 2

XONG:
tu account cuoi -> quay lai lam6
-> force-stop com.rok.gp.vn -> B6 ngu theo cycle_wait_min +/- cycle_wait_variance_min
```

Sau khi account cuoi chay xong ca `farm` va `chores`, bot wrap ve account dau
tien trong `account.txt` la `lam6`, cho game load on dinh roi tat app. B6 khong
doc timer Doi Quan nua; bot chi ngu theo `cycle_wait_min +/- cycle_wait_variance_min`
trong `devices.yaml` roi tu dong bat lai chu trinh moi. Vi du `cycle_wait_min: 60` va
`cycle_wait_variance_min: 10` thi moi vong se ngu ngau nhien 50-70 phut.

Khi switch account tra ve:

- `switched`: account tiep theo thanh cong, quay lai `char 1`.
- `wrapped`: da het account, bot quay ve account dau tien trong `account.txt`
  (`lam6`), cho game load on dinh, roi goi `device.shutdown()`.

Neu switch account loi:

- Moi lan switch account se thu toi da 3 lan trong cung man hinh.
- Neu ca 3 lan fail, bot dua ve WORLD, cho 20-35s va retry mem lan sau.
- Neu retry mem qua 5 lan lien tiep van fail, bot kill app, mo lai game, dua ve
  WORLD roi chay lai logic chuyen acc theo dung danh sach/pha hien tai.

`device.shutdown()` se chay:

```bat
adb -s SERIAL shell am force-stop com.rok.gp.vn
```

## Ket thuc bot va tat app

Co 2 duong tat app game:

1. Het danh sach account/da quay ve account dau tien: runtime goi
   `device.shutdown()`.
2. `cycle_wait_min: 0`: sau khi `bot_engine.run()` ket thuc, CLI `bot` va
   `fleet --sequential` goi `device.shutdown()` truoc khi thoat.

Lenh nay chi tat app game `com.rok.gp.vn`; khong tat may, khong tat gia lap.
Neu la Bluestacks, viec tat gia lap phu thuoc `auto_close_bluestack`.

## Control modes

- `scrcpy`: dung scrcpy client de lay video/control nhanh tren may that. Van
  dung ADB cho lenh he thong nhu `force-stop`, `pidof`, `monkey`.
- `adb`: dung snapshot/tap qua ADB.
- `physical_mouse`: dung chuot vat ly voi cua so Bluestacks.

Neu `scrcpy` loi import, can cai `scrcpy-client` trong `.venv`. Neu PyAV loi
decode stream tren may that, bot co patch stream loop trong `core/device.py`,
nhung van nen chay dung Python 3.12 va dung dependency trong `.venv`.

## Debug nhanh

Kiem tra app ROK dang chay:

```bat
.venv\Lib\site-packages\airtest\core\android\static\adb\windows\adb.exe -s YOUR_SERIAL shell pidof com.rok.gp.vn
```

Tat app ROK thu cong:

```bat
.venv\Lib\site-packages\airtest\core\android\static\adb\windows\adb.exe -s YOUR_SERIAL shell am force-stop com.rok.gp.vn
```

Anh debug `boost` thi xem anh chup trong `captures/` va template trong
`assets/templates/gathering_boost/`.
