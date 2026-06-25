document.addEventListener("DOMContentLoaded", () => {
    // Application State
    let appConfig = { defaults: {}, devices: [] };
    let botRunning = false;
    let statusInterval = null;

    // DOM Elements
    const navItems = document.querySelectorAll(".nav-item");
    const tabContents = document.querySelectorAll(".tab-content");
    const toast = document.getElementById("toast");

    // Global Config Form Fields
    const globalForm = document.getElementById("global-config-form");
    const inputs = [
        "cycle_wait_min", "cycle_wait_variance_min",
        "delay_after_popup_min", "delay_after_popup_max",
        "delay_after_dispatch_min", "delay_after_dispatch_max",
        "city_world_toggle_probability"
    ];
    const checkboxes = [
        "enable_city_world_toggle", "enable_vip_claim",
        "auto_close_bluestack", "save_debug_images"
    ];

    // Devices DOM
    const devicesContainer = document.getElementById("devices-container");
    const btnAddDevice = document.getElementById("btn-add-device");
    const btnScanBs = document.getElementById("btn-scan-bs");
    const deviceModal = document.getElementById("device-modal");
    const deviceForm = document.getElementById("device-form");
    const btnCloseModal = document.getElementById("btn-close-modal");
    const modalTitle = document.getElementById("modal-title");
    const deviceIndexInput = document.getElementById("device-index");

    // Bot Control DOM
    const runModeSelect = document.getElementById("run-mode");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");
    const logTerminal = document.getElementById("log-terminal");
    const btnClearLogs = document.getElementById("btn-clear-logs");
    const sidebarStatusIndicator = document.getElementById("sidebar-status-indicator");
    const sidebarStatusText = document.getElementById("sidebar-status-text");

    // --- UTILITIES ---
    function showToast(message, type = "success") {
        toast.textContent = message;
        toast.style.borderColor = type === "success" ? "var(--success)" : "var(--danger)";
        toast.classList.add("show");
        setTimeout(() => {
            toast.classList.remove("show");
        }, 3000);
    }

    // --- TAB SWITCHING ---
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const tabName = item.getAttribute("data-tab");
            
            navItems.forEach(i => i.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));
            
            item.classList.add("active");
            document.getElementById(`tab-${tabName}`).classList.add("active");
        });
    });

    // --- RENDER FUNCTIONS ---
    function fillGlobalConfigForm() {
        const defaults = appConfig.defaults || {};
        
        inputs.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.value = defaults[id] !== undefined ? defaults[id] : "";
            }
        });

        checkboxes.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.checked = !!defaults[id];
            }
        });
    }

    function renderDevices() {
        devicesContainer.innerHTML = "";
        const devices = appConfig.devices || [];

        if (devices.length === 0) {
            devicesContainer.innerHTML = `
                <div class="card" style="grid-column: 1/-1; text-align: center; color: var(--text-secondary);">
                    Không có thiết bị nào được cấu hình. Bấm "Thêm Thiết Bị" hoặc "Quét Bluestacks" để thêm.
                </div>
            `;
            return;
        }

        devices.forEach((dev, idx) => {
            if (!dev || typeof dev !== 'object') return;
            const botCfg = dev.bot || {};
            const resource = botCfg.resource || "defaults";
            const targetLevel = botCfg.target_level !== undefined ? botCfg.target_level : "defaults";
            const maxSlots = botCfg.max_slots !== undefined ? botCfg.max_slots : "defaults";
            const skipAdjust = botCfg.skip_level_adjust !== undefined ? botCfg.skip_level_adjust : "defaults";
            const turnWait = botCfg.turn_wait_min !== undefined ? botCfg.turn_wait_min : "defaults";
            const ctrlMode = botCfg.control_mode || "defaults";

            const card = document.createElement("div");
            card.className = "card device-card";
            card.innerHTML = `
                <div class="device-card-header">
                    <div class="device-info">
                        <h4>${dev.name || 'Không tên'}</h4>
                        <span class="device-serial">${dev.serial}</span>
                    </div>
                </div>
                <div class="device-meta">
                    <div class="meta-row">
                        <span class="meta-label">Tài nguyên:</span>
                        <span class="meta-value">${resource}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Cấp slider:</span>
                        <span class="meta-value">${targetLevel}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Số slot gửi:</span>
                        <span class="meta-value">${maxSlots}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Chế độ điều khiển:</span>
                        <span class="meta-value">${ctrlMode}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Thời gian chờ:</span>
                        <span class="meta-value">${turnWait} phút</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Bỏ qua slider:</span>
                        <span class="meta-value">${skipAdjust}</span>
                    </div>
                </div>
                <div class="device-card-actions">
                    <button class="btn btn-secondary btn-edit-dev" data-index="${idx}">✏️ Sửa</button>
                    <button class="btn btn-danger btn-delete-dev" data-index="${idx}">🗑️ Xoá</button>
                </div>
            `;
            devicesContainer.appendChild(card);
        });

        // Add event listeners to edit and delete buttons
        document.querySelectorAll(".btn-edit-dev").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const idx = parseInt(e.target.getAttribute("data-index"));
                openDeviceModal(idx);
            });
        });

        document.querySelectorAll(".btn-delete-dev").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const idx = parseInt(e.target.getAttribute("data-index"));
                if (confirm(`Bạn chắc chắn muốn xoá thiết bị "${appConfig.devices[idx].name}" chứ?`)) {
                    appConfig.devices.splice(idx, 1);
                    saveConfig();
                }
            });
        });
    }

    // --- CONFIG SERVER ACTIONS ---
    async function loadConfig() {
        try {
            const res = await fetch("/api/config");
            appConfig = await res.json();
            fillGlobalConfigForm();
            renderDevices();
        } catch (e) {
            showToast("Lỗi nạp cấu hình!", "danger");
        }
    }

    async function saveConfig() {
        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(appConfig)
            });
            const data = await res.json();
            if (data.status === "success") {
                showToast("Lưu cấu hình thành công!");
                loadConfig();
            } else {
                showToast("Lỗi: " + data.error, "danger");
            }
        } catch (e) {
            showToast("Lỗi gửi dữ liệu!", "danger");
        }
    }

    // --- SAVE GLOBAL FORM ---
    globalForm.addEventListener("submit", (e) => {
        e.preventDefault();
        
        inputs.forEach(id => {
            const val = document.getElementById(id).value;
            if (id === "city_world_toggle_probability") {
                appConfig.defaults[id] = parseFloat(val);
            } else {
                appConfig.defaults[id] = parseInt(val);
            }
        });

        checkboxes.forEach(id => {
            appConfig.defaults[id] = document.getElementById(id).checked;
        });

        saveConfig();
    });

    // --- DEVICE MODAL LOGIC ---
    function openDeviceModal(index = null) {
        if (index === null) {
            modalTitle.textContent = "Thêm Thiết Bị Mới";
            deviceIndexInput.value = "";
            document.getElementById("dev-name").value = "";
            document.getElementById("dev-serial").value = "";
            
            // Set defaults from global default config
            document.getElementById("dev-resource").value = appConfig.defaults.resource || "cycle";
            document.getElementById("dev-target-level").value = appConfig.defaults.target_level !== undefined ? appConfig.defaults.target_level : 5;
            document.getElementById("dev-max-slots").value = appConfig.defaults.max_slots !== undefined ? appConfig.defaults.max_slots : 4;
            document.getElementById("dev-turn-wait").value = appConfig.defaults.turn_wait_min !== undefined ? appConfig.defaults.turn_wait_min : 60;
            document.getElementById("dev-control-mode").value = appConfig.defaults.control_mode || "adb";
            document.getElementById("dev-skip-adjust").checked = !!appConfig.defaults.skip_level_adjust;
        } else {
            modalTitle.textContent = "Sửa Thiết Bị";
            deviceIndexInput.value = index;
            
            const dev = appConfig.devices[index];
            if (!dev || typeof dev !== 'object') return;
            document.getElementById("dev-name").value = dev.name || "";
            document.getElementById("dev-serial").value = dev.serial || "";
            
            const botCfg = dev.bot || {};
            document.getElementById("dev-resource").value = botCfg.resource || "cycle";
            document.getElementById("dev-target-level").value = botCfg.target_level !== undefined ? botCfg.target_level : 5;
            document.getElementById("dev-max-slots").value = botCfg.max_slots !== undefined ? botCfg.max_slots : 4;
            document.getElementById("dev-turn-wait").value = botCfg.turn_wait_min !== undefined ? botCfg.turn_wait_min : 60;
            document.getElementById("dev-control-mode").value = botCfg.control_mode || "adb";
            document.getElementById("dev-skip-adjust").checked = !!botCfg.skip_level_adjust;
        }
        deviceModal.classList.add("active");
    }

    btnCloseModal.addEventListener("click", () => {
        deviceModal.classList.remove("active");
    });

    btnAddDevice.addEventListener("click", () => {
        openDeviceModal();
    });

    deviceForm.addEventListener("submit", (e) => {
        e.preventDefault();
        
        const idx = deviceIndexInput.value;
        const name = document.getElementById("dev-name").value;
        const serial = document.getElementById("dev-serial").value;
        const resource = document.getElementById("dev-resource").value;
        const target_level = parseInt(document.getElementById("dev-target-level").value);
        const max_slots = parseInt(document.getElementById("dev-max-slots").value);
        const turn_wait_min = parseInt(document.getElementById("dev-turn-wait").value);
        const control_mode = document.getElementById("dev-control-mode").value;
        const skip_level_adjust = document.getElementById("dev-skip-adjust").checked;

        const devObj = {
            name,
            serial,
            bot: {
                resource,
                target_level,
                max_slots,
                turn_wait_min,
                control_mode,
                skip_level_adjust
            }
        };

        if (idx === "") {
            // Check serial duplicate
            const exists = appConfig.devices.some(d => d.serial === serial);
            if (exists) {
                showToast(`Serial ${serial} đã tồn tại!`, "danger");
                return;
            }
            appConfig.devices.push(devObj);
        } else {
            appConfig.devices[parseInt(idx)] = devObj;
        }

        deviceModal.classList.remove("active");
        saveConfig();
    });

    // --- BLUESTACKS SCANNER ---
    btnScanBs.addEventListener("click", async () => {
        btnScanBs.disabled = true;
        btnScanBs.textContent = "⌛ Đang quét...";
        try {
            const res = await fetch("/api/bluestacks/scan", { method: "POST" });
            const data = await res.json();
            if (data.status === "success" && data.devices) {
                let addedCount = 0;
                data.devices.forEach(d => {
                    const exists = appConfig.devices.some(dev => dev.serial === d.serial);
                    if (!exists) {
                        appConfig.devices.push({
                            name: d.name,
                            serial: d.serial,
                            bot: {
                                resource: appConfig.defaults.resource || "cycle",
                                target_level: appConfig.defaults.target_level !== undefined ? appConfig.defaults.target_level : 5,
                                max_slots: appConfig.defaults.max_slots !== undefined ? appConfig.defaults.max_slots : 4,
                                turn_wait_min: appConfig.defaults.turn_wait_min !== undefined ? appConfig.defaults.turn_wait_min : 60,
                                control_mode: appConfig.defaults.control_mode || "adb",
                                skip_level_adjust: !!appConfig.defaults.skip_level_adjust
                            }
                        });
                        addedCount++;
                    }
                });
                showToast(`Đã tìm thấy ${data.devices.length} máy ảo. Thêm mới ${addedCount} máy.`);
                if (addedCount > 0) {
                    saveConfig();
                }
            } else {
                showToast("Lỗi: " + data.error, "danger");
            }
        } catch (e) {
            showToast("Không thể kết nối đến Bluestacks conf!", "danger");
        } finally {
            btnScanBs.disabled = false;
            btnScanBs.textContent = "🔍 Quét Bluestacks";
        }
    });

    // --- BOT COMMANDS & LOG POLLING ---
    async function fetchBotStatus() {
        try {
            const res = await fetch("/api/bot/status");
            const data = await res.json();
            
            // Update Running Status
            botRunning = data.running;
            btnStart.disabled = botRunning;
            btnStop.disabled = !botRunning;
            runModeSelect.disabled = botRunning;

            if (botRunning) {
                sidebarStatusIndicator.classList.add("running");
                sidebarStatusText.textContent = "Đang chạy bot";
            } else {
                sidebarStatusIndicator.classList.remove("running");
                sidebarStatusText.textContent = "Đang dừng";
            }

            // Update Logs Terminal
            if (data.logs && data.logs.length > 0) {
                const isScrolledToBottom = logTerminal.scrollHeight - logTerminal.clientHeight <= logTerminal.scrollTop + 30;
                
                logTerminal.innerHTML = "";
                data.logs.forEach(line => {
                    const el = document.createElement("div");
                    el.className = "log-line";
                    
                    if (line.includes("WARNING")) el.classList.add("warning");
                    else if (line.includes("ERROR") || line.includes("FAILED")) el.classList.add("error");
                    else if (line.includes("Thành công") || line.includes("SUCCESS")) el.classList.add("success");
                    else if (line.startsWith("---")) el.classList.add("system");
                    
                    el.textContent = line;
                    logTerminal.appendChild(el);
                });

                if (isScrolledToBottom) {
                    logTerminal.scrollTop = logTerminal.scrollHeight;
                }
            }
        } catch (e) {
            console.error("Lỗi cập nhật trạng thái bot", e);
        }
    }

    btnStart.addEventListener("click", async () => {
        const mode = runModeSelect.value;
        btnStart.disabled = true;
        
        try {
            const res = await fetch("/api/bot/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode })
            });
            const data = await res.json();
            if (data.status === "success") {
                showToast("Khởi chạy bot thành công!");
                fetchBotStatus();
            } else {
                showToast("Lỗi: " + data.error, "danger");
                btnStart.disabled = false;
            }
        } catch (e) {
            showToast("Lỗi kết nối khởi chạy bot!", "danger");
            btnStart.disabled = false;
        }
    });

    btnStop.addEventListener("click", async () => {
        btnStop.disabled = true;
        try {
            const res = await fetch("/api/bot/stop", { method: "POST" });
            const data = await res.json();
            if (data.status === "success") {
                showToast("Đã dừng bot!");
                fetchBotStatus();
            } else {
                showToast("Lỗi: " + data.error, "danger");
                btnStop.disabled = false;
            }
        } catch (e) {
            showToast("Lỗi kết nối dừng bot!", "danger");
            btnStop.disabled = false;
        }
    });

    btnClearLogs.addEventListener("click", () => {
        logTerminal.innerHTML = '<div class="log-line system">Nhật ký đã được xoá sạch.</div>';
    });

    // --- INITIAL LOADING ---
    loadConfig();
    fetchBotStatus();
    
    // Poll status every 1.5s
    statusInterval = setInterval(fetchBotStatus, 1500);

    // Clean up interval on page unload
    window.addEventListener("beforeunload", () => {
        if (statusInterval) clearInterval(statusInterval);
    });
});
