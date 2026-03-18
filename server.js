// ============================================
// HiLook / Hikvision RTSP Camera Integration
// Express server cu ffmpeg pentru:
//   - Live MJPEG stream in browser
//   - Snapshot (captură JPG din RTSP)
//   - Auto-reconnect la pierderea streamului
// ============================================

require("dotenv").config();
const express = require("express");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

// ---- Cale absolută ffmpeg (funcționează indiferent de PATH) ----
const FFMPEG_PATH = process.env.FFMPEG_PATH || "C:\\ffmpeg\\ffmpeg-8.0.1-essentials_build\\bin\\ffmpeg.exe";

const app = express();

// ---- Middleware ----
app.use(express.json()); // pentru POST/DELETE cu body
app.use(express.urlencoded({ extended: true }));

// ---- Configurare din .env ----
const CAMERA_IP = process.env.CAMERA_IP || "192.168.100.105";
const CAMERA_USERNAME = process.env.CAMERA_USERNAME || "admin";
const CAMERA_PASSWORD = process.env.CAMERA_PASSWORD || "Ghilezan19@";
const CAMERA_RTSP_PORT = process.env.CAMERA_RTSP_PORT || "554";
const RTSP_MAIN_PATH = process.env.RTSP_MAIN_PATH || "/Streaming/channels/101";
const RTSP_SUB_PATH = process.env.RTSP_SUB_PATH || "/Streaming/channels/102";

// Camera 2 PTZ
const CAMERA2_IP = process.env.CAMERA2_IP || "192.168.100.106";
const CAMERA2_USERNAME = process.env.CAMERA2_USERNAME || "admin";
const CAMERA2_PASSWORD = process.env.CAMERA2_PASSWORD || process.env.CAMERA_PASSWORD || "Ghilezan19@";
const CAMERA2_RTSP_PORT = process.env.CAMERA2_RTSP_PORT || "554";
const CAMERA2_HTTP_PORT = process.env.CAMERA2_HTTP_PORT || "80";
const CAMERA2_SDK_PORT = process.env.CAMERA2_SDK_PORT || "8000";
const RTSP2_MAIN_PATH = process.env.RTSP2_MAIN_PATH || "/Streaming/channels/101";
const RTSP2_SUB_PATH = process.env.RTSP2_SUB_PATH || "/Streaming/channels/102";

const SERVER_PORT = parseInt(process.env.SERVER_PORT || "3000", 10);
const SNAPSHOT_DIR = process.env.SNAPSHOT_DIR || "./snapshots";

// ---- Encodare parolă pentru URL RTSP (@ -> %40, etc.) ----
function encodeRtspPassword(password) {
  return encodeURIComponent(password);
}

// ---- Construiește URL RTSP complet ----
function buildRtspUrl(streamPath) {
  const encodedPassword = encodeRtspPassword(CAMERA_PASSWORD);
  return `rtsp://${CAMERA_USERNAME}:${encodedPassword}@${CAMERA_IP}:${CAMERA_RTSP_PORT}${streamPath}`;
}

const RTSP_MAIN_URL = buildRtspUrl(RTSP_MAIN_PATH);
const RTSP_SUB_URL = buildRtspUrl(RTSP_SUB_PATH);

// ---- Camera 2 PTZ URL-uri ----
function buildRtspUrl2(streamPath) {
  const encodedPassword = encodeRtspPassword(CAMERA2_PASSWORD);
  return `rtsp://${CAMERA2_USERNAME}:${encodedPassword}@${CAMERA2_IP}:${CAMERA2_RTSP_PORT}${streamPath}`;
}

const RTSP2_MAIN_URL = buildRtspUrl2(RTSP2_MAIN_PATH);
const RTSP2_SUB_URL = buildRtspUrl2(RTSP2_SUB_PATH);

// ---- PTZ HTTP URL ----
function buildPtzUrl(endpoint) {
  const encodedPassword = encodeRtspPassword(CAMERA2_PASSWORD);
  return `http://${CAMERA2_USERNAME}:${encodedPassword}@${CAMERA2_IP}:${CAMERA2_HTTP_PORT}${endpoint}`;
}

const RECORDINGS_DIR = process.env.RECORDINGS_DIR || "./recordings";

// ---- Creare foldere dacă nu există ----
if (!fs.existsSync(SNAPSHOT_DIR)) {
  fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });
  console.log(`[INFO] Folder creat: ${SNAPSHOT_DIR}`);
}
if (!fs.existsSync(RECORDINGS_DIR)) {
  fs.mkdirSync(RECORDINGS_DIR, { recursive: true });
  console.log(`[INFO] Folder creat: ${RECORDINGS_DIR}`);
}

// ---- State înregistrare (un singur proces activ la un moment dat) ----
let recordingProcess = null;
let recordingMeta = null;

// ---- State cameră curentă ----
let currentCamera = 1; // 1 sau 2
let currentStreamProcess = null;
let currentRecordingProcess = null;

// ---- Servire fișiere statice (frontend) ----
app.use(express.static(path.join(__dirname, "public")));

// ---- Servire snapshots salvate ----
app.use("/snapshots", express.static(path.resolve(SNAPSHOT_DIR)));

// ---- Servire înregistrări ----
app.use("/recordings", express.static(path.resolve(RECORDINGS_DIR)));

// ============================================
// ENDPOINT: GET /api/stream
// Convertește RTSP -> MJPEG prin ffmpeg
// Query params:
//   ?camera=1|2 (default: 1)
//   ?quality=main|sub (default: sub pentru performanță)
//   ?fps=5 (default: 5, câte frame-uri pe secundă)
//   ?width=640 (opțional, resize)
// ============================================
app.get("/api/stream", (req, res) => {
  const camera = parseInt(req.query.camera || "1", 10);
  const quality = req.query.quality === "main" ? "main" : "sub";
  const fps = parseInt(req.query.fps || "5", 10);
  const width = req.query.width ? parseInt(req.query.width, 10) : null;
  
  const rtspUrl = camera === 2 
    ? (quality === "main" ? RTSP2_MAIN_URL : RTSP2_SUB_URL)
    : (quality === "main" ? RTSP_MAIN_URL : RTSP_SUB_URL);
  
  currentCamera = camera;
  console.log(`[STREAM] Camera ${camera} - ${quality} @ ${fps}fps`);

  console.log(`[STREAM] Start stream ${quality} @ ${fps}fps`);

  // Construim argumentele ffmpeg
  const ffmpegArgs = [
    // Input options
    "-rtsp_transport", "tcp",       // TCP transport - mai stabil decât UDP
    "-timeout", "5000000",          // Timeout conexiune RTSP (ffmpeg 8.x - în microsecunde)
    "-i", rtspUrl,                  // URL-ul RTSP
    // Decodare explicită (camera folosește HEVC/H.265)
    "-vcodec", "mjpeg",             // Encoding output: MJPEG
    // Output options
    "-f", "mjpeg",                  // Format output: Motion JPEG
    "-q:v", "5",                    // Calitate JPEG (2=best, 31=worst, 5=bun)
    "-r", String(fps),              // Frame rate output
    "-an",                          // Fără audio
  ];

  // Adaugă resize dacă e specificat
  if (width) {
    ffmpegArgs.splice(ffmpegArgs.indexOf("-f"), 0, "-vf", `scale=${width}:-2`);
  }

  // Pipe output la stdout
  ffmpegArgs.push("pipe:1");

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);

  // Header MJPEG - browserul știe să redea automat
  res.writeHead(200, {
    "Content-Type": "multipart/x-mixed-replace; boundary=ffmpeg",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Connection": "close",
  });

  // Buffer pentru a detecta granițele JPEG (SOI = FFD8, EOI = FFD9)
  let buffer = Buffer.alloc(0);

  ffmpeg.stdout.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);

    // Caută marcaje JPEG în buffer
    while (true) {
      // Caută Start Of Image (0xFFD8)
      const soiIndex = findMarker(buffer, 0xff, 0xd8);
      if (soiIndex === -1) break;

      // Caută End Of Image (0xFFD9) după SOI
      const eoiIndex = findMarker(buffer, 0xff, 0xd9, soiIndex + 2);
      if (eoiIndex === -1) break;

      // Extrage un frame JPEG complet
      const jpegFrame = buffer.slice(soiIndex, eoiIndex + 2);
      buffer = buffer.slice(eoiIndex + 2);

      // Trimite frame-ul ca parte MJPEG
      try {
        res.write(`--ffmpeg\r\n`);
        res.write(`Content-Type: image/jpeg\r\n`);
        res.write(`Content-Length: ${jpegFrame.length}\r\n\r\n`);
        res.write(jpegFrame);
        res.write("\r\n");
      } catch (err) {
        // Clientul s-a deconectat
        ffmpeg.kill("SIGTERM");
        return;
      }
    }
  });

  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    // Logăm doar erorile importante, nu tot outputul ffmpeg
    if (msg.includes("error") || msg.includes("Error") || msg.includes("Connection refused")) {
      console.error(`[STREAM ERROR] ${msg.trim()}`);
    }
  });

  ffmpeg.on("close", (code) => {
    console.log(`[STREAM] ffmpeg s-a oprit cu codul: ${code}`);
    if (!res.writableEnded) {
      res.end();
    }
  });

  ffmpeg.on("error", (err) => {
    console.error(`[STREAM] Eroare la pornirea ffmpeg: ${err.message}`);
    if (!res.headersSent) {
      res.status(500).json({ error: "Nu s-a putut porni ffmpeg. Verifică dacă ffmpeg este instalat." });
    }
  });

  // Oprește ffmpeg când clientul se deconectează
  req.on("close", () => {
    console.log("[STREAM] Client deconectat, opresc ffmpeg");
    ffmpeg.kill("SIGTERM");
  });
});

// ============================================
// ENDPOINT: GET /api/snapshot
// Captură un singur frame din RTSP și returnează JPG
// Query params:
//   ?camera=1|2 (default: 1)
//   ?quality=main|sub (default: main pentru calitate maximă)
//   ?save=true (opțional, salvează și pe disc)
//   ?filename=custom_name (opțional, nume fișier)
// ============================================
app.get("/api/snapshot", (req, res) => {
  const camera = parseInt(req.query.camera || "1", 10);
  const quality = req.query.quality === "sub" ? "sub" : "main";
  const shouldSave = req.query.save === "true";
  
  const rtspUrl = camera === 2 
    ? (quality === "main" ? RTSP2_MAIN_URL : RTSP2_SUB_URL)
    : (quality === "main" ? RTSP_MAIN_URL : RTSP_SUB_URL);
  
  console.log(`[SNAPSHOT] Camera ${camera} - ${quality}`);

  console.log(`[SNAPSHOT] Captură din stream ${quality}`);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "10000000",         // 10 secunde timeout (ffmpeg 8.x)
    "-i", rtspUrl,
    "-frames:v", "1",               // Doar 1 frame
    "-vcodec", "mjpeg",             // Forțează encoding MJPEG (camera e HEVC)
    "-f", "image2",                 // Format imagine
    "-q:v", "2",                    // Calitate maximă JPEG
    "-update", "1",                 // Necesar pentru pipe:1 cu image2 în ffmpeg 8.x
    "-y",                           // Overwrite output
    "pipe:1",                       // Output la stdout
  ];

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);
  const chunks = [];

  ffmpeg.stdout.on("data", (chunk) => {
    chunks.push(chunk);
  });

  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) {
      console.error(`[SNAPSHOT ERROR] ${msg.trim()}`);
    }
  });

  ffmpeg.on("close", (code) => {
    if (code !== 0 || chunks.length === 0) {
      console.error(`[SNAPSHOT] ffmpeg a eșuat cu codul: ${code}`);
      if (!res.headersSent) {
        return res.status(500).json({
          error: "Nu s-a putut captura snapshot-ul",
          details: "Verifică dacă camera este online și URL-ul RTSP este corect",
        });
      }
      return;
    }

    const imageBuffer = Buffer.concat(chunks);
    console.log(`[SNAPSHOT] Capturat ${imageBuffer.length} bytes`);

    // Salvare pe disc dacă e cerut
    if (shouldSave) {
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filename = req.query.filename || `snapshot_${timestamp}`;
      const filepath = path.join(SNAPSHOT_DIR, `${filename}.jpg`);
      fs.writeFileSync(filepath, imageBuffer);
      console.log(`[SNAPSHOT] Salvat: ${filepath}`);
    }

    // Returnează imaginea
    res.writeHead(200, {
      "Content-Type": "image/jpeg",
      "Content-Length": imageBuffer.length,
      "Content-Disposition": shouldSave ? "attachment; filename=snapshot.jpg" : "inline",
    });
    res.end(imageBuffer);
  });

  ffmpeg.on("error", (err) => {
    console.error(`[SNAPSHOT] Eroare la pornirea ffmpeg: ${err.message}`);
    if (!res.headersSent) {
      res.status(500).json({
        error: "Nu s-a putut porni ffmpeg",
        details: err.message,
      });
    }
  });

  // Timeout safety - dacă ffmpeg nu răspunde în 15 secunde
  const timeout = setTimeout(() => {
    ffmpeg.kill("SIGTERM");
    if (!res.headersSent) {
      res.status(504).json({ error: "Timeout la captarea snapshot-ului" });
    }
  }, 15000);

  ffmpeg.on("close", () => clearTimeout(timeout));
});

// ============================================
// ENDPOINT: GET /api/snapshot/save
// Salvează snapshot pe disc și returnează path-ul
// ============================================
app.get("/api/snapshot/save", (req, res) => {
  const quality = req.query.quality === "sub" ? "sub" : "main";
  const rtspUrl = quality === "main" ? RTSP_MAIN_URL : RTSP_SUB_URL;
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = req.query.filename || `snapshot_${timestamp}`;
  const filepath = path.resolve(SNAPSHOT_DIR, `${filename}.jpg`);

  console.log(`[SNAPSHOT SAVE] Salvare în: ${filepath}`);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "10000000",
    "-i", rtspUrl,
    "-frames:v", "1",
    "-vcodec", "mjpeg",             // Forțează encoding MJPEG (camera e HEVC)
    "-q:v", "2",
    "-y",
    filepath,
  ];

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);

  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) {
      console.error(`[SNAPSHOT SAVE ERROR] ${msg.trim()}`);
    }
  });

  ffmpeg.on("close", (code) => {
    if (code !== 0 || !fs.existsSync(filepath)) {
      return res.status(500).json({ error: "Nu s-a putut salva snapshot-ul" });
    }

    const stats = fs.statSync(filepath);
    res.json({
      success: true,
      filename: `${filename}.jpg`,
      path: filepath,
      size: stats.size,
      url: `/snapshots/${filename}.jpg`,
      timestamp: new Date().toISOString(),
    });
  });

  ffmpeg.on("error", (err) => {
    console.error(`[SNAPSHOT SAVE] Eroare: ${err.message}`);
    if (!res.headersSent) {
      res.status(500).json({ error: "ffmpeg nu a putut fi pornit", details: err.message });
    }
  });
});

// ============================================
// ENDPOINT: GET /api/snapshots
// Listează toate snapshot-urile salvate
// ============================================
app.get("/api/snapshots", (req, res) => {
  try {
    const files = fs.readdirSync(SNAPSHOT_DIR)
      .filter((f) => /\.(jpg|jpeg|png)$/i.test(f))
      .map((f) => {
        const stats = fs.statSync(path.join(SNAPSHOT_DIR, f));
        return {
          filename: f,
          url: `/snapshots/${f}`,
          size: stats.size,
          created: stats.birthtime,
        };
      })
      .sort((a, b) => new Date(b.created) - new Date(a.created));

    res.json({ count: files.length, files });
  } catch (err) {
    res.status(500).json({ error: "Nu s-a putut citi folderul de snapshots" });
  }
});

// ============================================
// ENDPOINT: GET /api/status
// Verifică dacă camera răspunde pe RTSP
// ============================================
app.get("/api/status", (req, res) => {
  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "5000000",
    "-i", RTSP_MAIN_URL,
    "-frames:v", "1",
    "-f", "null",
    "-",
  ];

  const startTime = Date.now();
  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);
  let stderr = "";

  ffmpeg.stderr.on("data", (data) => {
    stderr += data.toString();
  });

  ffmpeg.on("close", (code) => {
    const elapsed = Date.now() - startTime;
    const isOnline = code === 0 || stderr.includes("Video:");

    // Extrage info despre stream din outputul ffmpeg
    const videoInfo = stderr.match(/Video:\s+([^\n]+)/);
    const audioInfo = stderr.match(/Audio:\s+([^\n]+)/);

    res.json({
      camera: {
        ip: CAMERA_IP,
        online: isOnline,
        responseTime: `${elapsed}ms`,
        mainStream: RTSP_MAIN_PATH,
        subStream: RTSP_SUB_PATH,
      },
      stream: {
        video: videoInfo ? videoInfo[1].trim() : null,
        audio: audioInfo ? audioInfo[1].trim() : null,
      },
    });
  });

  // Timeout de 10 secunde
  setTimeout(() => {
    ffmpeg.kill("SIGTERM");
  }, 10000);
});

// ============================================
// ENDPOINT: POST /api/record/start
// Pornește înregistrarea RTSP -> MP4 pe disc
// Query params: ?camera=1|2&quality=main|sub
// ============================================
app.post("/api/record/start", (req, res) => {
  if (recordingProcess) {
    return res.status(409).json({ error: "O înregistrare este deja în curs", recording: recordingMeta });
  }

  const camera = parseInt(req.query.camera || "1", 10);
  const quality = (req.query.quality || "main");
  const rtspUrl = camera === 2 
    ? (quality === "sub" ? RTSP2_SUB_URL : RTSP2_MAIN_URL)
    : (quality === "sub" ? RTSP_SUB_URL : RTSP_MAIN_URL);
  
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `cam${camera}_${timestamp}.mp4`;
  const filepath = path.resolve(RECORDINGS_DIR, filename);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "5000000",
    "-i", rtspUrl,
    "-c:v", "libx264",                // Encode HEVC -> H.264 (MP4 compatible)
    "-preset", "ultrafast",            // Very fast encoding for live capture
    "-crf", "18",                      // High quality (18 = very good, 23 = good, 28 = acceptable)
    "-pix_fmt", "yuv420p",             // Ensure pixel format compatibility
    "-movflags", "+faststart",         // Optimize for web playback
    "-r", "25",                        // Force 25fps output
    "-c:a", "aac",                     // Encode audio to AAC (more compatible than copy)
    "-ar", "16000",                    // Audio sample rate
    "-f", "mp4",
    "-y",
    filepath,
  ];

  recordingProcess = spawn(FFMPEG_PATH, ffmpegArgs);
  recordingMeta = {
    filename,
    filepath,
    quality,
    startedAt: new Date().toISOString(),
    startTs: Date.now(),
  };

  recordingProcess.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) {
      console.error(`[RECORD ERROR] ${msg.trim()}`);
    }
  });

  recordingProcess.on("close", (code) => {
    console.log(`[RECORD] ffmpeg înregistrare oprit, cod: ${code}`);
    recordingProcess = null;
    recordingMeta = null;
  });

  recordingProcess.on("error", (err) => {
    console.error(`[RECORD] Eroare pornire ffmpeg: ${err.message}`);
    recordingProcess = null;
    recordingMeta = null;
  });

  console.log(`[RECORD] Înregistrare pornită: ${filename}`);
  res.json({
    success: true,
    message: "Înregistrarea a pornit",
    filename,
    quality,
    startedAt: recordingMeta.startedAt,
  });
});

// ============================================
// ENDPOINT: POST /api/record/stop
// Oprește înregistrarea curentă
// ============================================
app.post("/api/record/stop", (req, res) => {
  if (!recordingProcess) {
    return res.status(400).json({ error: "Nu există nicio înregistrare activă" });
  }

  const meta = { ...recordingMeta };
  const duration = Math.floor((Date.now() - meta.startTs) / 1000);

  // Trimitem 'q' pe stdin pentru oprire curată (ffmpeg flush + finalizare MP4)
  recordingProcess.stdin.write("q");

  // Forțăm SIGTERM după 3 secunde dacă nu s-a oprit
  const forceKill = setTimeout(() => {
    if (recordingProcess) {
      recordingProcess.kill("SIGTERM");
    }
  }, 3000);

  recordingProcess.on("close", () => {
    clearTimeout(forceKill);
    const fileExists = fs.existsSync(meta.filepath);
    const fileSize = fileExists ? fs.statSync(meta.filepath).size : 0;
    console.log(`[RECORD] Înregistrare salvată: ${meta.filename} (${(fileSize / 1024 / 1024).toFixed(2)} MB, ${duration}s)`);
  });

  res.json({
    success: true,
    message: "Înregistrarea s-a oprit",
    filename: meta.filename,
    duration: `${duration}s`,
    url: `/recordings/${meta.filename}`,
    downloadUrl: `/api/recordings/${meta.filename}`,
  });
});

// ============================================
// ENDPOINT: GET /api/record/status
// Returnează statusul înregistrării curente
// ============================================
app.get("/api/record/status", (req, res) => {
  if (!recordingProcess) {
    return res.json({ recording: false });
  }
  const duration = Math.floor((Date.now() - recordingMeta.startTs) / 1000);
  res.json({
    recording: true,
    filename: recordingMeta.filename,
    quality: recordingMeta.quality,
    startedAt: recordingMeta.startedAt,
    duration,
  });
});

// ============================================
// ENDPOINT: GET /api/recordings
// Listează toate înregistrările salvate
// ============================================
app.get("/api/recordings", (req, res) => {
  try {
    const files = fs.readdirSync(RECORDINGS_DIR)
      .filter((f) => /\.mp4$/i.test(f))
      .map((f) => {
        const stats = fs.statSync(path.join(RECORDINGS_DIR, f));
        return {
          filename: f,
          url: `/recordings/${f}`,
          downloadUrl: `/api/recordings/${f}`,
          size: stats.size,
          sizeMB: (stats.size / 1024 / 1024).toFixed(2),
          created: stats.birthtime,
        };
      })
      .sort((a, b) => new Date(b.created) - new Date(a.created));

    res.json({ count: files.length, files });
  } catch (err) {
    res.status(500).json({ error: "Nu s-a putut citi folderul de înregistrări" });
  }
});

// ============================================
// ENDPOINT: GET /api/recordings/:filename
// Download înregistrare
// ============================================
app.get("/api/recordings/:filename", (req, res) => {
  const filename = path.basename(req.params.filename); // sanitizare path traversal
  const filepath = path.resolve(RECORDINGS_DIR, filename);

  if (!fs.existsSync(filepath)) {
    return res.status(404).json({ error: "Fișierul nu există" });
  }

  const stat = fs.statSync(filepath);
  res.setHeader("Content-Type", "video/mp4");
  res.setHeader("Content-Length", stat.size);
  res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
  fs.createReadStream(filepath).pipe(res);
});

// ============================================
// ENDPOINT: POST /api/recordings/:filename/delete
// Șterge o înregistrare de pe disc (folosim POST pentru compatibilitate fetch)
// ============================================
app.post("/api/recordings/:filename/delete", (req, res) => {
  const filename = path.basename(req.params.filename);
  const filepath = path.resolve(RECORDINGS_DIR, filename);

  if (!fs.existsSync(filepath)) {
    return res.status(404).json({ error: "Fișierul nu există" });
  }

  try {
    fs.unlinkSync(filepath);
    console.log(`[RECORD] Șters: ${filename}`);
    res.json({ success: true, message: `${filename} șters` });
  } catch (err) {
    console.error(`[RECORD] Eroare ștergere: ${err.message}`);
    res.status(500).json({ error: "Nu s-a putut șterge fișierul", details: err.message });
  }
});

// ============================================
// ENDPOINT: POST /api/ptz/move
// PTZ movement control
// Body: { direction: "up|down|left|right|up-left|up-right|down-left|down-right", speed: 1-7 }
// ============================================
app.post("/api/ptz/move", (req, res) => {
  const { direction = "up", speed = 5 } = req.body;
  const speedNum = Math.max(1, Math.min(7, parseInt(speed) || 5));
  
  // PTZ command mapping for HiLook/Hikvision
  const ptzCommands = {
    "up": "0",
    "down": "1", 
    "left": "2",
    "right": "3",
    "up-left": "4",
    "up-right": "5",
    "down-left": "6",
    "down-right": "7"
  };
  
  const cmd = ptzCommands[direction];
  if (!cmd) {
    return res.status(400).json({ error: "Direcție invalidă" });
  }
  
  const ptzUrl = buildPtzUrl(`/PTZCtrl/channels/101/ptz/${cmd}?speed=${speedNum}`);
  console.log(`[PTZ] Move: ${direction} speed=${speedNum} -> ${ptzUrl}`);
  
  // Use POST method for PTZ control with HiLook/Hikvision API
  const http = require("http");
  const postData = "";
  const options = {
    hostname: CAMERA2_IP,
    port: CAMERA2_HTTP_PORT,
    path: `/PTZCtrl/channels/101/ptz/${cmd}?speed=${speedNum}`,
    method: "PUT", // HiLook uses PUT for PTZ control
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    },
    timeout: 5000
  };
  
  const reqPTZ = http.request(options, (response) => {
    let data = "";
    response.on("data", (chunk) => data += chunk);
    response.on("end", () => {
      console.log(`[PTZ] Move response: ${response.statusCode} - ${data}`);
      if (response.statusCode === 200 || response.statusCode === 201) {
        res.json({ success: true, direction, speed: speedNum });
      } else {
        res.status(response.statusCode).json({ 
          error: "PTZ command failed", 
          status: response.statusCode,
          details: data 
        });
      }
    });
  });
  
  reqPTZ.on("error", (err) => {
    console.error(`[PTZ] Error: ${err.message}`);
    res.status(500).json({ error: "PTZ connection failed", details: err.message });
  });
  
  reqPTZ.on("timeout", () => {
    reqPTZ.destroy();
    res.status(500).json({ error: "PTZ timeout" });
  });
  
  reqPTZ.write(postData);
  reqPTZ.end();
});

// ============================================
// ENDPOINT: POST /api/ptz/stop
// Stop PTZ movement
// ============================================
app.post("/api/ptz/stop", (req, res) => {
  console.log("[PTZ] Stop movement");
  
  const http = require("http");
  const postData = "";
  const options = {
    hostname: CAMERA2_IP,
    port: CAMERA2_HTTP_PORT,
    path: "/PTZCtrl/channels/101/ptz/stop",
    method: "POST",
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    },
    timeout: 5000
  };
  
  const reqPTZ = http.request(options, (response) => {
    let data = "";
    response.on("data", (chunk) => data += chunk);
    response.on("end", () => {
      console.log(`[PTZ] Stop response: ${response.statusCode} - ${data}`);
      if (response.statusCode === 200 || response.statusCode === 201) {
        res.json({ success: true });
      } else {
        res.status(response.statusCode).json({ error: "PTZ stop failed", details: data });
      }
    });
  });
  
  reqPTZ.on("error", (err) => {
    console.error(`[PTZ] Stop error: ${err.message}`);
    res.status(500).json({ error: "PTZ stop failed", details: err.message });
  });
  
  reqPTZ.on("timeout", () => {
    reqPTZ.destroy();
    res.status(500).json({ error: "PTZ timeout" });
  });
  
  reqPTZ.write(postData);
  reqPTZ.end();
});

// ============================================
// ENDPOINT: POST /api/ptz/goto
// Go to preset position
// Body: { preset: 1-255 }
// ============================================
app.post("/api/ptz/goto", (req, res) => {
  const preset = parseInt(req.body.preset) || 1;
  const presetNum = Math.max(1, Math.min(255, preset));
  
  console.log(`[PTZ] Goto preset: ${presetNum}`);
  
  const http = require("http");
  const postData = "";
  const options = {
    hostname: CAMERA2_IP,
    port: CAMERA2_HTTP_PORT,
    path: `/PTZCtrl/channels/101/presets/${presetNum}/goto`,
    method: "POST",
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    },
    timeout: 5000
  };
  
  const reqPTZ = http.request(options, (response) => {
    let data = "";
    response.on("data", (chunk) => data += chunk);
    response.on("end", () => {
      console.log(`[PTZ] Goto response: ${response.statusCode} - ${data}`);
      if (response.statusCode === 200 || response.statusCode === 201) {
        res.json({ success: true, preset: presetNum });
      } else {
        res.status(response.statusCode).json({ error: "PTZ goto failed", details: data });
      }
    });
  });
  
  reqPTZ.on("error", (err) => {
    console.error(`[PTZ] Goto error: ${err.message}`);
    res.status(500).json({ error: "PTZ goto failed", details: err.message });
  });
  
  reqPTZ.on("timeout", () => {
    reqPTZ.destroy();
    res.status(500).json({ error: "PTZ timeout" });
  });
  
  reqPTZ.write(postData);
  reqPTZ.end();
});

// ============================================
// ENDPOINT: POST /api/ptz/position
// Go to absolute position
// Body: { x: 0-360, y: 0-180, zoom: 1-10 }
// ============================================
app.post("/api/ptz/position", (req, res) => {
  const { x = 0, y = 0, zoom = 1 } = req.body;
  const xPos = Math.max(0, Math.min(360, parseFloat(x) || 0));
  const yPos = Math.max(0, Math.min(180, parseFloat(y) || 0));
  const zoomLevel = Math.max(1, Math.min(10, parseFloat(zoom) || 1));
  
  console.log(`[PTZ] Position: x=${xPos}, y=${yPos}, zoom=${zoomLevel}`);
  
  const http = require("http");
  const postData = "";
  const options = {
    hostname: CAMERA2_IP,
    port: CAMERA2_HTTP_PORT,
    path: `/PTZCtrl/channels/101/ptzpos?x=${xPos}&y=${yPos}&zoom=${zoomLevel}`,
    method: "POST",
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    },
    timeout: 5000
  };
  
  const reqPTZ = http.request(options, (response) => {
    let data = "";
    response.on("data", (chunk) => data += chunk);
    response.on("end", () => {
      console.log(`[PTZ] Position response: ${response.statusCode} - ${data}`);
      if (response.statusCode === 200 || response.statusCode === 201) {
        res.json({ success: true, position: { x: xPos, y: yPos, zoom: zoomLevel } });
      } else {
        res.status(response.statusCode).json({ error: "PTZ position failed", details: data });
      }
    });
  });
  
  reqPTZ.on("error", (err) => {
    console.error(`[PTZ] Position error: ${err.message}`);
    res.status(500).json({ error: "PTZ position failed", details: err.message });
  });
  
  reqPTZ.on("timeout", () => {
    reqPTZ.destroy();
    res.status(500).json({ error: "PTZ timeout" });
  });
  
  reqPTZ.write(postData);
  reqPTZ.end();
});

// ============================================
// ENDPOINT: GET /api/ptz/status
// Get PTZ status and position
// ============================================
app.get("/api/ptz/status", (req, res) => {
  const ptzUrl = buildPtzUrl("/PTZCtrl/channels/101/status");
  console.log("[PTZ] Get status");
  
  const http = require("http");
  const reqPTZ = http.get(ptzUrl, (response) => {
    let data = "";
    response.on("data", (chunk) => data += chunk);
    response.on("end", () => {
      try {
        // Try to parse XML response from camera
        res.json({ 
          success: true, 
          raw: data,
          // Note: Real parsing would need XML parser, returning raw for now
        });
      } catch (err) {
        res.json({ success: true, raw: data });
      }
    });
  });
  
  reqPTZ.on("error", (err) => {
    console.error(`[PTZ] Status error: ${err.message}`);
    res.status(500).json({ error: "PTZ status failed", details: err.message });
  });
});

// ============================================
// ENDPOINT: GET /api/diagnostic/camera2
// Diagnostic complet Camera 2 (PTZ)
// ============================================
app.get("/api/diagnostic/camera2", (req, res) => {
  const diagnostics = {
    camera: 2,
    config: {
      ip: CAMERA2_IP,
      username: CAMERA2_USERNAME,
      password: CAMERA2_PASSWORD ? "***" : "not set",
      rtspPort: CAMERA2_RTSP_PORT,
      httpPort: CAMERA2_HTTP_PORT,
      sdkPort: CAMERA2_SDK_PORT,
      mainPath: RTSP2_MAIN_PATH,
      subPath: RTSP2_SUB_PATH
    },
    urls: {
      rtspMain: buildRtspUrl2(RTSP2_MAIN_PATH),
      rtspSub: buildRtspUrl2(RTSP2_SUB_PATH),
      ptzMove: buildPtzUrl("/PTZCtrl/channels/101/ptz/0"),
      ptzStatus: buildPtzUrl("/PTZCtrl/channels/101/status")
    },
    tests: {}
  };

  // Test HTTP connectivity
  const http = require("http");
  const testHttp = (port, path, callback) => {
    const req = http.get({
      hostname: CAMERA2_IP,
      port: port,
      path: path,
      timeout: 3000
    }, (response) => {
      callback(null, {
        status: response.statusCode,
        statusText: response.statusMessage
      });
    });
    req.on('error', (err) => callback(err, null));
    req.on('timeout', () => {
      req.destroy();
      callback(new Error('Timeout'), null);
    });
  };

  // Run tests
  const tests = [
    { name: 'HTTP Port 80', port: CAMERA2_HTTP_PORT, path: '/' },
    { name: 'SDK Port 8000', port: CAMERA2_SDK_PORT, path: '/' },
    { name: 'PTZ Control', port: CAMERA2_HTTP_PORT, path: '/PTZCtrl/channels/101/status' }
  ];

  let completed = 0;
  tests.forEach(test => {
    testHttp(test.port, test.path, (err, result) => {
      diagnostics.tests[test.name] = err ? {
        success: false,
        error: err.message
      } : {
        success: true,
        status: result.status,
        statusText: result.statusText
      };
      
      completed++;
      if (completed === tests.length) {
        res.json(diagnostics);
      }
    });
  });
});

// ============================================
// ENDPOINT: DELETE /api/recordings/:filename (fallback)
// ============================================
app.delete("/api/recordings/:filename", (req, res) => {
  const filename = path.basename(req.params.filename);
  const filepath = path.resolve(RECORDINGS_DIR, filename);

  if (!fs.existsSync(filepath)) {
    return res.status(404).json({ error: "Fișierul nu există" });
  }

  try {
    fs.unlinkSync(filepath);
    console.log(`[RECORD] Șters: ${filename}`);
    res.json({ success: true, message: `${filename} șters` });
  } catch (err) {
    console.error(`[RECORD] Eroare ștergere: ${err.message}`);
    res.status(500).json({ error: "Nu s-a putut șterge fișierul", details: err.message });
  }
});

// ============================================
// ENDPOINT: GET /api/info
// Informații despre configurația serverului
// ============================================
app.get("/api/info", (req, res) => {
  res.json({
    server: {
      port: SERVER_PORT,
      version: "1.0.0",
    },
    camera: {
      ip: CAMERA_IP,
      rtspPort: CAMERA_RTSP_PORT,
      mainStream: RTSP_MAIN_PATH,
      subStream: RTSP_SUB_PATH,
    },
    endpoints: {
      stream: "/api/stream?quality=sub&fps=5",
      streamMain: "/api/stream?quality=main&fps=10",
      snapshot: "/api/snapshot",
      snapshotSave: "/api/snapshot/save",
      snapshotsList: "/api/snapshots",
      status: "/api/status",
      info: "/api/info",
    },
  });
});

// ---- Utilitar: Caută marker JPEG în buffer ----
function findMarker(buffer, byte1, byte2, startIndex = 0) {
  for (let i = startIndex; i < buffer.length - 1; i++) {
    if (buffer[i] === byte1 && buffer[i + 1] === byte2) {
      return i;
    }
  }
  return -1;
}

// ---- Pornire server ----
app.listen(SERVER_PORT, () => {
  console.log("============================================");
  console.log("  HiLook Camera Server - PORNIT");
  console.log("============================================");
  console.log(`  Server:      http://localhost:${SERVER_PORT}`);
  console.log(`  Camera IP:   ${CAMERA_IP}`);
  console.log(`  Main stream: ${RTSP_MAIN_PATH}`);
  console.log(`  Sub stream:  ${RTSP_SUB_PATH}`);
  console.log("--------------------------------------------");
  console.log("  Endpoints:");
  console.log(`    Live:      http://localhost:${SERVER_PORT}/api/stream`);
  console.log(`    Snapshot:  http://localhost:${SERVER_PORT}/api/snapshot`);
  console.log(`    Save:      http://localhost:${SERVER_PORT}/api/snapshot/save`);
  console.log(`    Status:    http://localhost:${SERVER_PORT}/api/status`);
  console.log(`    Info:      http://localhost:${SERVER_PORT}/api/info`);
  console.log("============================================");
});
