/**
 * Rafi Mobile Companion
 *
 * Vertical-first web UI that connects to Rafi over WebSocket.
 * Provides camera access via getUserMedia and hand gesture
 * recognition via MediaPipe Tasks Vision (client-side WASM).
 */

// ── Configuration ────────────────────────────────────────────────────────────

const WS_RECONNECT_DELAY = 3000;
const GESTURE_COOLDOWN_MS = 1500;

// Colors matching the PySide6 desktop theme
const COLORS = {
    accentCyan:   [34, 211, 238],
    accentBright: [0, 255, 255],
    glowTeal:     [6, 182, 212],
    textGlow:     [34, 211, 238],
    textCrisp:    [224, 243, 255],
};

// ── State ────────────────────────────────────────────────────────────────────

let ws = null;
let cameraStream = null;
let gestureRecognizer = null;
let visualizerActive = false;
let visualizerIntensity = 0;
let visualizerTime = 0;
let lastGestureTime = 0;
let animFrameId = null;
let micActive = false;
let recognition = null;
let audioQueue = [];
let audioPlaying = false;

// ── DOM Elements ─────────────────────────────────────────────────────────────

const voiceBadge   = document.getElementById('voice-badge');
const cameraBadge  = document.getElementById('camera-badge');
const vizCanvas    = document.getElementById('visualizer');
const transcript   = document.getElementById('transcript');
const camSection   = document.getElementById('camera-section');
const camPreview   = document.getElementById('camera-preview');
const gestCanvas   = document.getElementById('gesture-canvas');
const gestLabel    = document.getElementById('gesture-label');
const micBtn       = document.getElementById('mic-btn');
const cameraBtn    = document.getElementById('camera-btn');
const textInput    = document.getElementById('text-input');

// ═══════════════════════════════════════════════════════════════════════════════
// WebSocket
// ═══════════════════════════════════════════════════════════════════════════════

function connectWebSocket() {
    const params  = new URLSearchParams(window.location.search);
    const token   = params.get('t') || '';
    const proto   = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url     = `${proto}//${location.host}/ws/mobile?t=${encodeURIComponent(token)}`;

    ws = new WebSocket(url);

    ws.onopen = () => {
        voiceBadge.textContent = 'CONNECTED';
        voiceBadge.className   = 'badge connected';
    };

    ws.onmessage = (evt) => {
        try { handleServerMessage(JSON.parse(evt.data)); }
        catch (e) { console.error('WS parse error', e); }
    };

    ws.onclose = () => {
        voiceBadge.textContent = 'OFFLINE';
        voiceBadge.className   = 'badge';
        setTimeout(connectWebSocket, WS_RECONNECT_DELAY);
    };

    ws.onerror = (err) => console.error('WS error', err);
}

function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

function handleServerMessage(data) {
    switch (data.type) {
        case 'transcript':
            appendTranscript(data.role, data.text, data.is_final);
            break;
        case 'gesture_ack':
            showGestureAck(data.label);
            break;
        case 'visualizer':
            visualizerActive    = data.active;
            visualizerIntensity = data.intensity || 0;
            break;
        case 'audio':
            enqueueAudio(data.data);
            break;
        case 'connected':
            appendTranscript('system', 'Connected to Rafi');
            break;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Transcript
// ═══════════════════════════════════════════════════════════════════════════════

function appendTranscript(role, text, isFinal = true) {
    if (!isFinal) {
        const prev = transcript.querySelector('.interim');
        if (prev) prev.remove();
    }

    const el    = document.createElement('div');
    const label = role === 'assistant' ? 'RAFI' : role === 'user' ? 'YOU' : 'SYS';
    el.className = `transcript-entry ${role}` + (isFinal ? '' : ' interim');
    el.innerHTML = `<span class="role">&gt; ${label}:</span> ${escapeHtml(text)}`;
    transcript.appendChild(el);
    transcript.scrollTop = transcript.scrollHeight;
}

function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Camera & Gesture Recognition
// ═══════════════════════════════════════════════════════════════════════════════

async function toggleCamera() {
    if (cameraStream) {
        // Stop camera
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
        camPreview.srcObject = null;
        camSection.classList.add('hidden');
        cameraBtn.classList.remove('active');
        cameraBadge.textContent = 'CAM OFF';
        cameraBadge.className   = 'badge';
        return;
    }

    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false,
        });

        camPreview.srcObject = cameraStream;
        camSection.classList.remove('hidden');
        cameraBtn.classList.add('active');
        cameraBadge.textContent = 'CAM ON';
        cameraBadge.className   = 'badge active';

        // Load gesture model on first camera activation
        if (!gestureRecognizer) {
            gestLabel.textContent = 'Loading gesture model...';
            await initGestureRecognizer();
        }

        detectGestures();
    } catch (err) {
        console.error('Camera access failed:', err);
        gestLabel.textContent = 'Camera access denied';
    }
}

async function initGestureRecognizer() {
    try {
        const { GestureRecognizer, FilesetResolver } = await import(
            'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/+esm'
        );

        const vision = await FilesetResolver.forVisionTasks(
            'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm'
        );

        gestureRecognizer = await GestureRecognizer.createFromOptions(vision, {
            baseOptions: {
                modelAssetPath:
                    'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task',
                delegate: 'GPU',
            },
            runningMode: 'VIDEO',
            numHands: 1,
        });

        console.log('GestureRecognizer ready');
    } catch (err) {
        console.error('MediaPipe init failed:', err);
        gestLabel.textContent = 'Gesture model unavailable';
    }
}

function detectGestures() {
    if (!cameraStream || !gestureRecognizer) return;

    const video = camPreview;
    if (video.readyState < 2) {
        requestAnimationFrame(detectGestures);
        return;
    }

    const result = gestureRecognizer.recognizeForVideo(video, performance.now());

    if (result.gestures && result.gestures.length > 0) {
        const top = result.gestures[0][0];
        const name       = top.categoryName;
        const confidence = top.score;

        if (name !== 'None' && confidence > 0.65) {
            gestLabel.textContent = `${gestureEmoji(name)} ${name} (${(confidence * 100).toFixed(0)}%)`;
            gestLabel.classList.add('detected');

            // Cooldown — don't spam the server
            const now = Date.now();
            if (now - lastGestureTime > GESTURE_COOLDOWN_MS) {
                lastGestureTime = now;
                send({ type: 'gesture', gesture: name, confidence });
            }
        } else {
            gestLabel.textContent = 'No gesture';
            gestLabel.classList.remove('detected');
        }
    } else {
        gestLabel.textContent = 'No gesture';
        gestLabel.classList.remove('detected');
    }

    // Hand landmark overlay
    if (result.landmarks && result.landmarks.length > 0) {
        drawHandLandmarks(result.landmarks[0]);
    } else {
        const ctx = gestCanvas.getContext('2d');
        ctx.clearRect(0, 0, gestCanvas.width, gestCanvas.height);
    }

    if (cameraStream) requestAnimationFrame(detectGestures);
}

// ── Hand landmark drawing ────────────────────────────────────────────────────

const HAND_CONNECTIONS = [
    [0,1],[1,2],[2,3],[3,4],
    [0,5],[5,6],[6,7],[7,8],
    [0,9],[9,10],[10,11],[11,12],
    [0,13],[13,14],[14,15],[15,16],
    [0,17],[17,18],[18,19],[19,20],
    [5,9],[9,13],[13,17],
];

function drawHandLandmarks(landmarks) {
    const canvas = gestCanvas;
    const ctx    = canvas.getContext('2d');

    canvas.width  = camPreview.videoWidth  || 640;
    canvas.height = camPreview.videoHeight || 480;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Connections
    ctx.strokeStyle = `rgb(${COLORS.accentCyan.join(',')})`;
    ctx.lineWidth   = 2;
    for (const [a, b] of HAND_CONNECTIONS) {
        ctx.beginPath();
        ctx.moveTo(landmarks[a].x * canvas.width, landmarks[a].y * canvas.height);
        ctx.lineTo(landmarks[b].x * canvas.width, landmarks[b].y * canvas.height);
        ctx.stroke();
    }

    // Points
    ctx.fillStyle = `rgb(${COLORS.accentBright.join(',')})`;
    for (const lm of landmarks) {
        ctx.beginPath();
        ctx.arc(lm.x * canvas.width, lm.y * canvas.height, 4, 0, Math.PI * 2);
        ctx.fill();
    }
}

function gestureEmoji(name) {
    return {
        Thumb_Up:    '\u{1F44D}',
        Thumb_Down:  '\u{1F44E}',
        Open_Palm:   '\u270B',
        Closed_Fist: '\u270A',
        Victory:     '\u270C\uFE0F',
        Pointing_Up: '\u261D\uFE0F',
        ILoveYou:    '\u{1F91F}',
    }[name] || '\u{1F91A}';
}

function showGestureAck(label) {
    const el = document.createElement('div');
    el.className   = 'gesture-ack';
    el.textContent = label;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2000);
}

// ═══════════════════════════════════════════════════════════════════════════════
// RAFI Visualizer (Canvas — port of RafiVisualizer.paintEvent)
// ═══════════════════════════════════════════════════════════════════════════════

function drawVisualizer() {
    const canvas = vizCanvas;
    const ctx    = canvas.getContext('2d');
    const dpr    = window.devicePixelRatio || 1;
    const rect   = canvas.getBoundingClientRect();

    canvas.width  = rect.width  * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w   = rect.width;
    const h   = rect.height;
    const cx  = w / 2;
    const cy  = h / 2;
    const dim = Math.min(w, h);

    visualizerTime += 0.03;
    ctx.clearRect(0, 0, w, h);

    const baseRadius = dim * 0.25;
    const radius = visualizerActive
        ? baseRadius + visualizerIntensity * dim * 0.06
        : baseRadius + Math.sin(visualizerTime * 2.0) * dim * 0.015;

    // Outer ambient glow
    const glowR = radius * 2.0;
    const grad  = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
    grad.addColorStop(0,   'rgba(6,182,212,0.12)');
    grad.addColorStop(0.5, 'rgba(6,182,212,0.04)');
    grad.addColorStop(1,   'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
    ctx.fill();

    // Inner halo
    const haloR = radius * 1.3;
    const hAlpha = visualizerActive ? 0.31 : 0.20;
    const hGrad  = ctx.createRadialGradient(cx, cy, 0, cx, cy, haloR);
    hGrad.addColorStop(0,   `rgba(34,211,238,${hAlpha})`);
    hGrad.addColorStop(0.7, `rgba(34,211,238,${hAlpha / 3})`);
    hGrad.addColorStop(1,   'rgba(0,0,0,0)');
    ctx.fillStyle = hGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, haloR, 0, Math.PI * 2);
    ctx.fill();

    // Main circle
    ctx.strokeStyle = `rgba(34,211,238,${visualizerActive ? 0.78 : 0.51})`;
    ctx.lineWidth   = visualizerActive ? 2.5 : 1.8;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();

    // Outer ring
    ctx.strokeStyle = 'rgba(6,182,212,0.16)';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 1.12, 0, Math.PI * 2);
    ctx.stroke();

    // "RAFI" text
    const fontSize = Math.max(16, dim * 0.09);
    ctx.font      = `bold ${fontSize}px 'Segoe UI', 'Helvetica Neue', sans-serif`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';

    // Glow layer
    ctx.fillStyle = 'rgba(34,211,238,0.63)';
    ctx.fillText('RAFI', cx, cy);
    // Crisp layer
    ctx.fillStyle = 'rgba(224,243,255,0.94)';
    ctx.fillText('RAFI', cx, cy);

    // Orbiting dot
    const orbitR = radius * 1.06;
    const angle  = visualizerTime * 1.5;
    ctx.fillStyle = 'rgba(34,211,238,0.7)';
    ctx.beginPath();
    ctx.arc(cx + orbitR * Math.cos(angle), cy + orbitR * Math.sin(angle), 3, 0, Math.PI * 2);
    ctx.fill();

    animFrameId = requestAnimationFrame(drawVisualizer);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Microphone & Speech Recognition (Web Speech API)
// ═══════════════════════════════════════════════════════════════════════════════

function toggleMic() {
    if (micActive) {
        stopListening();
    } else {
        startListening();
    }
}

function startListening() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        appendTranscript('system', 'Speech recognition not supported in this browser');
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (event) => {
        let finalText = '';
        let interimText = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const t = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalText += t;
            } else {
                interimText += t;
            }
        }

        if (interimText) {
            appendTranscript('user', interimText, false);
        }

        if (finalText) {
            appendTranscript('user', finalText, true);
            send({ type: 'voice_text', text: finalText });
        }
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        if (event.error === 'not-allowed') {
            appendTranscript('system', 'Microphone access denied');
            micActive = false;
            micBtn.classList.remove('active');
            voiceBadge.textContent = 'CONNECTED';
            voiceBadge.className = 'badge connected';
        }
    };

    recognition.onend = () => {
        // Auto-restart if mic is still active (browser may stop on silence)
        if (micActive) {
            try { recognition.start(); }
            catch (_) { /* already started */ }
        }
    };

    try {
        recognition.start();
        micActive = true;
        micBtn.classList.add('active');
        voiceBadge.textContent = 'LISTENING';
        voiceBadge.className = 'badge listening';
        appendTranscript('system', 'Listening...');
    } catch (err) {
        console.error('Failed to start speech recognition:', err);
    }
}

function stopListening() {
    micActive = false;
    if (recognition) {
        recognition.stop();
        recognition = null;
    }
    micBtn.classList.remove('active');
    voiceBadge.textContent = 'CONNECTED';
    voiceBadge.className = 'badge connected';
}

// ═══════════════════════════════════════════════════════════════════════════════
// Audio Playback (TTS from server)
// ═══════════════════════════════════════════════════════════════════════════════

function enqueueAudio(base64Data) {
    audioQueue.push(base64Data);
    if (!audioPlaying) playNextAudio();
}

function playNextAudio() {
    if (audioQueue.length === 0) {
        audioPlaying = false;
        visualizerActive = false;
        return;
    }

    audioPlaying = true;
    visualizerActive = true;
    visualizerIntensity = 0.6;

    const b64 = audioQueue.shift();
    const audio = new Audio(`data:audio/mpeg;base64,${b64}`);

    audio.onended = () => {
        visualizerIntensity = 0;
        playNextAudio();
    };

    audio.onerror = () => {
        console.error('Audio playback failed');
        playNextAudio();
    };

    audio.play().catch((err) => {
        console.error('Audio play blocked:', err);
        // Browsers may block autoplay — show a hint
        appendTranscript('system', 'Tap the screen to enable audio playback');
        audioPlaying = false;
        visualizerActive = false;
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// Text Input
// ═══════════════════════════════════════════════════════════════════════════════

textInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const text = textInput.value.trim();
    if (!text) return;

    appendTranscript('user', text);
    send({ type: 'text', message: text });
    textInput.value = '';
});

// ═══════════════════════════════════════════════════════════════════════════════
// Button Handlers
// ═══════════════════════════════════════════════════════════════════════════════

micBtn.addEventListener('click', toggleMic);
cameraBtn.addEventListener('click', toggleCamera);

// ═══════════════════════════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════════════════════════

connectWebSocket();
drawVisualizer();
