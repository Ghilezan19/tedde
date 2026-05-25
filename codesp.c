// =============================================================================
// Tedde ESP32 firmware v1.3.0 - dual-core architecture, 24/7 reliable
// -----------------------------------------------------------------------------
// Core 1 (loop task): LCD, button, countdown, DHT  -> NEVER blocks on network
// Core 0 (net task):  WiFi + all HTTP calls        -> isolated from UX
// Communication: FreeRTOS queue for outbound events, atomics for shared state
// Countdown: deadline-based (millis() delta), cannot drift even if UI blocks
// =============================================================================
#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <Preferences.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>
#include <esp_system.h>
#include <atomic>

#define FIRMWARE_VERSION "1.3.0-prod"

// =============================================================================
// Config
// =============================================================================
static const char *WIFI_SSID   = "Tedde_Auto";
static const char *WIFI_PASS   = "teddeauto";
/* LAN laptop (FastAPI :8000). Dacă DHCP schimbă IP, verifică: ip addr / hostname -I */
static const char *SERVER_BASE = "http://192.168.0.174:8000";

static const uint8_t LCD_SDA_PIN = 21;
static const uint8_t LCD_SCL_PIN = 22;
static const uint8_t LCD_COLUMNS = 16;
static const uint8_t LCD_ROWS    = 2;

static const uint8_t DHT_PIN    = 18;
static const uint8_t DHT_TYPE   = DHT11;
static const uint8_t FAN_PIN    = 4;
static const uint8_t BUTTON_PIN = 25;

static const int COUNTDOWN_DEFAULT_SECONDS = 30;
static const int COUNTDOWN_MIN_SECONDS     = 5;
static const int COUNTDOWN_MAX_SECONDS     = 3600;

static const int FAN_ON_TEMP_C  = 40;
static const int FAN_OFF_TEMP_C = 35;

static const unsigned long WIFI_RETRY_MIN_MS     = 5000UL;
static const unsigned long WIFI_RETRY_MAX_MS     = 60000UL;
static const unsigned long TEMP_READ_INTERVAL_MS = 5000UL;
static const unsigned long BUTTON_DEBOUNCE_MS    = 45UL;
static const unsigned long MESSAGE_DURATION_MS   = 1500UL;
static const unsigned long CONFIG_REFRESH_MS     = 60000UL;
static const unsigned long HEARTBEAT_INTERVAL_MS = 15000UL;
static const unsigned long LCD_HEALTHCHECK_MS    = 30000UL;

static const uint16_t HTTP_TIMEOUT_MS         = 3000;
static const uint16_t HTTP_CONNECT_TIMEOUT_MS  = 2000;

static const uint32_t WDT_TIMEOUT_S = 25;

static const int MAX_HB_FAILS_BEFORE_WIFI_RESET = 8;
static const int MAX_HB_FAILS_BEFORE_REBOOT     = 30;

// =============================================================================
// Runtime URLs
// =============================================================================
static char COUNTER_START_URL[160];
static char ESP_CONFIG_URL[160];
static char HEARTBEAT_URL[160];

// =============================================================================
// Shared state (atomics - ESP32 has lock-free 32-bit atomics)
// =============================================================================
static std::atomic<bool>      wifiConnected{false};
static std::atomic<bool>      wifiHadIp{false};
static std::atomic<bool>      fanEnabled{false};
static std::atomic<int>       tempCelsius{0};
static std::atomic<bool>      tempValid{false};
static std::atomic<int>       currentCountdownSec{COUNTDOWN_DEFAULT_SECONDS};
static std::atomic<int>       ptzHomeSec{0};      // PTZ_HOME_RECORDING_SECONDS from server
static std::atomic<int>       ptzSecondarySec{0}; // PTZ_SECONDARY_RECORDING_SECONDS from server

// Countdown deadline-based (single source of truth)
static std::atomic<unsigned long> countdownEndMs{0};   // 0 = inactive
static std::atomic<int>           countdownLastShown{-1}; // for finish detection

// Stats
static std::atomic<uint32_t> wifiReconnectCount{0};
static std::atomic<uint32_t> httpFailCount{0};
static std::atomic<int>      consecutiveHbFails{0};

// Event queue: net task consumes these
enum NetEventType : uint8_t {
  EVT_COUNTER_STARTED = 1,
};
struct NetEvent {
  NetEventType type;
  int32_t      value;
};
static QueueHandle_t netEventQueue = nullptr;

// =============================================================================
// UI-only state (touched ONLY by loop task)
// =============================================================================
struct OverlayMessage {
  bool          active;
  char          line1[17];
  char          line2[17];
  unsigned long untilMs;
};
static OverlayMessage overlay = {false, "", "", 0};

static DHT                 dht(DHT_PIN, DHT_TYPE);
static LiquidCrystal_I2C  *lcd      = nullptr;
static bool                lcdReady = false;
static uint8_t             lcdAddr  = 0;

static unsigned long lastTempReadMs     = 0;
static unsigned long lastButtonChangeMs = 0;
static unsigned long lastLcdCheckMs     = 0;
static unsigned long lastLcdRenderMs    = 0; // used to guard against flicker-triggered reinit
static int           lastRawButtonState = HIGH;
static int           debouncedButtonState = HIGH;

static char lastRenderedLine1[17] = "";
static char lastRenderedLine2[17] = "";

// =============================================================================
// Net-only state (touched ONLY by net task)
// =============================================================================
static Preferences prefs;
static const char *PREFS_NS     = "tedde";
static const char *PREFS_KEY_CD = "cd_s";

static unsigned long lastWiFiAttemptMs = 0;
static unsigned long wifiBackoffMs     = WIFI_RETRY_MIN_MS;
static unsigned long lastConfigFetchMs = 0;
static unsigned long lastHeartbeatMs   = 0;
static bool          wifiResetDoneThisBurst = false;

// =============================================================================
// Helpers
// =============================================================================
static inline bool timeReached(unsigned long now, unsigned long last, unsigned long interval) {
  return (unsigned long)(now - last) >= interval;
}

static void copyText16(char *dest, const char *src) {
  if (!dest) return;
  if (!src) src = "";
  size_t i = 0;
  for (; i < 16 && src[i] != '\0'; ++i) dest[i] = src[i];
  for (; i < 16; ++i) dest[i] = ' ';
  dest[16] = '\0';
}

static void copyTextSized(char *dest, size_t destSize, const char *src) {
  if (!dest || destSize == 0) return;
  if (!src) src = "";
  size_t i = 0;
  for (; i + 1 < destSize && src[i] != '\0'; ++i) dest[i] = src[i];
  dest[i] = '\0';
}

static void showOverlay(const char *l1, const char *l2,
                        unsigned long durationMs = MESSAGE_DURATION_MS) {
  copyText16(overlay.line1, l1);
  copyText16(overlay.line2, l2);
  overlay.active  = true;
  overlay.untilMs = millis() + durationMs;
}

static void expireOverlayIfNeeded() {
  if (overlay.active && (long)(millis() - overlay.untilMs) >= 0) {
    overlay.active = false;
  }
}

// =============================================================================
// Countdown (deadline-based)
// =============================================================================
static inline bool countdownIsActive() {
  return countdownEndMs.load() != 0;
}

static inline int countdownRemainingSeconds() {
  unsigned long end = countdownEndMs.load();
  if (end == 0) return 0;
  unsigned long now = millis();
  long diff = (long)(end - now);
  if (diff <= 0) return 0;
  // round up so "1.2s left" shows "2" not "1"
  return (int)((diff + 999) / 1000);
}

static void startCountdown() {
  int home = ptzHomeSec.load();
  int masina = ptzSecondarySec.load();
  int total = (home > 0 && masina > 0) ? home + masina : currentCountdownSec.load();
  countdownEndMs.store(millis() + (unsigned long)total * 1000UL);
  countdownLastShown.store(total);
  Serial.printf("[CD] start %d sec (P=%d M=%d)\n", total, home, masina);
}

static void stopCountdownIfExpired() {
  unsigned long end = countdownEndMs.load();
  if (end == 0) return;
  if ((long)(millis() - end) >= 0) {
    countdownEndMs.store(0);
    showOverlay("TeddeAuto", "Finalizat", 1500);
    Serial.println("[CD] finalizat");
  }
}

// =============================================================================
// LCD
// =============================================================================
static uint8_t scanForLcdAddress() {
  for (uint8_t addr = 0x03; addr <= 0x77; ++addr) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) return addr;
  }
  return 0;
}

static void destroyLcd() {
  if (lcd) { delete lcd; lcd = nullptr; }
  lcdReady = false;
  lcdAddr  = 0;
  lastRenderedLine1[0] = '\0';
  lastRenderedLine2[0] = '\0';
}

static bool initLcd() {
  destroyLcd();
  uint8_t addr = scanForLcdAddress();
  if (addr == 0) {
    Serial.println("[LCD] nu am gasit display I2C");
    return false;
  }
  lcd = new LiquidCrystal_I2C(addr, LCD_COLUMNS, LCD_ROWS);
  lcd->init();
  lcd->backlight();
  lcd->clear();
  lcdAddr  = addr;
  lcdReady = true;
  Serial.printf("[LCD] gasit la 0x%02X\n", lcdAddr);
  return true;
}

static bool lcdProbe() {
  if (lcdAddr == 0) return false;
  Wire.beginTransmission(lcdAddr);
  return Wire.endTransmission() == 0;
}

static void maintainLcdHealth() {
  unsigned long now = millis();
  if (!timeReached(now, lastLcdCheckMs, LCD_HEALTHCHECK_MS)) return;
  lastLcdCheckMs = now;
  if (!lcdReady || !lcdProbe()) {
    // Guard: don't re-init if we rendered successfully in the last 5s
    // (I2C noise during button press can cause false probe fail → flicker)
    if (lastLcdRenderMs == 0 || timeReached(now, lastLcdRenderMs, 5000UL)) {
      Serial.println("[LCD] probe fail, re-init");
      initLcd();
    }
  }
}

static void renderLcdLines(const char *l1, const char *l2) {
  if (!lcdReady || !lcd) return;
  char out1[17], out2[17];
  copyText16(out1, l1);
  copyText16(out2, l2);
  if (strcmp(out1, lastRenderedLine1) == 0 &&
      strcmp(out2, lastRenderedLine2) == 0) return;
  lcd->setCursor(0, 0); lcd->print(out1);
  lcd->setCursor(0, 1); lcd->print(out2);
  copyTextSized(lastRenderedLine1, sizeof(lastRenderedLine1), out1);
  copyTextSized(lastRenderedLine2, sizeof(lastRenderedLine2), out2);
  lastLcdRenderMs = millis();
}

static void buildMainLine1(char *line1) {
  copyText16(line1, "TeddeAuto");
  char tempText[6];
  if (tempValid.load()) snprintf(tempText, sizeof(tempText), "%dC", tempCelsius.load());
  else                  snprintf(tempText, sizeof(tempText), "--C");
  int tempLen = (int)strlen(tempText);
  int start   = 16 - tempLen;
  for (int i = 0; i < tempLen; ++i) line1[start + i] = tempText[i];
  line1[16] = '\0';
}

static void buildMainLine2(char *line2) {
  if (countdownIsActive()) {
    int rem   = countdownRemainingSeconds();
    int home  = ptzHomeSec.load();
    int masina = ptzSecondarySec.load();
    int mm = rem / 60;
    int ss = rem % 60;
    if (home > 0 && masina > 0) {
      // Phase-aware: if remaining > masina_seconds → Piese phase, else Masina phase
      const char *phase = (rem > masina) ? "Piese" : "Masina";
      snprintf(line2, 17, "%-6s %02d:%02d", phase, mm, ss);
    } else {
      snprintf(line2, 17, "Timp  %02d:%02d", mm, ss);
    }
  } else if (!wifiConnected.load() || !wifiHadIp.load()) {
    snprintf(line2, 17, "WiFi...");
  } else {
    snprintf(line2, 17, "Apasa pt start");
  }
}

static void renderDisplay() {
  if (!lcdReady) return;
  expireOverlayIfNeeded();
  char l1[17], l2[17];
  if (overlay.active) {
    copyTextSized(l1, sizeof(l1), overlay.line1);
    copyTextSized(l2, sizeof(l2), overlay.line2);
    renderLcdLines(l1, l2);
    return;
  }
  buildMainLine1(l1);
  buildMainLine2(l2);
  renderLcdLines(l1, l2);
}

// =============================================================================
// Temperature / fan
// =============================================================================
static void applyFanState() {
  bool valid = tempValid.load();
  int  tc    = tempCelsius.load();
  bool on    = fanEnabled.load();

  if (!valid) {
    fanEnabled.store(false);
    digitalWrite(FAN_PIN, LOW);
    return;
  }
  if (!on && tc >= FAN_ON_TEMP_C)       { on = true;  }
  else if (on && tc <= FAN_OFF_TEMP_C)  { on = false; }
  fanEnabled.store(on);
  digitalWrite(FAN_PIN, on ? HIGH : LOW);
}

static void readTemperatureIfNeeded() {
  unsigned long now = millis();
  if (lastTempReadMs != 0 && !timeReached(now, lastTempReadMs, TEMP_READ_INTERVAL_MS)) return;
  lastTempReadMs = now;

  float measured = NAN;
  for (int attempt = 0; attempt < 2; ++attempt) {
    measured = dht.readTemperature();
    if (!isnan(measured)) break;
    vTaskDelay(pdMS_TO_TICKS(30));
  }

  if (isnan(measured) || measured < -20.0f || measured > 80.0f) {
    tempValid.store(false);
    tempCelsius.store(0);
    applyFanState();
    return;
  }

  tempValid.store(true);
  tempCelsius.store((int)(measured + (measured >= 0 ? 0.5f : -0.5f)));
  applyFanState();
}

// =============================================================================
// Button (UI task)
// =============================================================================
static void handleTriggerButton() {
  int raw = digitalRead(BUTTON_PIN);
  unsigned long now = millis();

  if (raw != lastRawButtonState) {
    lastButtonChangeMs = now;
    lastRawButtonState = raw;
  }
  if (!timeReached(now, lastButtonChangeMs, BUTTON_DEBOUNCE_MS)) return;
  if (raw == debouncedButtonState) return;

  debouncedButtonState = raw;
  if (debouncedButtonState != LOW) return;
  if (countdownIsActive()) {
    // Show 3s visual feedback that recording is in progress, then return to countdown
    int rem = countdownRemainingSeconds();
    int mm = rem / 60, ss = rem % 60;
    char l2[17];
    snprintf(l2, sizeof(l2), "Ramas %02d:%02d", mm, ss);
    showOverlay("Inregistrare!", l2, 3000);
    Serial.println("[BTN] overlay activ, countdown in desfasurare");
    return;
  }

  // Start countdown immediately and show 3s confirmation overlay
  startCountdown();
  int home = ptzHomeSec.load();
  int masina = ptzSecondarySec.load();
  if (home > 0 && masina > 0) {
    showOverlay("Pornit!", "P->M workflow", 3000);
  } else {
    showOverlay("Pornit!", "Se inregistreaza", 3000);
  }

  // Dispatch event to net task (non-blocking)
  int total = (home > 0 && masina > 0) ? home + masina : currentCountdownSec.load();
  NetEvent ev{EVT_COUNTER_STARTED, total};
  if (netEventQueue) {
    if (xQueueSend(netEventQueue, &ev, 0) != pdTRUE) {
      Serial.println("[BTN] event queue full, drop");
    }
  }
}

// =============================================================================
// WiFi - event handler (runs in WiFi task context)
// =============================================================================
static void onWiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      wifiConnected.store(true);
      Serial.println("[WiFi] asociat");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      wifiHadIp.store(true);
      wifiBackoffMs = WIFI_RETRY_MIN_MS;
      Serial.print("[WiFi] IP: ");
      Serial.println(WiFi.localIP());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      if (wifiConnected.load() || wifiHadIp.load()) {
        wifiReconnectCount.fetch_add(1);
        Serial.println("[WiFi] deconectat");
      }
      wifiConnected.store(false);
      wifiHadIp.store(false);
      break;
    default:
      break;
  }
}

static void beginWiFiConnect() {
  Serial.printf("[WiFi] connect -> %s (backoff %lums)\n", WIFI_SSID, wifiBackoffMs);
  WiFi.disconnect(false, true);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  lastWiFiAttemptMs = millis();
}

static void maintainWiFi() {
  if (wifiConnected.load() && wifiHadIp.load()) {
    wifiBackoffMs = WIFI_RETRY_MIN_MS;
    return;
  }
  unsigned long now = millis();
  if (lastWiFiAttemptMs == 0 || timeReached(now, lastWiFiAttemptMs, wifiBackoffMs)) {
    beginWiFiConnect();
    wifiBackoffMs *= 2;
    if (wifiBackoffMs > WIFI_RETRY_MAX_MS) wifiBackoffMs = WIFI_RETRY_MAX_MS;
  }
}

static inline bool netReady() {
  return wifiConnected.load() && wifiHadIp.load() && WiFi.status() == WL_CONNECTED;
}

// =============================================================================
// HTTP (runs ONLY in net task - safe to block)
// =============================================================================
static void postCounterStart(int value) {
  if (!netReady()) { Serial.println("[HTTP] skip POST, no WiFi"); return; }

  HTTPClient http;
  http.setReuse(false);
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(COUNTER_START_URL)) {
    httpFailCount.fetch_add(1);
    return;
  }
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<128> doc;
  doc["event"] = "counter_started";
  doc["value"] = value;
  char payload[128];
  size_t n = serializeJson(doc, payload, sizeof(payload));

  esp_task_wdt_reset();
  int code = http.POST((uint8_t *)payload, n);
  esp_task_wdt_reset();

  if (code <= 0) {
    Serial.printf("[HTTP] POST fail: %s\n", http.errorToString(code).c_str());
    httpFailCount.fetch_add(1);
  } else {
    Serial.printf("[HTTP] POST /counter-start -> %d\n", code);
  }
  http.end();
}

static bool fetchConfig() {
  if (!netReady()) return false;

  HTTPClient http;
  http.setReuse(false);
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(ESP_CONFIG_URL)) { httpFailCount.fetch_add(1); return false; }

  esp_task_wdt_reset();
  int code = http.GET();
  esp_task_wdt_reset();

  if (code != 200) {
    Serial.printf("[HTTP] /api/esp/config -> %d\n", code);
    http.end();
    httpFailCount.fetch_add(1);
    return false;
  }

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, http.getStream());
  http.end();
  if (err) { Serial.printf("[CONFIG] parse fail: %s\n", err.c_str()); return false; }

  int v = doc["countdown_seconds"] | -1;
  if (v >= COUNTDOWN_MIN_SECONDS && v <= COUNTDOWN_MAX_SECONDS) {
    if (v != currentCountdownSec.load()) {
      Serial.printf("[CONFIG] countdown %d -> %d\n", currentCountdownSec.load(), v);
      currentCountdownSec.store(v);
      prefs.putInt(PREFS_KEY_CD, v);
    }
  }
  int ph = doc["ptz_home_seconds"] | 0;
  int pm = doc["ptz_secondary_seconds"] | 0;
  if (ph > 0 && ph != ptzHomeSec.load()) {
    Serial.printf("[CONFIG] ptz_home %d -> %d\n", ptzHomeSec.load(), ph);
    ptzHomeSec.store(ph);
  }
  if (pm > 0 && pm != ptzSecondarySec.load()) {
    Serial.printf("[CONFIG] ptz_masina %d -> %d\n", ptzSecondarySec.load(), pm);
    ptzSecondarySec.store(pm);
  }
  return v >= COUNTDOWN_MIN_SECONDS && v <= COUNTDOWN_MAX_SECONDS;
}

static bool sendHeartbeat() {
  if (!netReady()) return false;

  HTTPClient http;
  http.setReuse(false);
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(HEARTBEAT_URL)) { httpFailCount.fetch_add(1); return false; }
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<320> doc;
  if (tempValid.load()) doc["temp_c"] = tempCelsius.load();
  doc["fan_on"]            = fanEnabled.load();
  doc["wifi_ssid"]         = WIFI_SSID;
  doc["countdown_seconds"] = countdownIsActive() ? countdownRemainingSeconds()
                                                 : currentCountdownSec.load();
  doc["state"]      = countdownIsActive() ? "COUNTDOWN" : "IDLE";
  doc["fw"]         = FIRMWARE_VERSION;
  doc["uptime_s"]   = (uint32_t)(millis() / 1000UL);
  doc["rssi"]       = WiFi.RSSI();
  doc["free_heap"]  = (uint32_t)ESP.getFreeHeap();
  doc["wifi_rc"]    = wifiReconnectCount.load();
  doc["http_fails"] = httpFailCount.load();

  char payload[320];
  size_t n = serializeJson(doc, payload, sizeof(payload));

  esp_task_wdt_reset();
  int code = http.POST((uint8_t *)payload, n);
  esp_task_wdt_reset();
  http.end();

  if (code <= 0) {
    Serial.printf("[HB] fail: %s\n", http.errorToString(code).c_str());
    httpFailCount.fetch_add(1);
    return false;
  }
  if (code != 200) {
    Serial.printf("[HB] -> %d\n", code);
    return false;
  }
  return true;
}

static void resetWiFiStack() {
  Serial.println("[RECOVER] reset WiFi stack");
  WiFi.disconnect(true, true);
  vTaskDelay(pdMS_TO_TICKS(200));
  esp_task_wdt_reset();
  WiFi.mode(WIFI_OFF);
  vTaskDelay(pdMS_TO_TICKS(200));
  esp_task_wdt_reset();
  wifiConnected.store(false);
  wifiHadIp.store(false);
  wifiBackoffMs = WIFI_RETRY_MIN_MS;
  beginWiFiConnect();
}

// =============================================================================
// Net task (core 0) - isolated, can block safely
// =============================================================================
static void netTask(void *param) {
  (void)param;
  esp_task_wdt_add(NULL);
  Serial.println("[NET] task started on core 0");

  for (;;) {
    esp_task_wdt_reset();
    maintainWiFi();

    // Process outbound events (non-blocking receive)
    NetEvent ev;
    while (xQueueReceive(netEventQueue, &ev, 0) == pdTRUE) {
      esp_task_wdt_reset();
      if (ev.type == EVT_COUNTER_STARTED) {
        postCounterStart(ev.value);
      }
      esp_task_wdt_reset();
    }

    // Periodic tasks
    unsigned long now = millis();

    if (netReady()) {
      if (lastConfigFetchMs == 0 || timeReached(now, lastConfigFetchMs, CONFIG_REFRESH_MS)) {
        lastConfigFetchMs = now;
        esp_task_wdt_reset();
        fetchConfig();
        esp_task_wdt_reset();
      }

      if (lastHeartbeatMs == 0 || timeReached(now, lastHeartbeatMs, HEARTBEAT_INTERVAL_MS)) {
        lastHeartbeatMs = now;
        esp_task_wdt_reset();
        bool ok = sendHeartbeat();
        esp_task_wdt_reset();

        if (ok) {
          consecutiveHbFails.store(0);
          wifiResetDoneThisBurst = false;
        } else {
          int f = consecutiveHbFails.fetch_add(1) + 1;
          Serial.printf("[HB] streak=%d\n", f);
          if (f >= MAX_HB_FAILS_BEFORE_REBOOT) {
            Serial.println("[RECOVER] prea multe fail-uri, reboot");
            vTaskDelay(pdMS_TO_TICKS(300));
            ESP.restart();
          } else if (!wifiResetDoneThisBurst && f >= MAX_HB_FAILS_BEFORE_WIFI_RESET) {
            wifiResetDoneThisBurst = true;
            resetWiFiStack();
          }
        }
      }
    }

    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

// =============================================================================
// Watchdog init
// =============================================================================
static void initWatchdog() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_deinit();
  esp_task_wdt_config_t cfg = {
      .timeout_ms     = WDT_TIMEOUT_S * 1000,
      .idle_core_mask = 0,
      .trigger_panic  = true,
  };
  esp_err_t e = esp_task_wdt_init(&cfg);
  Serial.printf("[WDT] init(core3) -> %d\n", e);
#else
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
  Serial.println("[WDT] init(core2)");
#endif
  esp_task_wdt_add(NULL);
}

// =============================================================================
// Setup / loop
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("\n=== Tedde ESP fw=%s | server=%s ===\n", FIRMWARE_VERSION, SERVER_BASE);
  Serial.printf("[BOOT] reset reason=%d\n", (int)esp_reset_reason());

  initWatchdog();

  if (prefs.begin(PREFS_NS, false)) {
    int saved = prefs.getInt(PREFS_KEY_CD, COUNTDOWN_DEFAULT_SECONDS);
    if (saved >= COUNTDOWN_MIN_SECONDS && saved <= COUNTDOWN_MAX_SECONDS) {
      currentCountdownSec.store(saved);
      Serial.printf("[NVS] restored cd=%d\n", saved);
    }
  }

  snprintf(COUNTER_START_URL, sizeof(COUNTER_START_URL), "%s/counter-start",     SERVER_BASE);
  snprintf(ESP_CONFIG_URL,    sizeof(ESP_CONFIG_URL),    "%s/api/esp/config",    SERVER_BASE);
  snprintf(HEARTBEAT_URL,     sizeof(HEARTBEAT_URL),     "%s/api/esp/heartbeat", SERVER_BASE);

  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN, 100000UL);
  dht.begin();

  initLcd();
  showOverlay("TeddeAuto", "Se initializeaza", 1800);
  renderDisplay();

  netEventQueue = xQueueCreate(8, sizeof(NetEvent));
  if (!netEventQueue) {
    Serial.println("[FATAL] queue alloc failed");
  }

  WiFi.onEvent(onWiFiEvent);

  // Spawn network task pinned to core 0
  BaseType_t ok = xTaskCreatePinnedToCore(
      netTask,
      "netTask",
      8192,
      nullptr,
      1,
      nullptr,
      0);
  Serial.printf("[TASK] netTask spawn=%d\n", ok == pdPASS ? 1 : 0);

  readTemperatureIfNeeded();
  renderDisplay();
  esp_task_wdt_reset();
}

void loop() {
  esp_task_wdt_reset();

  // UI-only work: non-blocking, tight loop
  readTemperatureIfNeeded();
  handleTriggerButton();
  stopCountdownIfExpired();
  maintainLcdHealth();
  renderDisplay();

  // Short sleep keeps IDLE alive but still ~50Hz button polling
  vTaskDelay(pdMS_TO_TICKS(20));
}