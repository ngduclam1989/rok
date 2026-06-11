# Rise of Kingdoms Bot Action Extract

Thu muc nay gom cac action:

- Collecting: thu tai nguyen trong thanh.
- Training: train/nang cap linh.
- Alliance: alliance help, gift, territory resource, technology donate.
- ClaimQuests va ClaimVip.
- Tavern: mo chest tavern.
- Materials: san xuat vat lieu trong blacksmith.

## Cau truc

- `tasks/`: source task goc can ghep sang project khac.
- `support/`: file phu thuoc truc tiep cua cac task.
- `resources/resource/`: anh mau dung de nhan dien nut/man hinh.
- `sample/`: config va building position mau lay tu profile `kurtadam_127.0.0.1_5555`.
- `project_root_copy/`: ban da sap xep dung layout root cua project Python. Neu muon copy nhanh sang project khac, uu tien dung thu muc nay.

## File task chinh

- `tasks/Collecting.py`
- `tasks/Training.py`
- `tasks/Alliance.py`
- `tasks/ClaimQuests.py`
- `tasks/ClaimVip.py`
- `tasks/Tavern.py`
- `tasks/Materials.py`

## Dependency can co

Cac task tren deu ke thua `Task`, nen can ghep them:

- `tasks/Task.py`
- `tasks/constants.py`
- `support/bot_related/bot_config.py`
- `support/bot_related/device_gui_detector.py`
- `support/bot_related/aircve.py`
- `support/bot_related/haoi.py`
- `support/bot_related/twocaptcha.py`
- `support/filepath/file_relative_paths.py`
- `support/filepath/constants.py`
- `support/utils.py`
- `support/config.py`

Python packages trong `support/requirements.txt`:

- `opencv-python`
- `pytesseract`
- `numpy`
- `Pillow`
- `pure-python-adb`
- `requests`
- `requests-toolbelt`
- `customtkinter`
- `python-tkdnd`

## Dieu kien runtime

Bot object can co cac field/method sau:

- `bot.device`: object ADB device co method `shell(cmd)`.
- `bot.gui`: instance `GuiDetector`.
- `bot.config`: instance `BotConfig`.
- `bot.building_pos`: dict toa do cong trinh.
- `bot.text_update_event`: callback nhan log UI, co the de lambda.

Vi du `building_pos` can co it nhat cac key:

- `barracks`
- `archery_range`
- `stable`
- `siege_workshop`
- `farm`
- `lumber_mill`
- `quarry`
- `goldmine`
- `alliance_center`
- `blacksmith`
- `tavern`

Xem mau trong `sample/sample_building_pos.json`.

## Config key theo action

### Collecting

- `enableCollecting`: bat/tat task.
- `hasBuildingPos`: nen la `true` neu da co toa do cong trinh.

Task tap lan luot cac cong trinh linh va resource, sau do tap diem collect `(105, 125)`.

### Training

- `enableTraining`: bat/tat task.
- `trainBarracksTrainingLevel`
- `trainBarracksUpgradeLevel`
- `trainArcheryRangeTrainingLevel`
- `trainArcheryRangeUpgradeLevel`
- `trainStableTrainingLevel`
- `trainStableUpgradeLevel`
- `trainSiegeWorkshopTrainingLevel`
- `trainSiegeWorkshopUpgradeLevel`

Gia tri level:

- `0`: T1
- `1`: T2
- `2`: T3
- `3`: T4
- `4`: T5
- `5`: upgrade all den T4
- `-1`: disable

### Alliance

- `allianceAction`: bat/tat task.
- `allianceDoRound`: chay moi N vong.

Task thuc hien 4 phan: `HELP`, `GIFTS`, `TERRITORY`, `TECHNOLOGY`.

### ClaimQuests

- `claimQuests`: bat/tat task.
- `questDoRound`: chay moi N vong.

Task claim quest, daily objective, va tap cac chest daily objective.

### ClaimVip

- `enableVipClaimChest`: bat/tat task.
- `vipDoRound`: chay moi N vong.

Task tap VIP, claim daily VIP point va free VIP chest.

### Tavern

- `enableTavern`: bat/tat task.

Task tap tavern building, vao tavern, lap toi da 20 lan de open chest va confirm.

### Materials

- `enableMaterialProduce`: bat/tat task.
- `materialDoRound`: chay moi N vong.

Task tap blacksmith, vao production, OCR so luong 4 material, chon loai dang it nhat de san xuat.

## Anh resource can copy dung duong dan

Cac duong dan trong code dang hardcode dang `resource\\file.png`, nen khi ghep sang project khac nen giu folder `resource/` o root hoac sua `resource_path()`.

Anh dung cho navigation/common:

- `map_button.png`
- `home_button.png`
- `green_home_button.png`
- `window.png`
- `window_title_mark.png`
- `building_title_left.png`
- `menu_opened.png`
- `menu_button.png`
- `map_button_0.png`
- `home_button_0.png`

Anh dung cho verification:

- `verification_verify_button.png`
- `verification_verify_title.png`
- `verification_close_refresh_ok_button.png`
- `verification_chest.png`
- `verification_chest_button.png`
- `verification_chest_button1.png`

Anh dung cho ClaimQuests:

- `quests_claim_button.png`

Anh dung cho Training:

- `barracks_button.png`
- `archery_range_button.png`
- `stable_button.png`
- `siege_workshop_button.png`
- `training_upgrade_button.png`
- `train_button.png`
- `upgrade_button.png`
- `speed_up_button.png`

Anh dung cho Alliance:

- `alliance_gifts_claim_button.png`
- `alliance_tech_recommend.png`
- `alliance_tech_donate.png`

Anh dung cho Materials:

- `materials_production_button.png`

Anh dung cho Tavern:

- `tavern_button.png`
- `chest_open_button.png`
- `chest_confirm_button.png`

## Ghi chu khi ghep

- Code goc mac dinh man hinh game la `1280x720`; nhieu toa do tap la hardcoded.
- `Task.back_to_home_gui()` va `Task.back_to_map_gui()` phu thuoc `GuiDetector.get_curr_gui_name()`.
- `Materials` phu thuoc OCR trong `GuiDetector.materilal_amount_image_to_string()` va Tesseract path trong `FilePaths.TESSERACT_EXE_PATH`.
- Neu project moi khong can CAPTCHA, van can giu stub/config cho `config.global_config.method` de `Task.py` import khong loi.
- Trong ban copy, `file_relative_paths.py` da duoc bo sung enum `VERIFICATION_CHEST_IMG_PATH` va `VERIFICATION_CHEST1_IMG_PATH` vi `Task.check_capcha()` co goi hai key nay.
