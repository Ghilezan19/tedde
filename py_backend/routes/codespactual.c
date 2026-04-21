#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <Preferences.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#define FIRMWARE_VERSION "1.1.0-prod"

// =========================
// Config
// =========================
static const char *WIFI_SSID = "Ghile";
static const char *WIFI_PASS = "ghilezan";
static const char *SERVER_BASE = "http://10.27.252.10:8000";

static const uint8_t LCD_SDA_PIN = 21;
static const uint8_t LCD_SCL_PIN = 22;
static const uint8_t LCD_COLUMNS = 16;
static const uint8_t LCD_ROWS = 2;

static const uint8_t DHT_PIN = 18;
static const uint8_t DHT_TYPE = DHT11;
static const uint8_t FAN_PIN = 4;
static const uint8_t BUTTON_PIN = 25;

static const int COUNTDOWN_DEFAULT_SECONDS = 30;
static const int COUNTDOWN_MIN_SECONDS = 5;
static const int COUNTDOWN_MAX_SECONDS = 3600;
static const int FAN_ON_TEMP_C = 25;
static const int FAN_OFF_TEMP_C = 22;

static const unsigned long WIFI_RETRY_INTERVAL_MS = 10000UL;
static const unsigned long TEMP_READ_INTERVAL_MS = 5000UL;
static const unsigned long PAGE_ROTATE_INTERVAL_MS = 2500UL;
static const unsigned long BUTTON_DEBOUNCE_MS = 45UL;
static const unsigned long MESSAGE_DURATION_MS = 1500UL;
static const unsigned long CONFIG_REFRESH_INTERVAL_MS = 60000UL;   // resync /api/esp/config every 60s
static const unsigned long HEARTBEAT_INTERVAL_MS = 15000UL;        // POST /api/esp/heartbeat every 15s
static const uint16_t HTTP_TIMEOUT_MS = 3000;                      // per HTTP call
static const uint16_t HTTP_CONNECT_TIMEOUT_MS = 2000;              // TCP connect phase

// Watchdog: must be > (worst-case blocking time in loop).
// Worst case = 2 HTTP calls back-to-back during maintainServerSync = ~6s, plus margin.
static const uint32_t WDT_TIMEOUT_S = 20;

// Auto-recover: if heartbeat POST fails this many times in a row while WiFi is up,
// reset the WiFi stack; after double that, reboot the whole board.
static const int MAX_HEARTBEAT_FAILS_BEFORE_WIFI_RESET = 8;   // ~2 minutes
static const int MAX_HEARTBEAT_FAILS_BEFORE_REBOOT     = 20;  // ~5 minutes

// =========================
// URLs
// =========================
char COUNTER_START_URL[160];
char ESP_CONFIG_URL[160];
char WORKFLOW_STATUS_URL[160];
char HEARTBEAT_URL[160];

// =========================
// Structs
// =========================
enum UiPage {
  PAGE_STATUS = 0,
  PAGE_ENV = 1
};

struct TempStatus {
  bool valid;
  int celsius;
};

struct OverlayMessage {
  bool active;
  char line1[17];
  char line2[17];
  unsigned long untilMs;
};

// =========================
// Globals
// =========================
DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C *lcd = nullptr;

bool lcdReady = false;
uint8_t lcdAddress = 0;

TempStatus temperature = {false, 0};
OverlayMessage overlay = {false, "", "", 0};

bool fanEnabled = false;
bool wifiWasConnected = false;

bool countdownActive = false;
int countdownRemaining = COUNTDOWN_DEFAULT_SECONDS;
unsigned long countdownLastTickMs = 0;

// Runtime value synced from server's /api/esp/config (falls back to DEFAULT)
int currentCountdownSeconds = COUNTDOWN_DEFAULT_SECONDS;

bool triggerInFlight = false;

unsigned long lastWiFiAttemptMs = 0;
unsigned long lastTempReadMs = 0;
unsigned long lastPageSwitchMs = 0;
unsigned long lastButtonChangeMs = 0;
unsigned long lastConfigFetchMs = 0;
unsigned long lastHeartbeatMs = 0;

// Network auto-recovery counters
int consecutiveHeartbeatFails = 0;
bool wifiResetDoneAtFailCount = false;

// Non-volatile storage (survives power loss) for last-known-good countdown.
Preferences prefs;
static const char *PREFS_NAMESPACE = "tedde";
static const char *PREFS_KEY_COUNTDOWN = "cd_s";

UiPage currentPage = PAGE_STATUS;

int lastRawButtonState = HIGH;
int debouncedButtonState = HIGH;

char lastRenderedLine1[17] = "";
char lastRenderedLine2[17] = "";

// =========================
// Helpers
// =========================
void copyText16(char *dest, const char *src) {
  if (!dest) return;
  if (!src) src = "";

  size_t i = 0;
  for (; i < 16 && src[i] != '\0'; ++i) {
    dest[i] = src[i];
  }
  for (; i < 16; ++i) {
    dest[i] = ' ';
  }
  dest[16] = '\0';
}

void copyTextSized(char *dest, size_t destSize, const char *src) {
  if (!dest || destSize == 0) return;
  if (!src) src = "";

  size_t i = 0;
  for (; i + 1 < destSize && src[i] != '\0'; ++i) {
    dest[i] = src[i];
  }
  dest[i] = '\0';
}

bool isWiFiConnected() {
  return WiFi.status() == WL_CONNECTED;
}

void showOverlay(const char *line1, const char *line2, unsigned long durationMs = MESSAGE_DURATION_MS) {
  copyText16(overlay.line1, line1);
  copyText16(overlay.line2, line2);
  overlay.active = true;
  overlay.untilMs = millis() + durationMs;
}

void expireOverlayIfNeeded() {
  if (overlay.active && millis() >= overlay.untilMs) {
    overlay.active = false;
  }
}

// =========================
// LCD
// =========================
uint8_t scanForLcdAddress() {
  for (uint8_t address = 0x03; address <= 0x77; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      return address;
    }
  }
  return 0;
}

void destroyLcd() {
  if (lcd != nullptr) {
    delete lcd;
    lcd = nullptr;
  }
  lcdReady = false;
  lcdAddress = 0;
}

bool initLcd() {
  uint8_t address = scanForLcdAddress();
  if (address == 0) {
    Serial.println("[LCD] Nu am gasit display I2C");
    destroyLcd();
    return false;
  }

  destroyLcd();
  lcd = new LiquidCrystal_I2C(address, LCD_COLUMNS, LCD_ROWS);
  lcd->init();
  lcd->backlight();
  lcd->clear();

  lcdAddress = address;
  lcdReady = true;

  Serial.printf("[LCD] Gasit la adresa 0x%02X\n", lcdAddress);
  showOverlay("BOOT", "TEDDE READY", 1800);
  return true;
}

void renderLcdLines(const char *line1, const char *line2) {
  if (!lcdReady || lcd == nullptr) return;

  char out1[17];
  char out2[17];
  copyText16(out1, line1);
  copyText16(out2, line2);

  if (strcmp(out1, lastRenderedLine1) == 0 && strcmp(out2, lastRenderedLine2) == 0) {
    return;
  }

  lcd->setCursor(0, 0);
  lcd->print(out1);
  lcd->setCursor(0, 1);
  lcd->print(out2);

  copyTextSized(lastRenderedLine1, sizeof(lastRenderedLine1), out1);
  copyTextSized(lastRenderedLine2, sizeof(lastRenderedLine2), out2);
}

void buildStatusPage(char *line1, char *line2) {
  snprintf(line1, 17, "WIFI:%s BTN:%s",
           isWiFiConnected() ? "OK" : "--",
           countdownActive ? "ON" : "OFF");

  if (countdownActive) {
    snprintf(line2, 17, "LEFT %4ds", countdownRemaining);
  } else {
    snprintf(line2, 17, "READY %3ds", currentCountdownSeconds);
  }
}

void buildEnvPage(char *line1, char *line2) {
  if (temperature.valid) {
    snprintf(line1, 17, "TEMP %2dC", temperature.celsius);
  } else {
    snprintf(line1, 17, "TEMP ERR");
  }

  snprintf(line2, 17, "FAN %s", fanEnabled ? "ON" : "OFF");
}

void rotatePageIfNeeded() {
  if (overlay.active) return;

  unsigned long now = millis();
  if (lastPageSwitchMs == 0) {
    lastPageSwitchMs = now;
    return;
  }

  if (now - lastPageSwitchMs >= PAGE_ROTATE_INTERVAL_MS) {
    lastPageSwitchMs = now;
    currentPage = (currentPage == PAGE_STATUS) ? PAGE_ENV : PAGE_STATUS;
  }
}

void renderDisplay() {
  if (!lcdReady) return;

  expireOverlayIfNeeded();
  rotatePageIfNeeded();

  char line1[17];
  char line2[17];

  if (overlay.active) {
    copyTextSized(line1, sizeof(line1), overlay.line1);
    copyTextSized(line2, sizeof(line2), overlay.line2);
    renderLcdLines(line1, line2);
    return;
  }

  if (currentPage == PAGE_STATUS) {
    buildStatusPage(line1, line2);
  } else {
    buildEnvPage(line1, line2);
  }

  renderLcdLines(line1, line2);
}

// =========================
// WiFi
// =========================
void beginWiFiConnect() {
  Serial.printf("[WiFi] Connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  lastWiFiAttemptMs = millis();
}

void maintainWiFi() {
  bool connected = isWiFiConnected();
  unsigned long now = millis();

  if (!connected) {
    if (wifiWasConnected) {
      Serial.println("[WiFi] Lost connection");
      showOverlay("WIFI FAIL", "RECONNECTING");
    }

    if (lastWiFiAttemptMs == 0 || (now - lastWiFiAttemptMs) >= WIFI_RETRY_INTERVAL_MS) {
      beginWiFiConnect();
    }
  } else if (!wifiWasConnected) {
    Serial.print("[WiFi] Connected. IP: ");
    Serial.println(WiFi.localIP());
  }

  wifiWasConnected = connected;
}

// =========================
// HTTP
// =========================
void postCounterStart() {
  if (!isWiFiConnected()) {
    Serial.println("[HTTP] skip POST, no WiFi");
    return;
  }

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(COUNTER_START_URL)) {
    Serial.println("[HTTP] begin failed /counter-start");
    return;
  }

  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<128> doc;
  doc["event"] = "counter_started";
  doc["value"] = currentCountdownSeconds;

  String payload;
  serializeJson(doc, payload);

  int code = http.POST(payload);

  if (code <= 0) {
    Serial.printf("[HTTP] POST failed: %s\n", http.errorToString(code).c_str());
    http.end();
    return;
  }

  String body = http.getString();
  Serial.printf("[HTTP] POST /counter-start -> %d | %s\n", code, body.c_str());
  http.end();
}

// Fetch /api/esp/config and apply countdown_seconds to runtime state.
// Returns true on successful update.
bool fetchConfig() {
  if (!isWiFiConnected()) return false;

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(ESP_CONFIG_URL)) {
    Serial.println("[HTTP] begin failed /api/esp/config");
    return false;
  }

  int code = http.GET();
  if (code != 200) {
    Serial.printf("[HTTP] /api/esp/config returned %d\n", code);
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[CONFIG] json parse failed: %s | body=%s\n", err.c_str(), body.c_str());
    return false;
  }

  int v = doc["countdown_seconds"] | -1;
  if (v >= COUNTDOWN_MIN_SECONDS && v <= COUNTDOWN_MAX_SECONDS) {
    if (v != currentCountdownSeconds) {
      Serial.printf("[CONFIG] countdown %d -> %d sec (from server)\n", currentCountdownSeconds, v);
      currentCountdownSeconds = v;
      // Persist to NVS so next boot starts with the latest value even before WiFi is up.
      prefs.putInt(PREFS_KEY_COUNTDOWN, v);
    }
    return true;
  }
  Serial.printf("[CONFIG] invalid countdown_seconds=%d (ignored)\n", v);
  return false;
}

// POST current status to /api/esp/heartbeat so the dashboard can show us live.
bool sendHeartbeat() {
  if (!isWiFiConnected()) return false;

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);

  if (!http.begin(HEARTBEAT_URL)) {
    Serial.println("[HTTP] begin failed /api/esp/heartbeat");
    return false;
  }
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  if (temperature.valid) doc["temp_c"] = temperature.celsius;
  doc["fan_on"] = fanEnabled;
  doc["wifi_ssid"] = WIFI_SSID;
  doc["countdown_seconds"] = countdownActive ? countdownRemaining : currentCountdownSeconds;
  const char *state;
  if (countdownActive)      state = "COUNTDOWN";
  else if (triggerInFlight) state = "TRIGGER";
  else                      state = "IDLE";
  doc["state"] = state;
  doc["fw"] = FIRMWARE_VERSION;
  doc["uptime_s"] = (unsigned long)(millis() / 1000UL);
  doc["rssi"] = WiFi.RSSI();

  String payload;
  serializeJson(doc, payload);

  int code = http.POST(payload);
  http.end();

  if (code <= 0) {
    Serial.printf("[HB] POST failed: %s\n", http.errorToString(code).c_str());
    return false;
  }
  if (code != 200) {
    Serial.printf("[HB] POST -> %d\n", code);
    return false;
  }
  return true;
}

// =========================
// Temperature / fan
// =========================
void applyFanStateFromTemperature() {
  if (!temperature.valid) {
    fanEnabled = false;
    digitalWrite(FAN_PIN, LOW);
    return;
  }

  if (!fanEnabled && temperature.celsius >= FAN_ON_TEMP_C) {
    fanEnabled = true;
  } else if (fanEnabled && temperature.celsius <= FAN_OFF_TEMP_C) {
    fanEnabled = false;
  }

  digitalWrite(FAN_PIN, fanEnabled ? HIGH : LOW);
}

void readTemperatureIfNeeded() {
  unsigned long now = millis();
  if (lastTempReadMs != 0 && (now - lastTempReadMs) < TEMP_READ_INTERVAL_MS) {
    return;
  }

  lastTempReadMs = now;

  float measured = dht.readTemperature();
  if (isnan(measured)) {
    temperature.valid = false;
    temperature.celsius = 0;
    applyFanStateFromTemperature();
    Serial.println("[DHT] Temperature read failed");
    return;
  }

  temperature.valid = true;
  temperature.celsius = (int)(measured + (measured >= 0 ? 0.5f : -0.5f));

  applyFanStateFromTemperature();
  Serial.printf("[DHT] Temperature=%dC fan=%s\n", temperature.celsius, fanEnabled ? "ON" : "OFF");
}

// =========================
// Countdown
// =========================
void startCountdown() {
  countdownActive = true;
  countdownRemaining = currentCountdownSeconds;
  countdownLastTickMs = millis();

  Serial.printf("[COUNTDOWN] Started: %d sec\n", countdownRemaining);
}

void tickCountdown() {
  if (!countdownActive) return;

  unsigned long now = millis();

  while ((now - countdownLastTickMs) >= 1000UL && countdownRemaining > 0) {
    countdownRemaining--;
    countdownLastTickMs += 1000UL;
    Serial.printf("[COUNTDOWN] %d sec left\n", countdownRemaining);
  }

  if (countdownRemaining <= 0) {
    countdownRemaining = 0;
    countdownActive = false;
    showOverlay("COUNTDOWN", "FINISHED");
    Serial.println("[COUNTDOWN] Finished");
  }
}

// =========================
// Button
// =========================
void handleTriggerButton() {
  int rawState = digitalRead(BUTTON_PIN);
  unsigned long now = millis();

  if (rawState != lastRawButtonState) {
    lastButtonChangeMs = now;
    lastRawButtonState = rawState;
  }

  if ((now - lastButtonChangeMs) < BUTTON_DEBOUNCE_MS) {
    return;
  }

  if (rawState == debouncedButtonState) {
    return;
  }

  debouncedButtonState = rawState;

  if (debouncedButtonState != LOW) {
    return;
  }

  if (triggerInFlight || countdownActive) {
    showOverlay("BUSY", "COUNTDOWN ON");
    Serial.println("[BTN] Ignored, countdown active");
    return;
  }

  triggerInFlight = true;

  showOverlay("TRIGGER", "STARTED");
  startCountdown();
  postCounterStart();

  triggerInFlight = false;
}

// =========================
// Setup / loop
// =========================
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("\n=== Tedde ESP fw=%s | server=%s ===\n", FIRMWARE_VERSION, SERVER_BASE);

  // Hardware watchdog: auto-reboot if loop() stalls for > WDT_TIMEOUT_S.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  // Arduino ESP32 core 3.x (ESP-IDF 5.x): struct-based init
  esp_task_wdt_config_t wdt_cfg = {
    .timeout_ms     = WDT_TIMEOUT_S * 1000U,
    .idle_core_mask = 0,
    .trigger_panic  = true,
  };
  esp_task_wdt_init(&wdt_cfg);
#else
  // Arduino ESP32 core 2.x: (timeout_sec, panic)
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
#endif
  esp_task_wdt_add(NULL);

  // Load last-known-good countdown from NVS (survives power loss).
  if (prefs.begin(PREFS_NAMESPACE, false)) {
    int saved = prefs.getInt(PREFS_KEY_COUNTDOWN, COUNTDOWN_DEFAULT_SECONDS);
    if (saved >= COUNTDOWN_MIN_SECONDS && saved <= COUNTDOWN_MAX_SECONDS) {
      currentCountdownSeconds = saved;
      Serial.printf("[NVS] restored countdown=%d\n", saved);
    }
  } else {
    Serial.println("[NVS] prefs.begin failed");
  }

  snprintf(COUNTER_START_URL, sizeof(COUNTER_START_URL), "%s/counter-start", SERVER_BASE);
  snprintf(ESP_CONFIG_URL, sizeof(ESP_CONFIG_URL), "%s/api/esp/config", SERVER_BASE);
  snprintf(WORKFLOW_STATUS_URL, sizeof(WORKFLOW_STATUS_URL), "%s/api/workflow/status", SERVER_BASE);
  snprintf(HEARTBEAT_URL, sizeof(HEARTBEAT_URL), "%s/api/esp/heartbeat", SERVER_BASE);

  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN, 100000UL);
  dht.begin();

  initLcd();
  renderDisplay();

  beginWiFiConnect();
  readTemperatureIfNeeded();
  // Best-effort initial sync; loop() keeps them refreshed after boot
  fetchConfig();
  sendHeartbeat();

  renderDisplay();
}

// Reset the WiFi stack without rebooting — recovers from driver soft-hangs.
void resetWiFiStack() {
  Serial.println("[RECOVER] Resetting WiFi stack");
  showOverlay("RECOVER", "WIFI RESET");
  WiFi.disconnect(true, true);
  delay(200);
  WiFi.mode(WIFI_OFF);
  delay(200);
  beginWiFiConnect();
  wifiWasConnected = false;
}

// Periodically resync config and post heartbeat (idempotent, rate-limited).
// Tracks consecutive heartbeat failures to trigger WiFi reset / reboot as last resort.
void maintainServerSync() {
  unsigned long now = millis();
  if (!isWiFiConnected()) return;

  if (lastConfigFetchMs == 0 || (now - lastConfigFetchMs) >= CONFIG_REFRESH_INTERVAL_MS) {
    lastConfigFetchMs = now;
    fetchConfig();
  }

  if (lastHeartbeatMs == 0 || (now - lastHeartbeatMs) >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    bool ok = sendHeartbeat();
    if (ok) {
      consecutiveHeartbeatFails = 0;
      wifiResetDoneAtFailCount = false;
    } else {
      consecutiveHeartbeatFails++;
      Serial.printf("[HB] fail streak=%d\n", consecutiveHeartbeatFails);

      if (consecutiveHeartbeatFails >= MAX_HEARTBEAT_FAILS_BEFORE_REBOOT) {
        Serial.println("[RECOVER] Too many failures, rebooting");
        showOverlay("REBOOT", "NET FAIL", 1500);
        renderDisplay();
        delay(1500);
        ESP.restart();
      } else if (!wifiResetDoneAtFailCount &&
                 consecutiveHeartbeatFails >= MAX_HEARTBEAT_FAILS_BEFORE_WIFI_RESET) {
        wifiResetDoneAtFailCount = true;
        resetWiFiStack();
      }
    }
  }
}

void loop() {
  esp_task_wdt_reset();  // feed the watchdog — skipping this for >WDT_TIMEOUT_S will reboot the board

  maintainWiFi();
  readTemperatureIfNeeded();
  handleTriggerButton();
  tickCountdown();
  maintainServerSync();
  renderDisplay();
  delay(5);
}