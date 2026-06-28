'use strict';


let socket = null;
let boardSelectActive = false;
let startX, startY;
let scaleX = 1.0, scaleY = 1.0;
let screenshotOrigWidth = 1920;
let screenshotOrigHeight = 1080;
let selectionRect = { x: 0, y: 0, w: 0, h: 0 };


const serverDot = document.getElementById('server-status-dot');
const serverText = document.getElementById('server-status-text');


const navButtons = document.querySelectorAll('.nav-btn');
const tabContents = document.querySelectorAll('.tab-content');


const statEval = document.getElementById('stat-eval');
const evalBar = document.getElementById('eval-bar-fill');
const statDepth = document.getElementById('stat-depth');
const statNps = document.getElementById('stat-nps');
const statTime = document.getElementById('stat-time');
const statPv = document.getElementById('stat-pv');


const metricCpuVal = document.getElementById('metric-cpu-val');
const metricCpuFill = document.getElementById('metric-cpu-fill');
const metricRamVal = document.getElementById('metric-ram-val');
const metricRamFill = document.getElementById('metric-ram-fill');
const metricThreadsVal = document.getElementById('metric-threads-val');


const screenContainer = document.getElementById('screenshot-container');
const screenPlaceholder = document.getElementById('screenshot-placeholder');
const screenImg = document.getElementById('screenshot-img');
const selectionBox = document.getElementById('selection-box');
const cvBoardRectText = document.getElementById('cv-board-rect');
const cvCalibratedBadge = document.getElementById('cv-calibrated-badge');
const cvOrientationText = document.getElementById('cv-orientation');
const cvCurrentFenText = document.getElementById('cv-current-fen');


const btnScreenshot = document.getElementById('btn-screenshot');
const btnAutoDetect = document.getElementById('btn-autodetect');
const btnCalibrate = document.getElementById('btn-calibrate');
const btnTestFen = document.getElementById('btn-test-fen');
const btnSaveSettings = document.getElementById('btn-save-settings');


const settingMode = document.getElementById('setting-mode-select');
const settingAutoplay = document.getElementById('setting-autoplay');
const settingAllocator = document.getElementById('setting-allocator-select');
const settingThreads = document.getElementById('setting-threads-slider');
const settingThreadsVal = document.getElementById('setting-threads-val');
const settingHash = document.getElementById('setting-hash-slider');
const settingHashVal = document.getElementById('setting-hash-val');
const settingQuality = document.getElementById('setting-quality-slider');
const settingQualityVal = document.getElementById('setting-quality-val');
const settingSafetyBuffer = document.getElementById('setting-safety-buffer');

const manualSettingsPanel = document.getElementById('manual-allocator-settings');
const autoSettingsPanel = document.getElementById('auto-allocator-settings');


navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.getAttribute('data-tab');
        
        navButtons.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        
        btn.classList.add('active');
        document.getElementById(`tab-${tabName}`).classList.add('active');
    });
});


settingAllocator.addEventListener('change', () => {
    if (settingAllocator.value === 'manual') {
        manualSettingsPanel.style.display = 'block';
        autoSettingsPanel.style.display = 'none';
    } else {
        manualSettingsPanel.style.display = 'none';
        autoSettingsPanel.style.display = 'block';
    }
});

settingThreads.addEventListener('input', () => {
    settingThreadsVal.textContent = settingThreads.value;
});

settingHash.addEventListener('input', () => {
    settingHashVal.textContent = `${settingHash.value} MB`;
});

settingQuality.addEventListener('input', () => {
    settingQualityVal.textContent = `${settingQuality.value}x`;
});


function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws_dashboard`;
    
    console.log(`Connecting to server WS: ${wsUrl}`);
    socket = new WebSocket(wsUrl);
    
    socket.onopen = () => {
        console.log('Connected to server!');
        serverDot.className = 'status-indicator connected';
        serverText.textContent = 'Active';
    };
    
    socket.onclose = () => {
        console.warn('WebSocket connection lost. Reconnecting in 3s...');
        serverDot.className = 'status-indicator disconnected';
        serverText.textContent = 'Disconnected';
        setTimeout(connectWebSocket, 3000);
    };
    
    socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
    };
    
    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleServerMessage(msg);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };
}

function sendWS(data) {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(data));
    }
}


function handleServerMessage(msg) {
    if (!msg || !msg.type) return;
    
    switch (msg.type) {
        case 'telemetry':
            updateTelemetry(msg.data);
            break;
        case 'cv_state':
            updateCVState(msg.data);
            break;
        case 'screenshot':
            displayScreenshot(msg.image, msg.width, msg.height);
            break;
        case 'settings':
            loadSettings(msg.data);
            break;
        default:
            console.log('Received unknown message type:', msg.type);
    }
}


function updateTelemetry(data) {
    
    if (data.eval !== undefined) {
        let displayScore = '0.00';
        if (data.eval_type === 'mate') {
            displayScore = `M${data.eval > 0 ? '+' : ''}${data.eval}`;
            statEval.className = 'value badge badge-green';
            evalBar.style.width = data.eval > 0 ? '100%' : '0%';
        } else {
            const cp = data.eval / 100;
            displayScore = (cp > 0 ? '+' : '') + cp.toFixed(2);
            statEval.className = 'value';
            
            
            const normalized = Math.max(0, Math.min(100, (cp + 5) * 10));
            evalBar.style.width = `${normalized}%`;
        }
        statEval.textContent = displayScore;
    }
    
    
    if (data.depth !== undefined) {
        statDepth.textContent = `${data.depth} / ${(data.nodes || 0).toLocaleString()}`;
    }
    
    
    if (data.nps !== undefined) {
        statNps.textContent = data.nps >= 1000000 
            ? `${(data.nps / 1000000).toFixed(2)}M nps` 
            : `${(data.nps / 1000).toFixed(0)}k nps`;
    }
    
    
    if (data.our_time !== undefined) {
        const totalSecs = data.our_time / 1000;
        const mins = Math.floor(totalSecs / 60);
        const secs = (totalSecs % 60).toFixed(1);
        statTime.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(4, '0')}`;
    }
    
    
    if (data.pv) {
        statPv.textContent = data.pv;
    }
    
    
    if (data.cpu !== undefined) {
        metricCpuVal.textContent = `${data.cpu.toFixed(0)}%`;
        metricCpuFill.style.width = `${data.cpu}%`;
    }
    if (data.ram !== undefined) {
        metricRamVal.textContent = `${data.ram.toFixed(0)}%`;
        metricRamFill.style.width = `${data.ram}%`;
    }
    if (data.threads !== undefined) {
        metricThreadsVal.textContent = `${data.threads} / ${data.total_cores || 1}`;
    }
}

function updateCVState(data) {
    if (data.rect) {
        cvBoardRectText.textContent = `x:${data.rect[0]}, y:${data.rect[1]} (${data.rect[2]}x${data.rect[3]})`;
        btnCalibrate.disabled = false;
        btnTestFen.disabled = !data.is_calibrated;
    } else {
        cvBoardRectText.textContent = 'Not set';
        btnCalibrate.disabled = true;
        btnTestFen.disabled = true;
    }
    
    if (data.is_calibrated) {
        cvCalibratedBadge.textContent = 'Yes';
        cvCalibratedBadge.className = 'value badge badge-green';
        btnTestFen.disabled = false;
    } else {
        cvCalibratedBadge.textContent = 'No';
        cvCalibratedBadge.className = 'value badge badge-red';
        btnTestFen.disabled = true;
    }
    
    cvOrientationText.textContent = data.is_flipped ? 'Flipped (Black Bottom)' : 'Normal (White Bottom)';
    
    if (data.current_fen) {
        cvCurrentFenText.textContent = data.current_fen;
    }
}

function displayScreenshot(base64Image, w, h) {
    screenshotOrigWidth = w;
    screenshotOrigHeight = h;
    
    screenPlaceholder.style.display = 'none';
    screenImg.style.display = 'block';
    screenImg.src = `data:image/jpeg;base64,${base64Image}`;
    
    
    setTimeout(updateImageScales, 100);
}

function updateImageScales() {
    if (!screenImg.complete) return;
    const clientW = screenImg.clientWidth;
    const clientH = screenImg.clientHeight;
    
    scaleX = screenshotOrigWidth / clientW;
    scaleY = screenshotOrigHeight / clientH;
    console.log(`Image scale updated: scaleX=${scaleX.toFixed(2)}, scaleY=${scaleY.toFixed(2)}`);
}

window.addEventListener('resize', updateImageScales);

function loadSettings(data) {
    if (!data) return;
    
    settingMode.value = data.mode || 'extension';
    settingAutoplay.checked = data.autoplay !== undefined ? data.autoplay : true;
    settingAllocator.value = data.allocator || 'auto';
    settingThreads.value = data.threads || 2;
    settingThreadsVal.textContent = settingThreads.value;
    settingHash.value = data.hash || 256;
    settingHashVal.textContent = `${settingHash.value} MB`;
    settingQuality.value = data.quality || 1.0;
    settingQualityVal.textContent = `${settingQuality.value}x`;
    settingSafetyBuffer.value = data.safety_buffer || 2000;
    
    
    settingAllocator.dispatchEvent(new Event('change'));
}


btnSaveSettings.addEventListener('click', () => {
    const settings = {
        type: 'update_settings',
        mode: settingMode.value,
        autoplay: settingAutoplay.checked,
        allocator: settingAllocator.value,
        threads: parseInt(settingThreads.value),
        hash: parseInt(settingHash.value),
        quality: parseFloat(settingQuality.value),
        safety_buffer: parseInt(settingSafetyBuffer.value)
    };
    sendWS(settings);
    alert('Settings applied successfully!');
});


btnScreenshot.addEventListener('click', () => {
    sendWS({ type: 'cv_command', cmd: 'screenshot' });
});

btnAutoDetect.addEventListener('click', () => {
    sendWS({ type: 'cv_command', cmd: 'autodetect' });
});

btnCalibrate.addEventListener('click', () => {
    sendWS({ type: 'cv_command', cmd: 'calibrate' });
});

btnTestFen.addEventListener('click', () => {
    sendWS({ type: 'cv_command', cmd: 'test_fen' });
});


screenImg.addEventListener('mousedown', (e) => {
    if (!screenImg.src) return;
    e.preventDefault();
    boardSelectActive = true;
    
    const rect = screenImg.getBoundingClientRect();
    startX = e.clientX - rect.left;
    startY = e.clientY - rect.top;
    
    selectionBox.style.display = 'block';
    selectionBox.style.left = `${startX + screenImg.offsetLeft}px`;
    selectionBox.style.top = `${startY + screenImg.offsetTop}px`;
    selectionBox.style.width = '0px';
    selectionBox.style.height = '0px';
});

screenContainer.addEventListener('mousemove', (e) => {
    if (!boardSelectActive) return;
    
    const rect = screenImg.getBoundingClientRect();
    const currentX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const currentY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
    
    const x = Math.min(startX, currentX);
    const y = Math.min(startY, currentY);
    const w = Math.abs(startX - currentX);
    const h = Math.abs(startY - currentY);
    
    
    const size = Math.max(w, h);
    
    selectionBox.style.left = `${x + screenImg.offsetLeft}px`;
    selectionBox.style.top = `${y + screenImg.offsetTop}px`;
    selectionBox.style.width = `${size}px`;
    selectionBox.style.height = `${size}px`;
    
    
    selectionRect = {
        x: Math.round(x * scaleX),
        y: Math.round(y * scaleY),
        w: Math.round(size * scaleX),
        h: Math.round(size * scaleY)
    };
});

window.addEventListener('mouseup', () => {
    if (!boardSelectActive) return;
    boardSelectActive = false;
    
    
    if (selectionRect.w > 50 && selectionRect.h > 50) {
        console.log('Sending bounds selection to server:', selectionRect);
        sendWS({
            type: 'cv_command',
            cmd: 'set_bounds',
            x: selectionRect.x,
            y: selectionRect.y,
            w: selectionRect.w,
            h: selectionRect.h
        });
    } else {
        selectionBox.style.display = 'none';
    }
});


connectWebSocket();
