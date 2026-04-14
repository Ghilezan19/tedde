// ============================================
// HiLook / Hikvision RTSP Camera Integration
// Express server cu ffmpeg + ISAPI Digest Auth
// ============================================

require("dotenv").config();
const express = require("express");
const { spawn }  = require("child_process");
const path       = require("path");
const fs         = require("fs");
const http       = require("http");
const crypto     = require("crypto");
const { WebSocketServer } = require("ws");

// ---- ffmpeg path (per OS) ----
function resolveFFmpegPath() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH;
  switch (process.platform) {
    case "darwin": return "/opt/homebrew/bin/ffmpeg";
    case "linux":  return "/usr/bin/ffmpeg";
    case "win32":  return "C:\\ffmpeg\\ffmpeg-8.0.1-essentials_build\\bin\\ffmpeg.exe";
    default:       return "ffmpeg";
  }
}
const FFMPEG_PATH = resolveFFmpegPath();
console.log(`[INFO] ffmpeg path: ${FFMPEG_PATH}`);

// ---- Config from .env ----
const SERVER_PORT    = parseInt(process.env.SERVER_PORT    || "3000", 10);
const SNAPSHOT_DIR   = process.env.SNAPSHOT_DIR            || "./snapshots";
const RECORDINGS_DIR = process.env.RECORDINGS_DIR          || "./recordings";

const CAMERA_IP        = process.env.CAMERA_IP        || "192.168.100.105";
const CAMERA_USERNAME  = process.env.CAMERA_USERNAME  || "admin";
const CAMERA_PASSWORD  = process.env.CAMERA_PASSWORD  || "Ghilezan19@";
const CAMERA_RTSP_PORT = process.env.CAMERA_RTSP_PORT || "554";
const RTSP_MAIN_PATH   = process.env.RTSP_MAIN_PATH   || "/Streaming/channels/101";
const RTSP_SUB_PATH    = process.env.RTSP_SUB_PATH    || "/Streaming/channels/102";

const CAMERA2_IP        = process.env.CAMERA2_IP        || "10.112.50.88";
const CAMERA2_USERNAME  = process.env.CAMERA2_USERNAME  || "admin";
const CAMERA2_PASSWORD  = process.env.CAMERA2_PASSWORD  || process.env.CAMERA_PASSWORD || "DentaTimis02";
const CAMERA2_RTSP_PORT = process.env.CAMERA2_RTSP_PORT || "554";
const CAMERA2_HTTP_PORT = process.env.CAMERA2_HTTP_PORT || "80";
const CAMERA2_SDK_PORT  = process.env.CAMERA2_SDK_PORT  || "8000";
const RTSP2_MAIN_PATH   = process.env.RTSP2_MAIN_PATH   || "/Streaming/channels/101";
const RTSP2_SUB_PATH    = process.env.RTSP2_SUB_PATH    || "/Streaming/channels/102";

// ---- RTSP URL builders ----
const encRtsp = (p) => encodeURIComponent(p);

const RTSP_MAIN_URL  = `rtsp://${CAMERA_USERNAME}:${encRtsp(CAMERA_PASSWORD)}@${CAMERA_IP}:${CAMERA_RTSP_PORT}${RTSP_MAIN_PATH}`;
const RTSP_SUB_URL   = `rtsp://${CAMERA_USERNAME}:${encRtsp(CAMERA_PASSWORD)}@${CAMERA_IP}:${CAMERA_RTSP_PORT}${RTSP_SUB_PATH}`;
const RTSP2_MAIN_URL = `rtsp://${CAMERA2_USERNAME}:${encRtsp(CAMERA2_PASSWORD)}@${CAMERA2_IP}:${CAMERA2_RTSP_PORT}${RTSP2_MAIN_PATH}`;
const RTSP2_SUB_URL  = `rtsp://${CAMERA2_USERNAME}:${encRtsp(CAMERA2_PASSWORD)}@${CAMERA2_IP}:${CAMERA2_RTSP_PORT}${RTSP2_SUB_PATH}`;

// ---- Create directories ----
[SNAPSHOT_DIR, RECORDINGS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
    console.log(`[INFO] Folder creat: ${dir}`);
  }
});

// ============================================
// ONVIF HELPER (SOAP over HTTP, WS-Security)
// Camera uses ONVIF, NOT ISAPI, on port 80
// ============================================

const CAMERA2_ONVIF_PROFILE = process.env.CAMERA2_ONVIF_PROFILE || "Profile_1";
const CAMERA2_VIDEO_SOURCE  = process.env.CAMERA2_VIDEO_SOURCE  || "VideoSourceToken";

/** Build ONVIF WS-Security header (PasswordDigest + fresh nonce per call) */
function onvifSecHeader() {
  const nonce    = crypto.randomBytes(16);
  const created  = new Date().toISOString();
  const nonceB64 = nonce.toString("base64");
  const digest   = crypto.createHash("sha1")
    .update(Buffer.concat([nonce, Buffer.from(created), Buffer.from(CAMERA2_PASSWORD)]))
    .digest("base64");
  return `<s:Header><Security xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"><UsernameToken><Username>${CAMERA2_USERNAME}</Username><Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">${digest}</Password><Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">${nonceB64}</Nonce><Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">${created}</Created></UsernameToken></Security></s:Header>`;
}

/**
 * Makes an ONVIF SOAP request to Camera 2.
 * @param {string} onvifPath  - e.g. "/onvif/PTZ_Service"
 * @param {string} action     - SOAP action URI
 * @param {string} soapBody   - inner SOAP body XML string
 */
function onvifSoap(onvifPath, action, soapBody) {
  const envelope = `<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">${onvifSecHeader()}<s:Body>${soapBody}</s:Body></s:Envelope>`;
  const payload  = Buffer.from(envelope);
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: CAMERA2_IP,
      port:     parseInt(CAMERA2_HTTP_PORT, 10),
      path:     onvifPath,
      method:   "POST",
      headers:  { "Content-Type": `application/soap+xml; charset=utf-8; action="${action}"`, "Content-Length": payload.length },
      timeout:  8000,
    }, (res) => {
      const chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, data: Buffer.concat(chunks).toString() }));
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("ONVIF request timeout")); });
    req.write(payload);
    req.end();
  });
}

/** Extract first value of any ONVIF/XML tag (namespace-agnostic) */
function onvifGet(xml, tag) {
  const m = xml.match(new RegExp(`<[^:>]+:${tag}[^>]*>([^<]*)<`));
  return m ? m[1].trim() : null;
}

// ============================================
// ISAPI / HTTP DIGEST AUTH HELPER
// (Kept for light + image endpoints — ONVIF imaging is used where possible)
// ============================================

/** Cache nonce per host to avoid extra round-trips */
const nonceCache = new Map();
/** Session cookie captured from camera (needed for audio) */
let cam2Cookie = null;

function md5(str) {
  return crypto.createHash("md5").update(str).digest("hex");
}

function buildDigestHeader(method, reqPath, { realm, nonce, qop, opaque }) {
  const nc     = "00000001";
  const cnonce = crypto.randomBytes(4).toString("hex");
  const ha1    = md5(`${CAMERA2_USERNAME}:${realm}:${CAMERA2_PASSWORD}`);
  const ha2    = md5(`${method}:${reqPath}`);
  const responseHash = qop
    ? md5(`${ha1}:${nonce}:${nc}:${cnonce}:${qop}:${ha2}`)
    : md5(`${ha1}:${nonce}:${ha2}`);
  let header = `Digest username="${CAMERA2_USERNAME}", realm="${realm}", nonce="${nonce}", uri="${reqPath}", response="${responseHash}"`;
  if (qop)    header += `, qop=${qop}, nc=${nc}, cnonce="${cnonce}"`;
  if (opaque) header += `, opaque="${opaque}"`;
  return header;
}

/**
 * Makes an HTTP request to Camera 2 with automatic Digest Auth.
 *
 * Some HiLook/Hikvision cameras return 404 (not 401) for unauthenticated
 * PUT/POST requests. We handle that by probing a known GET endpoint
 * (/ISAPI/System/Time) to obtain the digest nonce, then retry.
 *
 * @param {object} opts
 * @param {string} opts.method
 * @param {string} opts.path  - ISAPI path, e.g. "/ISAPI/PTZCtrl/channels/1/Continuous"
 * @param {string|null} opts.body  - XML body (string)
 * @param {Buffer|null} opts.binaryBuffer  - binary body (for audio data)
 * @param {string} opts.contentType
 * @returns {Promise<{status:number, headers:object, data:string}>}
 */
async function cam2Request({ method, path: reqPath, body = null, binaryBuffer = null, contentType = "application/xml" }) {
  const hostname = CAMERA2_IP;
  const port     = parseInt(CAMERA2_HTTP_PORT, 10);
  const cacheKey = `${hostname}:${port}`;

  const doReq = (authHeader) => new Promise((resolve, reject) => {
    const headers = {};
    if (authHeader)     headers["Authorization"] = authHeader;
    if (cam2Cookie)     headers["Cookie"]        = cam2Cookie;
    if (binaryBuffer) {
      headers["Content-Type"]   = "application/octet-stream";
      headers["Content-Length"] = binaryBuffer.length;
    } else if (body) {
      headers["Content-Type"]   = contentType;
      headers["Content-Length"] = Buffer.byteLength(body);
    } else if (["PUT", "POST"].includes(method.toUpperCase())) {
      headers["Content-Length"] = 0;
    }

    const req = http.request({ hostname, port, path: reqPath, method, headers, timeout: 8000 }, (res) => {
      const setCookie = res.headers["set-cookie"];
      if (setCookie) cam2Cookie = setCookie.map(c => c.split(";")[0]).join("; ");
      const chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, data: Buffer.concat(chunks).toString() }));
    });

    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("cam2 request timeout")); });

    if (binaryBuffer) req.write(binaryBuffer);
    else if (body)    req.write(body);
    req.end();
  });

  /**
   * Probe a safe GET endpoint to obtain a Digest Auth nonce.
   * Used as fallback when the camera doesn't return 401 on the first request.
   */
  const probeNonce = () => new Promise((resolve) => {
    const req = http.request(
      { hostname, port, path: "/ISAPI/System/Time", method: "GET",
        headers: cam2Cookie ? { Cookie: cam2Cookie } : {}, timeout: 5000 },
      (res) => { const h = res.headers; res.resume(); res.on("end", () => resolve({ status: res.statusCode, headers: h })); }
    );
    req.on("error", () => resolve({ status: 0, headers: {} }));
    req.on("timeout", () => { req.destroy(); resolve({ status: 0, headers: {} }); });
    req.end();
  });

  const parseWwwAuth = (headers) => {
    const raw = headers["www-authenticate"] || "";
    if (!raw.toLowerCase().startsWith("digest")) return null;
    return {
      realm:  (raw.match(/realm="([^"]+)"/)  || [])[1] || "",
      nonce:  (raw.match(/nonce="([^"]+)"/)  || [])[1] || "",
      qop:    ((raw.match(/qop="([^"]+)"/)   || [])[1] || "").split(",")[0].trim(),
      opaque: (raw.match(/opaque="([^"]+)"/) || [])[1] || "",
    };
  };

  // ── 1. Try cached nonce first ──────────────────────────────────────────────
  const cached = nonceCache.get(cacheKey);
  if (cached) {
    try {
      const res = await doReq(buildDigestHeader(method, reqPath, cached));
      if (res.status !== 401) return res;
      nonceCache.delete(cacheKey);
    } catch { nonceCache.delete(cacheKey); }
  }

  // ── 2. First attempt without auth ─────────────────────────────────────────
  const first = await doReq(null);

  let authInfo = null;

  if (first.status === 401) {
    // Standard flow: camera challenged us
    authInfo = parseWwwAuth(first.headers);
  } else if (first.status === 200 || first.status === 201) {
    // No auth needed
    return first;
  } else {
    // Camera returned 404/403/etc. without an auth challenge (common on HiLook
    // when the first request is a PUT without body or the endpoint needs auth).
    // Probe a known GET endpoint to get the digest nonce.
    console.log(`[ISAPI] First request to ${reqPath} returned ${first.status} — probing for nonce…`);
    const probe = await probeNonce();
    if (probe.status === 401) {
      authInfo = parseWwwAuth(probe.headers);
    } else {
      // Cannot obtain nonce — return the original response as-is
      console.warn(`[ISAPI] Nonce probe returned ${probe.status}; giving up on auth`);
      return first;
    }
  }

  if (!authInfo || !authInfo.nonce) {
    console.warn("[ISAPI] Could not parse WWW-Authenticate header");
    return first;
  }

  // ── 3. Retry with Digest Auth ──────────────────────────────────────────────
  nonceCache.set(cacheKey, authInfo);
  return doReq(buildDigestHeader(method, reqPath, authInfo));
}

/** Shorthand for XML ISAPI calls to Camera 2 */
function isapi(method, apiPath, xmlBody = null) {
  return cam2Request({ method, path: apiPath, body: xmlBody });
}

/** Extract first value of an XML tag */
function xmlGet(xml, tag) {
  const m = xml.match(new RegExp(`<${tag}[^>]*>([^<]*)<\/${tag}>`));
  return m ? m[1].trim() : null;
}

/** Extract all blocks of a repeated XML tag */
function xmlGetAll(xml, tag) {
  const results = [];
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\/${tag}>`, "g");
  let m;
  while ((m = re.exec(xml)) !== null) results.push(m[1]);
  return results;
}

/** Replace a tag value in XML string */
function xmlSet(xml, tag, value) {
  return xml.replace(new RegExp(`(<${tag}[^>]*>)[^<]*(<\/${tag}>)`), `$1${value}$2`);
}

/** G.711 μ-law encoder (Int16 PCM → u-law byte) */
function encodeMuLaw(sample) {
  const BIAS = 33, CLIP = 32635;
  const sign = sample < 0 ? 0x80 : 0;
  if (sign) sample = -sample;
  if (sample > CLIP) sample = CLIP;
  sample += BIAS;
  let exp = 7;
  for (let mask = 0x4000; (sample & mask) === 0 && exp > 0; exp--, mask >>= 1) {}
  const mantissa = (sample >> (exp + 3)) & 0x0F;
  return (~(sign | (exp << 4) | mantissa)) & 0xFF;
}

// ============================================
// EXPRESS APP
// ============================================
const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, "public")));
app.use("/snapshots",  express.static(path.resolve(SNAPSHOT_DIR)));
app.use("/recordings", express.static(path.resolve(RECORDINGS_DIR)));

// ---- State ----
let recordingProcess = null;
let recordingMeta    = null;
let currentCamera    = 1;
let audioSessionOpen = false;
let audioSessionId   = null;

// ============================================
// STREAM ENDPOINT
// ============================================
app.get("/api/stream", (req, res) => {
  const camera  = parseInt(req.query.camera  || "1", 10);
  const quality = req.query.quality === "main" ? "main" : "sub";
  const fps     = parseInt(req.query.fps     || "5",  10);
  const width   = req.query.width ? parseInt(req.query.width, 10) : null;

  const rtspUrl = camera === 2
    ? (quality === "main" ? RTSP2_MAIN_URL : RTSP2_SUB_URL)
    : (quality === "main" ? RTSP_MAIN_URL  : RTSP_SUB_URL);

  currentCamera = camera;
  console.log(`[STREAM] Camera ${camera} - ${quality} @ ${fps}fps`);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "5000000",
    "-i", rtspUrl,
    "-vcodec", "mjpeg",
    "-f", "mjpeg",
    "-q:v", "5",
    "-r", String(fps),
    "-an",
  ];
  if (width) ffmpegArgs.splice(ffmpegArgs.indexOf("-f"), 0, "-vf", `scale=${width}:-2`);
  ffmpegArgs.push("pipe:1");

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);

  res.writeHead(200, {
    "Content-Type": "multipart/x-mixed-replace; boundary=ffmpeg",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Connection": "close",
  });

  let buffer = Buffer.alloc(0);

  ffmpeg.stdout.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    while (true) {
      const soi = findMarker(buffer, 0xff, 0xd8);
      if (soi === -1) break;
      const eoi = findMarker(buffer, 0xff, 0xd9, soi + 2);
      if (eoi === -1) break;
      const frame = buffer.slice(soi, eoi + 2);
      buffer = buffer.slice(eoi + 2);
      try {
        res.write(`--ffmpeg\r\n`);
        res.write(`Content-Type: image/jpeg\r\n`);
        res.write(`Content-Length: ${frame.length}\r\n\r\n`);
        res.write(frame);
        res.write("\r\n");
      } catch { ffmpeg.kill("SIGTERM"); return; }
    }
  });

  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error") || msg.includes("Connection refused")) {
      console.error(`[STREAM ERROR] ${msg.trim()}`);
    }
  });

  ffmpeg.on("close", (code) => {
    console.log(`[STREAM] ffmpeg oprit: ${code}`);
    if (!res.writableEnded) res.end();
  });

  ffmpeg.on("error", (err) => {
    console.error(`[STREAM] Eroare ffmpeg: ${err.message}`);
    if (!res.headersSent) res.status(500).json({ error: "Nu s-a putut porni ffmpeg." });
  });

  req.on("close", () => ffmpeg.kill("SIGTERM"));
});

// ============================================
// SNAPSHOT ENDPOINTS
// ============================================
app.get("/api/snapshot", (req, res) => {
  const camera  = parseInt(req.query.camera  || "1", 10);
  const quality = req.query.quality === "sub" ? "sub" : "main";
  const shouldSave = req.query.save === "true";

  const rtspUrl = camera === 2
    ? (quality === "main" ? RTSP2_MAIN_URL : RTSP2_SUB_URL)
    : (quality === "main" ? RTSP_MAIN_URL  : RTSP_SUB_URL);

  console.log(`[SNAPSHOT] Camera ${camera} - ${quality}`);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "10000000",
    "-i", rtspUrl,
    "-frames:v", "1",
    "-vcodec", "mjpeg",
    "-f", "image2",
    "-q:v", "2",
    "-update", "1",
    "-y",
    "pipe:1",
  ];

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);
  const chunks = [];
  ffmpeg.stdout.on("data", c => chunks.push(c));
  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) console.error(`[SNAPSHOT ERROR] ${msg.trim()}`);
  });

  ffmpeg.on("close", (code) => {
    if (code !== 0 || chunks.length === 0) {
      if (!res.headersSent) return res.status(500).json({ error: "Nu s-a putut captura snapshot-ul" });
      return;
    }
    const imageBuffer = Buffer.concat(chunks);
    if (shouldSave) {
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filename  = req.query.filename || `snapshot_${timestamp}`;
      fs.writeFileSync(path.join(SNAPSHOT_DIR, `${filename}.jpg`), imageBuffer);
    }
    res.writeHead(200, {
      "Content-Type": "image/jpeg",
      "Content-Length": imageBuffer.length,
      "Content-Disposition": shouldSave ? "attachment; filename=snapshot.jpg" : "inline",
    });
    res.end(imageBuffer);
  });

  ffmpeg.on("error", (err) => {
    if (!res.headersSent) res.status(500).json({ error: "Nu s-a putut porni ffmpeg", details: err.message });
  });

  const timeout = setTimeout(() => {
    ffmpeg.kill("SIGTERM");
    if (!res.headersSent) res.status(504).json({ error: "Timeout la snapshot" });
  }, 15000);
  ffmpeg.on("close", () => clearTimeout(timeout));
});

app.get("/api/snapshot/save", (req, res) => {
  const camera  = parseInt(req.query.camera || "1", 10);
  const quality = req.query.quality === "sub" ? "sub" : "main";
  const rtspUrl = camera === 2
    ? (quality === "main" ? RTSP2_MAIN_URL : RTSP2_SUB_URL)
    : (quality === "main" ? RTSP_MAIN_URL  : RTSP_SUB_URL);

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename  = req.query.filename || `snapshot_${timestamp}`;
  const filepath  = path.resolve(SNAPSHOT_DIR, `${filename}.jpg`);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp", "-timeout", "10000000",
    "-i", rtspUrl, "-frames:v", "1",
    "-vcodec", "mjpeg", "-q:v", "2", "-y", filepath,
  ];

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);
  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) console.error(`[SNAPSHOT SAVE ERROR] ${msg.trim()}`);
  });

  ffmpeg.on("close", (code) => {
    if (code !== 0 || !fs.existsSync(filepath)) {
      return res.status(500).json({ error: "Nu s-a putut salva snapshot-ul" });
    }
    const stats = fs.statSync(filepath);
    res.json({ success: true, filename: `${filename}.jpg`, path: filepath, size: stats.size, url: `/snapshots/${filename}.jpg`, timestamp: new Date().toISOString() });
  });

  ffmpeg.on("error", (err) => {
    if (!res.headersSent) res.status(500).json({ error: "ffmpeg error", details: err.message });
  });
});

app.get("/api/snapshots", (req, res) => {
  try {
    const files = fs.readdirSync(SNAPSHOT_DIR)
      .filter(f => /\.(jpg|jpeg|png)$/i.test(f))
      .map(f => {
        const stats = fs.statSync(path.join(SNAPSHOT_DIR, f));
        return { filename: f, url: `/snapshots/${f}`, size: stats.size, created: stats.birthtime };
      })
      .sort((a, b) => new Date(b.created) - new Date(a.created));
    res.json({ count: files.length, files });
  } catch { res.status(500).json({ error: "Nu s-a putut citi folderul de snapshots" }); }
});

// ============================================
// STATUS / INFO
// ============================================
app.get("/api/status", (req, res) => {
  const startTime  = Date.now();
  const ffmpeg     = spawn(FFMPEG_PATH, ["-rtsp_transport", "tcp", "-timeout", "5000000", "-i", RTSP_MAIN_URL, "-frames:v", "1", "-f", "null", "-"]);
  let stderr       = "";
  ffmpeg.stderr.on("data", d => { stderr += d.toString(); });
  ffmpeg.on("close", (code) => {
    const elapsed   = Date.now() - startTime;
    const isOnline  = code === 0 || stderr.includes("Video:");
    const videoInfo = stderr.match(/Video:\s+([^\n]+)/);
    const audioInfo = stderr.match(/Audio:\s+([^\n]+)/);
    res.json({
      camera: { ip: CAMERA_IP, online: isOnline, responseTime: `${elapsed}ms`, mainStream: RTSP_MAIN_PATH, subStream: RTSP_SUB_PATH },
      stream: { video: videoInfo ? videoInfo[1].trim() : null, audio: audioInfo ? audioInfo[1].trim() : null },
    });
  });
  setTimeout(() => ffmpeg.kill("SIGTERM"), 10000);
});

app.get("/api/info", (req, res) => {
  res.json({
    server: { port: SERVER_PORT, version: "2.0.0" },
    camera1: { ip: CAMERA_IP, rtspPort: CAMERA_RTSP_PORT, mainStream: RTSP_MAIN_PATH, subStream: RTSP_SUB_PATH },
    camera2: { ip: CAMERA2_IP, httpPort: CAMERA2_HTTP_PORT, rtspPort: CAMERA2_RTSP_PORT, mainStream: RTSP2_MAIN_PATH, subStream: RTSP2_SUB_PATH },
  });
});

// ============================================
// RECORDING ENDPOINTS
// ============================================
app.post("/api/record/start", (req, res) => {
  if (recordingProcess) {
    return res.status(409).json({ error: "O înregistrare este deja în curs", recording: recordingMeta });
  }
  const camera  = parseInt(req.query.camera || "1", 10);
  const quality = req.query.quality || "main";
  const rtspUrl = camera === 2
    ? (quality === "sub" ? RTSP2_SUB_URL : RTSP2_MAIN_URL)
    : (quality === "sub" ? RTSP_SUB_URL  : RTSP_MAIN_URL);

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename  = `cam${camera}_${timestamp}.mp4`;
  const filepath  = path.resolve(RECORDINGS_DIR, filename);

  const ffmpegArgs = [
    "-rtsp_transport", "tcp", "-timeout", "5000000",
    "-i", rtspUrl,
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", "25",
    "-c:a", "aac", "-ar", "16000",
    "-f", "mp4", "-y", filepath,
  ];

  recordingProcess = spawn(FFMPEG_PATH, ffmpegArgs);
  recordingMeta    = { filename, filepath, quality, startedAt: new Date().toISOString(), startTs: Date.now() };

  recordingProcess.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) console.error(`[RECORD ERROR] ${msg.trim()}`);
  });
  recordingProcess.on("close", (code) => {
    console.log(`[RECORD] ffmpeg oprit, cod: ${code}`);
    recordingProcess = null;
    recordingMeta    = null;
  });
  recordingProcess.on("error", (err) => {
    console.error(`[RECORD] Eroare: ${err.message}`);
    recordingProcess = null;
    recordingMeta    = null;
  });

  console.log(`[RECORD] Pornit: ${filename}`);
  res.json({ success: true, message: "Înregistrarea a pornit", filename, quality, startedAt: recordingMeta.startedAt });
});

app.post("/api/record/stop", (req, res) => {
  if (!recordingProcess) return res.status(400).json({ error: "Nu există nicio înregistrare activă" });
  const meta     = { ...recordingMeta };
  const duration = Math.floor((Date.now() - meta.startTs) / 1000);
  recordingProcess.stdin.write("q");
  const forceKill = setTimeout(() => { if (recordingProcess) recordingProcess.kill("SIGTERM"); }, 3000);
  recordingProcess.on("close", () => {
    clearTimeout(forceKill);
    const fileExists = fs.existsSync(meta.filepath);
    const fileSize   = fileExists ? fs.statSync(meta.filepath).size : 0;
    console.log(`[RECORD] Salvat: ${meta.filename} (${(fileSize / 1024 / 1024).toFixed(2)} MB, ${duration}s)`);
  });
  res.json({ success: true, message: "Înregistrarea s-a oprit", filename: meta.filename, duration: `${duration}s`, url: `/recordings/${meta.filename}`, downloadUrl: `/api/recordings/${meta.filename}` });
});

app.get("/api/record/status", (req, res) => {
  if (!recordingProcess) return res.json({ recording: false });
  const duration = Math.floor((Date.now() - recordingMeta.startTs) / 1000);
  res.json({ recording: true, filename: recordingMeta.filename, quality: recordingMeta.quality, startedAt: recordingMeta.startedAt, duration });
});

app.get("/api/recordings", (req, res) => {
  try {
    const files = fs.readdirSync(RECORDINGS_DIR)
      .filter(f => /\.mp4$/i.test(f))
      .map(f => {
        const stats = fs.statSync(path.join(RECORDINGS_DIR, f));
        return { filename: f, url: `/recordings/${f}`, downloadUrl: `/api/recordings/${f}`, size: stats.size, sizeMB: (stats.size / 1024 / 1024).toFixed(2), created: stats.birthtime };
      })
      .sort((a, b) => new Date(b.created) - new Date(a.created));
    res.json({ count: files.length, files });
  } catch { res.status(500).json({ error: "Nu s-a putut citi folderul" }); }
});

app.get("/api/recordings/:filename", (req, res) => {
  const filename = path.basename(req.params.filename);
  const filepath = path.resolve(RECORDINGS_DIR, filename);
  if (!fs.existsSync(filepath)) return res.status(404).json({ error: "Fișierul nu există" });
  const stat = fs.statSync(filepath);
  res.setHeader("Content-Type", "video/mp4");
  res.setHeader("Content-Length", stat.size);
  res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
  fs.createReadStream(filepath).pipe(res);
});

const deleteRecording = (req, res) => {
  const filename = path.basename(req.params.filename);
  const filepath = path.resolve(RECORDINGS_DIR, filename);
  if (!fs.existsSync(filepath)) return res.status(404).json({ error: "Fișierul nu există" });
  try {
    fs.unlinkSync(filepath);
    console.log(`[RECORD] Șters: ${filename}`);
    res.json({ success: true, message: `${filename} șters` });
  } catch (err) {
    res.status(500).json({ error: "Nu s-a putut șterge fișierul", details: err.message });
  }
};
app.post("/api/recordings/:filename/delete", deleteRecording);
app.delete("/api/recordings/:filename", deleteRecording);

// ============================================
// PTZ ENDPOINTS — ONVIF ContinuousMove / Stop
// ============================================

/** direction → ONVIF PanTilt x/y unit vectors (-1..1) */
const PTZ_VECTORS = {
  "up":         { x:  0,     y:  1     },
  "down":       { x:  0,     y: -1     },
  "left":       { x: -1,     y:  0     },
  "right":      { x:  1,     y:  0     },
  "up-left":    { x: -0.707, y:  0.707 },
  "up-right":   { x:  0.707, y:  0.707 },
  "down-left":  { x: -0.707, y: -0.707 },
  "down-right": { x:  0.707, y: -0.707 },
};

const PTZ_SVC    = "/onvif/PTZ_Service";
const PTZ_NS     = "http://www.onvif.org/ver20/ptz/wsdl";
const PTZ_ACTION = (a) => `${PTZ_NS}/${a}`;

app.post("/api/ptz/move", async (req, res) => {
  const { direction = "up", speed = 5 } = req.body;
  const speedNum = Math.max(1, Math.min(7, parseInt(speed) || 5));
  const v = PTZ_VECTORS[direction];
  if (!v) return res.status(400).json({ error: "Direcție invalidă" });

  const vx = (v.x * speedNum / 7).toFixed(3);
  const vy = (v.y * speedNum / 7).toFixed(3);
  // Omit <Zoom> element — PT-only cameras return 500 if Zoom is included
  const body = `<tptz:ContinuousMove xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:Velocity><tt:PanTilt xmlns:tt="http://www.onvif.org/ver10/schema" x="${vx}" y="${vy}"/></tptz:Velocity></tptz:ContinuousMove>`;

  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("ContinuousMove"), body);
    if (result.status === 200) {
      res.json({ success: true, direction, speed: speedNum });
    } else {
      console.warn(`[PTZ] ContinuousMove ${result.status}`);
      res.status(502).json({ success: false, error: `Camera returned ${result.status}`, cameraStatus: result.status });
    }
  } catch (err) {
    console.error(`[PTZ] Move error: ${err.message}`);
    res.status(500).json({ success: false, error: "PTZ connection failed", details: err.message });
  }
});

app.post("/api/ptz/stop", async (req, res) => {
  const body = `<tptz:Stop xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>`;
  try {
    await onvifSoap(PTZ_SVC, PTZ_ACTION("Stop"), body);
    res.json({ success: true });
  } catch (err) {
    console.error(`[PTZ] Stop error: ${err.message}`);
    res.status(500).json({ success: false, error: "PTZ stop failed" });
  }
});

app.post("/api/ptz/goto", async (req, res) => {
  // Accept either ONVIF token (string) or legacy numeric preset
  const presetToken = req.body.token || String(req.body.preset || "1");
  const body = `<tptz:GotoPreset xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:PresetToken>${presetToken}</tptz:PresetToken></tptz:GotoPreset>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("GotoPreset"), body);
    res.json({ success: result.status === 200, token: presetToken });
  } catch (err) {
    res.status(500).json({ success: false, error: "GotoPreset failed", details: err.message });
  }
});

app.post("/api/ptz/position", async (req, res) => {
  // ONVIF AbsoluteMove: x/y are -1..1 fractions of pan/tilt range, zoom 0..1
  const { x = 0, y = 0, zoom = 0 } = req.body;
  const px = Math.max(-1, Math.min(1, parseFloat(x) || 0)).toFixed(3);
  const py = Math.max(-1, Math.min(1, parseFloat(y) || 0)).toFixed(3);
  const pz = Math.max(0,  Math.min(1, parseFloat(zoom) || 0)).toFixed(3);
  const body = `<tptz:AbsoluteMove xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:Position><tt:PanTilt xmlns:tt="http://www.onvif.org/ver10/schema" x="${px}" y="${py}"/><tt:Zoom xmlns:tt="http://www.onvif.org/ver10/schema" x="${pz}"/></tptz:Position></tptz:AbsoluteMove>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("AbsoluteMove"), body);
    res.json({ success: result.status === 200 });
  } catch (err) {
    res.status(500).json({ success: false, error: "AbsoluteMove failed", details: err.message });
  }
});

app.post("/api/ptz/zoom", async (req, res) => {
  const { direction = "in", speed = 5 } = req.body;
  const speedNum = Math.max(1, Math.min(7, parseInt(speed) || 5));
  const zv       = (direction === "in" ? speedNum / 7 : -(speedNum / 7)).toFixed(3);
  // For zoom-only move: include PanTilt zeroed + Zoom
  const body = `<tptz:ContinuousMove xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:Velocity><tt:PanTilt xmlns:tt="http://www.onvif.org/ver10/schema" x="0" y="0"/><tt:Zoom xmlns:tt="http://www.onvif.org/ver10/schema" x="${zv}"/></tptz:Velocity></tptz:ContinuousMove>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("ContinuousMove"), body);
    res.json({ success: result.status === 200, direction });
  } catch (err) {
    res.status(500).json({ success: false, error: "PTZ zoom failed" });
  }
});

app.post("/api/ptz/focus", async (req, res) => {
  // Focus is not standard ONVIF PTZ — cameras with fixed lens won't support it
  res.json({ success: false, message: "Focus control not available on this camera (fixed lens)" });
});

app.get("/api/ptz/status", async (req, res) => {
  const body = `<tptz:GetStatus xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken></tptz:GetStatus>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("GetStatus"), body);
    res.json({ success: result.status === 200, raw: result.data });
  } catch (err) {
    res.status(500).json({ error: "PTZ status failed", details: err.message });
  }
});

// ---- Presets (ONVIF) ----
app.get("/api/ptz/presets", async (req, res) => {
  const body = `<tptz:GetPresets xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken></tptz:GetPresets>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("GetPresets"), body);
    const presets = [];
    const re = /token="([^"]+)"[^>]*>[\s\S]*?<[^:]+:Name>([^<]+)<\/[^:]+:Name>/g;
    let m;
    while ((m = re.exec(result.data)) !== null) {
      presets.push({ token: m[1], name: m[2].trim() });
    }
    res.json({ count: presets.length, presets });
  } catch (err) {
    res.status(500).json({ error: "Failed to list presets", details: err.message });
  }
});

app.post("/api/ptz/presets", async (req, res) => {
  const { name = "Preset", token } = req.body;
  const safeName = String(name).replace(/[<>&'"]/g, "");
  let body = `<tptz:SetPreset xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:PresetName>${safeName}</tptz:PresetName>`;
  if (token) body += `<tptz:PresetToken>${token}</tptz:PresetToken>`;
  body += `</tptz:SetPreset>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("SetPreset"), body);
    if (result.status === 200) {
      const newToken = onvifGet(result.data, "PresetToken");
      res.json({ success: true, token: newToken || token, name: safeName });
    } else {
      res.status(502).json({ success: false, error: "SetPreset failed", cameraStatus: result.status });
    }
  } catch (err) {
    res.status(500).json({ success: false, error: "SetPreset failed", details: err.message });
  }
});

app.delete("/api/ptz/presets/:token", async (req, res) => {
  const presetToken = req.params.token;
  const body = `<tptz:RemovePreset xmlns:tptz="${PTZ_NS}"><tptz:ProfileToken>${CAMERA2_ONVIF_PROFILE}</tptz:ProfileToken><tptz:PresetToken>${presetToken}</tptz:PresetToken></tptz:RemovePreset>`;
  try {
    const result = await onvifSoap(PTZ_SVC, PTZ_ACTION("RemovePreset"), body);
    res.json({ success: result.status === 200 });
  } catch (err) {
    res.status(500).json({ success: false, error: "RemovePreset failed", details: err.message });
  }
});

// ============================================
// AUDIO ENDPOINTS
// ============================================

app.post("/api/audio/open", async (req, res) => {
  if (audioSessionOpen) return res.json({ success: true, sessionId: audioSessionId, message: "Already open" });
  try {
    const result = await isapi("PUT", "/ISAPI/System/TwoWayAudio/channels/1/open");
    if ([200, 201].includes(result.status)) {
      audioSessionId   = xmlGet(result.data, "sessionId") || "1";
      audioSessionOpen = true;
      console.log(`[AUDIO] Session opened: ${audioSessionId}`);
      res.json({ success: true, sessionId: audioSessionId });
    } else {
      res.status(result.status).json({ error: "Failed to open audio session", details: result.data });
    }
  } catch (err) {
    console.error(`[AUDIO] Open error: ${err.message}`);
    res.status(500).json({ error: "Failed to open audio", details: err.message });
  }
});

app.post("/api/audio/close", async (req, res) => {
  try {
    await isapi("PUT", "/ISAPI/System/TwoWayAudio/channels/1/close");
  } catch {}
  audioSessionOpen = false;
  audioSessionId   = null;
  console.log("[AUDIO] Session closed");
  res.json({ success: true });
});

app.get("/api/audio/status", (req, res) => {
  res.json({ open: audioSessionOpen, sessionId: audioSessionId });
});

/** Camera mic → browser: ffmpeg extracts audio from RTSP as MP3 stream */
app.get("/api/audio/listen", (req, res) => {
  const camera  = parseInt(req.query.camera || "2", 10);
  const rtspUrl = camera === 2 ? RTSP2_SUB_URL : RTSP_SUB_URL;

  res.writeHead(200, {
    "Content-Type": "audio/mpeg",
    "Transfer-Encoding": "chunked",
    "Cache-Control": "no-cache, no-store",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });

  const ffmpegArgs = [
    "-rtsp_transport", "tcp",
    "-timeout", "5000000",
    "-i", rtspUrl,
    "-vn",
    "-acodec", "libmp3lame",
    "-ar", "16000",
    "-ac", "1",
    "-q:a", "5",
    "-f", "mp3",
    "pipe:1",
  ];

  const ffmpeg = spawn(FFMPEG_PATH, ffmpegArgs);
  ffmpeg.stdout.on("data", chunk => { try { res.write(chunk); } catch { ffmpeg.kill("SIGTERM"); } });
  ffmpeg.stderr.on("data", (data) => {
    const msg = data.toString();
    if (msg.includes("error") || msg.includes("Error")) console.error(`[AUDIO LISTEN] ${msg.trim()}`);
  });
  ffmpeg.on("close", () => { if (!res.writableEnded) res.end(); });
  ffmpeg.on("error", err => {
    console.error(`[AUDIO LISTEN] ffmpeg error: ${err.message}`);
    if (!res.headersSent) res.status(500).end();
  });
  req.on("close", () => ffmpeg.kill("SIGTERM"));
});

// ============================================
// LIGHT CONTROL ENDPOINTS
// ============================================

app.get("/api/light", async (req, res) => {
  try {
    const result     = await isapi("GET", "/ISAPI/Image/channels/1/supplementLight");
    const mode       = xmlGet(result.data, "supplementLightMode")        || "unknown";
    const brightness = xmlGet(result.data, "whiteLightBrightness")       || "50";
    const irBright   = xmlGet(result.data, "IRLightBrightness")          || "50";
    res.json({ mode, brightness: parseInt(brightness), irBrightness: parseInt(irBright), raw: result.data });
  } catch (err) {
    res.status(500).json({ error: "Failed to get light settings", details: err.message });
  }
});

app.post("/api/light", async (req, res) => {
  const { mode = "ir", brightness = 50 } = req.body;
  const modeMap = { ir: "IRLight", white: "colorVuWhiteLight", off: "close", auto: "brightnessDay" };
  const lightMode   = modeMap[mode] || "close";
  const brightnessN = Math.max(0, Math.min(100, parseInt(brightness) || 50));

  const xml = `<SupplementLight><supplementLightMode>${lightMode}</supplementLightMode><whiteLightBrightness>${brightnessN}</whiteLightBrightness><IRLightBrightness>${brightnessN}</IRLightBrightness><mixedLightBrightnessRegulatMode>manual</mixedLightBrightnessRegulatMode></SupplementLight>`;
  try {
    const result = await isapi("PUT", "/ISAPI/Image/channels/1/supplementLight", xml);
    if ([200, 201].includes(result.status)) {
      res.json({ success: true, mode, brightness: brightnessN });
    } else {
      res.status(result.status).json({ error: "Failed to set light", details: result.data });
    }
  } catch (err) {
    res.status(500).json({ error: "Failed to set light", details: err.message });
  }
});

// ============================================
// IMAGE SETTINGS ENDPOINTS
// ============================================

app.get("/api/image/settings", async (req, res) => {
  try {
    const result = await isapi("GET", "/ISAPI/Image/channels/1");
    const d      = result.data;
    res.json({
      brightness:  parseInt(xmlGet(d, "Brightness")  || xmlGet(d, "brightness")  || "50"),
      contrast:    parseInt(xmlGet(d, "Contrast")    || xmlGet(d, "contrast")    || "50"),
      saturation:  parseInt(xmlGet(d, "Saturation")  || xmlGet(d, "saturation")  || "50"),
      hue:         parseInt(xmlGet(d, "Hue")         || xmlGet(d, "hue")         || "50"),
      sharpness:   parseInt(xmlGet(d, "Sharpness")   || xmlGet(d, "sharpness")   || "50"),
      irCutFilter: xmlGet(d, "IRCutFilter") || xmlGet(d, "irCutFilter") || "AUTO",
      wdr:         (xmlGet(d, "WDREnabled") || xmlGet(d, "WDR") || "false"),
      raw: d,
    });
  } catch (err) {
    res.status(500).json({ error: "Failed to get image settings", details: err.message });
  }
});

app.put("/api/image/settings", async (req, res) => {
  const { brightness, contrast, saturation, hue, sharpness, irCutFilter } = req.body;

  let xml = "";
  try {
    const current = await isapi("GET", "/ISAPI/Image/channels/1");
    xml = current.data;
  } catch (err) {
    return res.status(500).json({ error: "Failed to get current settings before update" });
  }

  if (brightness  !== undefined) xml = xmlSet(xml, "Brightness",  brightness);
  if (contrast    !== undefined) xml = xmlSet(xml, "Contrast",    contrast);
  if (saturation  !== undefined) xml = xmlSet(xml, "Saturation",  saturation);
  if (hue         !== undefined) xml = xmlSet(xml, "Hue",         hue);
  if (sharpness   !== undefined) xml = xmlSet(xml, "Sharpness",   sharpness);
  if (irCutFilter !== undefined) xml = xmlSet(xml, "IRCutFilter", irCutFilter);

  try {
    const result = await isapi("PUT", "/ISAPI/Image/channels/1", xml);
    if ([200, 201].includes(result.status)) {
      res.json({ success: true });
    } else {
      res.status(result.status).json({ error: "Failed to save settings", details: result.data });
    }
  } catch (err) {
    res.status(500).json({ error: "Failed to save settings", details: err.message });
  }
});

// ============================================
// DEVICE INFO ENDPOINT (ONVIF)
// ============================================

app.get("/api/device/info", async (req, res) => {
  const body = `<tds:GetDeviceInformation xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>`;
  try {
    const result = await onvifSoap("/onvif/device_service", "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation", body);
    const d = result.data;
    res.json({
      manufacturer:    onvifGet(d, "Manufacturer")    || "—",
      model:           onvifGet(d, "Model")           || "—",
      firmwareVersion: onvifGet(d, "FirmwareVersion") || "—",
      serialNumber:    onvifGet(d, "SerialNumber")    || "—",
      hardwareId:      onvifGet(d, "HardwareId")      || "—",
      ip:              CAMERA2_IP,
    });
  } catch (err) {
    res.status(500).json({ error: "Failed to get device info", details: err.message });
  }
});

// ============================================
// DIAGNOSTIC ENDPOINT
// ============================================

app.get("/api/diagnostic/camera2", async (req, res) => {
  const diagnostics = {
    camera: 2,
    config: {
      ip: CAMERA2_IP, username: CAMERA2_USERNAME,
      password: "***",
      rtspPort: CAMERA2_RTSP_PORT, httpPort: CAMERA2_HTTP_PORT, sdkPort: CAMERA2_SDK_PORT,
    },
    tests: {},
  };

  const testHttp = (portStr, testPath) => new Promise((resolve) => {
    const port = parseInt(portStr, 10);
    const req  = http.get({ hostname: CAMERA2_IP, port, path: testPath, timeout: 3000 }, (response) => {
      response.resume();
      resolve({ success: true, status: response.statusCode });
    });
    req.on("error", (err) => resolve({ success: false, error: err.message }));
    req.on("timeout",  () => { req.destroy(); resolve({ success: false, error: "Timeout" }); });
  });

  const [http80, sdk8000, ptz] = await Promise.all([
    testHttp(CAMERA2_HTTP_PORT, "/"),
    testHttp(CAMERA2_SDK_PORT,  "/"),
    testHttp(CAMERA2_HTTP_PORT, "/ISAPI/PTZCtrl/channels/1/status"),
  ]);
  diagnostics.tests["HTTP Port " + CAMERA2_HTTP_PORT] = http80;
  diagnostics.tests["SDK Port "  + CAMERA2_SDK_PORT]  = sdk8000;
  diagnostics.tests["PTZ ISAPI"]                      = ptz;

  res.json(diagnostics);
});

// ============================================
// UTILITY
// ============================================

function findMarker(buffer, byte1, byte2, startIndex = 0) {
  for (let i = startIndex; i < buffer.length - 1; i++) {
    if (buffer[i] === byte1 && buffer[i + 1] === byte2) return i;
  }
  return -1;
}

// ============================================
// START SERVER + WEBSOCKET
// ============================================

const httpServer = app.listen(SERVER_PORT, () => {
  console.log("============================================");
  console.log("  HiLook Camera Server v2.0 - PORNIT");
  console.log("============================================");
  console.log(`  Server:      http://localhost:${SERVER_PORT}`);
  console.log(`  Camera 1:    ${CAMERA_IP} (fix)`);
  console.log(`  Camera 2:    ${CAMERA2_IP} (PTZ)`);
  console.log("--------------------------------------------");
  console.log(`  Live:        http://localhost:${SERVER_PORT}/api/stream`);
  console.log(`  Snapshot:    http://localhost:${SERVER_PORT}/api/snapshot`);
  console.log(`  Audio:       ws://localhost:${SERVER_PORT}/ws/audio`);
  console.log("============================================");
});

httpServer.on("error", (err) => {
  console.error(`[SERVER] Eroare: ${err.message}`);
  process.exit(1);
});

// ---- WebSocket server for two-way audio talk ----
const wss = new WebSocketServer({ server: httpServer });

wss.on("error", (err) => console.error(`[WSS] Eroare: ${err.message}`));

wss.on("connection", (ws, req) => {
  if (req.url !== "/ws/audio") {
    ws.close(4000, "Unknown endpoint");
    return;
  }
  console.log("[AUDIO-WS] Browser connected for talk");

  ws.on("message", async (data) => {
    if (!audioSessionOpen) {
      console.warn("[AUDIO-WS] Audio data received but session not open — ignoring");
      return;
    }

    // Expect ArrayBuffer of Int16 PCM @ 8 kHz mono
    const buf    = Buffer.isBuffer(data) ? data : Buffer.from(data);
    const int16  = new Int16Array(buf.buffer, buf.byteOffset, Math.floor(buf.length / 2));
    const mulaw  = Buffer.alloc(int16.length);
    for (let i = 0; i < int16.length; i++) mulaw[i] = encodeMuLaw(int16[i]);

    try {
      await cam2Request({
        method:       "PUT",
        path:         "/ISAPI/System/TwoWayAudio/channels/1/audioData",
        binaryBuffer: mulaw,
      });
    } catch (err) {
      console.error(`[AUDIO-WS] Send error: ${err.message}`);
    }
  });

  ws.on("close", () => console.log("[AUDIO-WS] Browser disconnected"));
  ws.on("error", err => console.error(`[AUDIO-WS] Error: ${err.message}`));
});
