// Tedde ESP32 firmware stored as .c in the repo, but this is Arduino C++ code.
// Flash it as an Arduino sketch / .ino / .cpp source for ESP32.
//
// Hardware profile:
// - ESP32 DevKitC / ESP32-WROOM-32D
// - LCD1602 + I2C backpack (PCF8574/PCF8574A): SDA GPIO21, SCL GPIO22
// - DHT11 (temperatură / umiditate) on GPIO18
// - Fan / ventilator (relay) on GPIO4 (active HIGH)
// - Trigger button on GPIO25 to GND (INPUT_PULLUP)
//
// Note: this firmware tolerates the current direct ESP32(3.3V) -> backpack(5V)
// I2C wiring, but that is not the ideal electrical setup. If the LCD is unstable,
// add a bidirectional level shifter on SDA/SCL.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <Wire.h>

// =====================================================
// User configuration
// =====================================================
static const char *WIFI_SSID = "Ghile";
static const char *WIFI_PASS = "ghilezan";
static const char *SERVER_BASE = "http://10.27.252.192:8000";

static const uint8_t LCD_SDA_PIN = 21;
static const uint8_t LCD_SCL_PIN = 22;
static const uint8_t LCD_COLUMNS = 16;
static const uint8_t LCD_ROWS = 2;

static const uint8_t DHT_PIN = 18;
static const uint8_t DHT_TYPE = DHT11;
static const uint8_t FAN_PIN = 4;
static const uint8_t BUTTON_PIN = 25;

static const int COUNTDOWN_DEFAULT_SECONDS = 30;
static const int FAN_ON_TEMP_C = 40;
static const int FAN_OFF_TEMP_C = 35;

static const unsigned long WIFI_RETRY_INTERVAL_MS = 10000UL;
static const unsigned long LCD_RESCAN_INTERVAL_MS = 10000UL;
static const unsigned long STATUS_POLL_INTERVAL_MS = 1000UL;
static const unsigned long CONFIG_REFRESH_INTERVAL_MS = 60000UL;
static const unsigned long TEMP_READ_INTERVAL_MS = 5000UL;
static const unsigned long PAGE_ROTATE_INTERVAL_MS = 2500UL;
static const unsigned long BUTTON_DEBOUNCE_MS = 45UL;
static const unsigned long MESSAGE_DURATION_MS = 1600UL;
static const unsigned long SERVER_STALE_AFTER_MS = 4000UL;
static const uint16_t HTTP_TIMEOUT_MS = 1500;

// =====================================================
// Backend URLs
// =====================================================
char COUNTER_START_URL[160];
char ESP_CONFIG_URL[160];
char WORKFLOW_STATUS_URL[160];

// =====================================================
// Device state
// =====================================================
enum DeviceState {
  STATE_BOOT,
  STATE_LCD_INIT,
  STATE_WIFI_CONNECTING,
  STATE_IDLE_READY,
  STATE_TRIGGER_POSTING,
  STATE_RECORDING,
  STATE_DEGRADED,
};

enum UiPage {
  PAGE_STATUS = 0,
  PAGE_ENV = 1,
};

struct TempStatus {
  bool valid;
  int celsius;
};

struct WorkflowStatus {
  bool busy;
  int remainingSeconds;
  int durationSeconds;
  char eventId[64];
  char selectedPlate[32];
  char error[64];
};

struct OverlayMessage {
  bool active;
  char line1[17];
  char line2[17];
  unsigned long untilMs;
};

enum PostTriggerResult {
  POST_RESULT_TRIGGERED,
  POST_RESULT_BUSY,
  POST_RESULT_FAILED,
};

// =====================================================
// Globals
// =====================================================
DHT dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C *lcd = nullptr;
uint8_t lcdAddress = 0;
bool lcdReady = false;

DeviceState deviceState = STATE_BOOT;
UiPage currentPage = PAGE_STATUS;
OverlayMessage overlay = {false, "", "", 0};
WorkflowStatus workflow = {false, 0, 0, "", "", ""};
TempStatus temperature = {false, 0};

bool fanEnabled = false;
bool triggerInFlight = false;
bool configLoaded = false;
bool lastWiFiConnected = false;
bool lastServerReachable = false;
bool lastTempValid = true;

int countdownSeconds = COUNTDOWN_DEFAULT_SECONDS;
int recordingDurationSeconds = COUNTDOWN_DEFAULT_SECONDS;

bool fallbackRecordingActive = false;
int fallbackRemainingSeconds = 0;
unsigned long fallbackLastTickMs = 0;

unsigned long lastWiFiAttemptMs = 0;
unsigned long lastLcdScanMs = 0;
unsigned long lastStatusPollMs = 0;
unsigned long lastConfigRefreshMs = 0;
unsigned long lastTempReadMs = 0;
unsigned long lastPageSwitchMs = 0;
unsigned long lastBackendSuccessMs = 0;
unsigned long lastButtonChangeMs = 0;

int lastRawButtonState = HIGH;
int debouncedButtonState = HIGH;

char lastRenderedLine1[17] = "";
char lastRenderedLine2[17] = "";

// =====================================================
// Utility helpers
// =====================================================
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

bool isServerReachable() {
  if (!isWiFiConnected()) {
    return false;
  }
  unsigned long now = millis();
  return lastBackendSuccessMs != 0 && (now - lastBackendSuccessMs) <= SERVER_STALE_AFTER_MS;
}

bool isWorkflowBusyDerived() {
  if (workflow.busy && isServerReachable()) {
    return true;
  }
  return fallbackRecordingActive && fallbackRemainingSeconds > 0;
}

int currentRemainingSeconds() {
  if (workflow.busy && isServerReachable()) {
    return workflow.remainingSeconds;
  }
  if (fallbackRecordingActive) {
    return fallbackRemainingSeconds;
  }
  return countdownSeconds;
}

void setDeviceStateFromSignals() {
  if (!lcdReady) {
    deviceState = STATE_LCD_INIT;
    return;
  }

  if (triggerInFlight) {
    deviceState = STATE_TRIGGER_POSTING;
    return;
  }

  if (!isWiFiConnected()) {
    deviceState = STATE_WIFI_CONNECTING;
    return;
  }

  if (isWorkflowBusyDerived()) {
    deviceState = STATE_RECORDING;
    return;
  }

  if (!isServerReachable() || !temperature.valid) {
    deviceState = STATE_DEGRADED;
    return;
  }

  deviceState = STATE_IDLE_READY;
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

void markBackendSuccess() {
  lastBackendSuccessMs = millis();
}

void clearWorkflowStrings() {
  workflow.eventId[0] = '\0';
  workflow.selectedPlate[0] = '\0';
  workflow.error[0] = '\0';
}

// =====================================================
// LCD / I2C
// =====================================================
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
  lastRenderedLine1[0] = '\0';
  lastRenderedLine2[0] = '\0';
}

bool initLcdFromBus() {
  uint8_t address = scanForLcdAddress();
  if (address == 0) {
    destroyLcd();
    Serial.println("[LCD] No I2C device found for LCD1602 backpack");
    return false;
  }

  destroyLcd();
  lcd = new LiquidCrystal_I2C(address, LCD_COLUMNS, LCD_ROWS);
  lcd->init();
  lcd->backlight();
  lcd->clear();

  lcdAddress = address;
  lcdReady = true;
  Serial.printf("[LCD] Initialized on I2C address 0x%02X\n", lcdAddress);
  showOverlay("BOOT", "TEDDE READY", 1800UL);
  return true;
}

void maintainLcd() {
  if (lcdReady) {
    return;
  }
  unsigned long now = millis();
  if (lastLcdScanMs != 0 && (now - lastLcdScanMs) < LCD_RESCAN_INTERVAL_MS) {
    return;
  }
  lastLcdScanMs = now;
  initLcdFromBus();
}

void renderLcdLines(const char *line1, const char *line2, bool force = false) {
  if (!lcdReady || lcd == nullptr) {
    return;
  }

  char out1[17];
  char out2[17];
  copyText16(out1, line1);
  copyText16(out2, line2);

  if (!force && strcmp(out1, lastRenderedLine1) == 0 && strcmp(out2, lastRenderedLine2) == 0) {
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
  const char *recText = isWorkflowBusyDerived() ? "REC" : "NOREC";
  const char *wifiText = isWiFiConnected() ? "OK" : "--";
  const char *serverText = isServerReachable() ? "OK" : "--";

  snprintf(line1, 17, "%s W:%s S:%s", recText, wifiText, serverText);
  if (isWorkflowBusyDerived()) {
    snprintf(line2, 17, "LEFT %4ds", currentRemainingSeconds());
  } else {
    snprintf(line2, 17, "READY %3ds", countdownSeconds);
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
  if (overlay.active) {
    return;
  }

  unsigned long now = millis();
  if (lastPageSwitchMs == 0) {
    lastPageSwitchMs = now;
    return;
  }
  if ((now - lastPageSwitchMs) < PAGE_ROTATE_INTERVAL_MS) {
    return;
  }

  lastPageSwitchMs = now;
  currentPage = (currentPage == PAGE_STATUS) ? PAGE_ENV : PAGE_STATUS;
}

void renderDisplay() {
  if (!lcdReady) {
    return;
  }

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

// =====================================================
// WiFi
// =====================================================
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
    if (lastWiFiConnected) {
      Serial.println("[WiFi] Lost connection");
      showOverlay("WIFI FAIL", "RECONNECTING");
    }

    if (lastWiFiAttemptMs == 0 || (now - lastWiFiAttemptMs) >= WIFI_RETRY_INTERVAL_MS) {
      beginWiFiConnect();
    }
  } else if (!lastWiFiConnected) {
    Serial.print("[WiFi] Connected. IP: ");
    Serial.println(WiFi.localIP());
    lastConfigRefreshMs = 0;
    lastStatusPollMs = 0;
  }

  lastWiFiConnected = connected;
}

// =====================================================
// HTTP / backend
// =====================================================
bool fetchConfigFromBackend() {
  if (!isWiFiConnected()) {
    return false;
  }

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(ESP_CONFIG_URL)) {
    Serial.println("[HTTP] Failed to begin /api/esp/config");
    return false;
  }

  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[HTTP] /api/esp/config returned %d\n", code);
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[JSON] /api/esp/config parse failed: %s\n", err.c_str());
    return false;
  }

  int fetchedCountdown = doc["countdown_seconds"] | 0;
  int fetchedRecording = doc["recording_duration_seconds"] | 0;

  if (fetchedCountdown > 0) {
    countdownSeconds = fetchedCountdown;
  }
  if (fetchedRecording > 0) {
    recordingDurationSeconds = fetchedRecording;
  }
  if (countdownSeconds <= 0) {
    countdownSeconds = COUNTDOWN_DEFAULT_SECONDS;
  }
  if (recordingDurationSeconds <= 0) {
    recordingDurationSeconds = countdownSeconds;
  }

  configLoaded = true;
  lastConfigRefreshMs = millis();
  markBackendSuccess();

  Serial.printf(
    "[HTTP] /api/esp/config ok: countdown=%d recording=%d\n",
    countdownSeconds,
    recordingDurationSeconds
  );
  return true;
}

bool fetchWorkflowStatusFromBackend() {
  if (!isWiFiConnected()) {
    return false;
  }

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(WORKFLOW_STATUS_URL)) {
    Serial.println("[HTTP] Failed to begin /api/workflow/status");
    return false;
  }

  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[HTTP] /api/workflow/status returned %d\n", code);
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  StaticJsonDocument<768> doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[JSON] /api/workflow/status parse failed: %s\n", err.c_str());
    return false;
  }

  workflow.busy = doc["busy"] | false;
  workflow.remainingSeconds = doc["remaining_seconds"] | 0;
  workflow.durationSeconds = doc["duration_seconds"] | 0;
  const char *eventId = doc["event_id"];
  const char *selectedPlate = doc["selected_plate"];
  const char *errorText = doc["error"];
  copyTextSized(workflow.eventId, sizeof(workflow.eventId), eventId ? eventId : "");
  copyTextSized(workflow.selectedPlate, sizeof(workflow.selectedPlate), selectedPlate ? selectedPlate : "");
  copyTextSized(workflow.error, sizeof(workflow.error), errorText ? errorText : "");

  if (workflow.busy) {
    fallbackRecordingActive = true;
    fallbackRemainingSeconds = workflow.remainingSeconds;
    fallbackLastTickMs = millis();
  } else {
    fallbackRecordingActive = false;
    fallbackRemainingSeconds = 0;
  }

  markBackendSuccess();
  lastStatusPollMs = millis();

  Serial.printf(
    "[HTTP] /api/workflow/status ok: busy=%s remaining=%d event=%s plate=%s\n",
    workflow.busy ? "true" : "false",
    workflow.remainingSeconds,
    workflow.eventId,
    workflow.selectedPlate
  );
  return true;
}

void tickFallbackRecording() {
  if (!fallbackRecordingActive || fallbackRemainingSeconds <= 0) {
    fallbackRecordingActive = false;
    return;
  }

  unsigned long now = millis();
  if (fallbackLastTickMs == 0) {
    fallbackLastTickMs = now;
    return;
  }

  while ((now - fallbackLastTickMs) >= 1000UL && fallbackRemainingSeconds > 0) {
    fallbackRemainingSeconds--;
    fallbackLastTickMs += 1000UL;
  }

  if (fallbackRemainingSeconds <= 0) {
    fallbackRemainingSeconds = 0;
    fallbackRecordingActive = false;
  }
}

void refreshBackendSignals() {
  unsigned long now = millis();

  if (isWiFiConnected()) {
    bool shouldPollStatus = lastStatusPollMs == 0 || (now - lastStatusPollMs) >= STATUS_POLL_INTERVAL_MS;
    if (shouldPollStatus) {
      fetchWorkflowStatusFromBackend();
    }

    bool shouldRefreshConfig = !configLoaded || (!isWorkflowBusyDerived() && (lastConfigRefreshMs == 0 || (now - lastConfigRefreshMs) >= CONFIG_REFRESH_INTERVAL_MS));
    if (shouldRefreshConfig) {
      fetchConfigFromBackend();
    }
  }

  tickFallbackRecording();
}

PostTriggerResult postCounterStart() {
  if (!isWiFiConnected()) {
    Serial.println("[HTTP] POST /counter-start skipped: no WiFi");
    return POST_RESULT_FAILED;
  }

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(COUNTER_START_URL)) {
    Serial.println("[HTTP] Failed to begin /counter-start");
    return POST_RESULT_FAILED;
  }

  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<128> requestDoc;
  requestDoc["event"] = "counter_started";
  requestDoc["value"] = countdownSeconds;

  String payload;
  serializeJson(requestDoc, payload);

  int code = http.POST(payload);
  if (code <= 0) {
    Serial.printf("[HTTP] POST /counter-start failed: %s\n", http.errorToString(code).c_str());
    http.end();
    return POST_RESULT_FAILED;
  }

  String body = http.getString();
  http.end();

  StaticJsonDocument<256> responseDoc;
  DeserializationError err = deserializeJson(responseDoc, body);
  if (err) {
    Serial.printf("[JSON] /counter-start parse failed: %s\n", err.c_str());
    return POST_RESULT_FAILED;
  }

  const char *status = responseDoc["status"];
  int responseDuration = responseDoc["recording_seconds"] | 0;
  const char *responseEvent = responseDoc["event"];
  copyTextSized(workflow.eventId, sizeof(workflow.eventId), responseEvent ? responseEvent : "");

  if (status != nullptr && strcmp(status, "triggered") == 0) {
    if (responseDuration > 0) {
      fallbackRecordingActive = true;
      fallbackRemainingSeconds = responseDuration;
    } else {
      fallbackRecordingActive = true;
      fallbackRemainingSeconds = countdownSeconds;
    }
    fallbackLastTickMs = millis();
    workflow.busy = true;
    workflow.remainingSeconds = fallbackRemainingSeconds;
    markBackendSuccess();
    Serial.printf("[HTTP] /counter-start triggered: %s\n", body.c_str());
    return POST_RESULT_TRIGGERED;
  }

  if (status != nullptr && strcmp(status, "busy") == 0) {
    Serial.printf("[HTTP] /counter-start busy: %s\n", body.c_str());
    return POST_RESULT_BUSY;
  }

  Serial.printf("[HTTP] /counter-start unexpected response: %s\n", body.c_str());
  return POST_RESULT_FAILED;
}

// =====================================================
// Temperature / fan
// =====================================================
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
  temperature.celsius = static_cast<int>(measured + (measured >= 0 ? 0.5f : -0.5f));
  applyFanStateFromTemperature();
  Serial.printf("[DHT] Temperature=%dC fan=%s\n", temperature.celsius, fanEnabled ? "ON" : "OFF");
}

// =====================================================
// Button handling
// =====================================================
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

  if (triggerInFlight || isWorkflowBusyDerived()) {
    showOverlay("BUSY", "WORKFLOW ON");
    Serial.println("[BTN] Ignored: workflow already active");
    return;
  }

  if (!isWiFiConnected()) {
    showOverlay("WIFI FAIL", "NO TRIGGER");
    Serial.println("[BTN] Ignored: no WiFi");
    return;
  }

  triggerInFlight = true;
  showOverlay("POSTING", "WAIT...");
  setDeviceStateFromSignals();

  PostTriggerResult postResult = postCounterStart();
  triggerInFlight = false;

  if (postResult == POST_RESULT_BUSY) {
    showOverlay("BUSY", "WORKFLOW ON");
    setDeviceStateFromSignals();
    return;
  }

  if (postResult != POST_RESULT_TRIGGERED) {
    if (!isServerReachable() && isWiFiConnected()) {
      showOverlay("SRV FAIL", "POST FAIL");
    } else {
      showOverlay("POST FAIL", "TRY AGAIN");
    }
    setDeviceStateFromSignals();
    return;
  }

  showOverlay("POST OK", "CHECK REC");
  if (!fetchWorkflowStatusFromBackend()) {
    // Keep the short local fallback until the next successful poll.
    Serial.println("[BTN] Trigger succeeded, waiting for status refresh fallback");
  }
  setDeviceStateFromSignals();
}

// =====================================================
// Transition-based warnings
// =====================================================
void emitTransitionWarnings() {
  bool wifiNow = isWiFiConnected();
  bool serverNow = isServerReachable();
  bool tempNow = temperature.valid;

  if (wifiNow && !serverNow && lastServerReachable) {
    showOverlay("SRV FAIL", "CHECK API");
  }
  if (!tempNow && lastTempValid) {
    showOverlay("TEMP ERR", "FAN SAFE OFF");
  }

  lastServerReachable = serverNow;
  lastTempValid = tempNow;
}

// =====================================================
// Setup / loop
// =====================================================
void setup() {
  Serial.begin(115200);

  snprintf(COUNTER_START_URL, sizeof(COUNTER_START_URL), "%s/counter-start", SERVER_BASE);
  snprintf(ESP_CONFIG_URL, sizeof(ESP_CONFIG_URL), "%s/api/esp/config", SERVER_BASE);
  snprintf(WORKFLOW_STATUS_URL, sizeof(WORKFLOW_STATUS_URL), "%s/api/workflow/status", SERVER_BASE);

  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN, 100000UL);
  dht.begin();

  clearWorkflowStrings();
  fallbackRemainingSeconds = countdownSeconds;

  deviceState = STATE_BOOT;
  maintainLcd();
  renderDisplay();

  beginWiFiConnect();
  readTemperatureIfNeeded();
  fetchConfigFromBackend();
  fetchWorkflowStatusFromBackend();
  setDeviceStateFromSignals();
  renderDisplay();
}

void loop() {
  maintainLcd();
  maintainWiFi();
  readTemperatureIfNeeded();
  refreshBackendSignals();
  emitTransitionWarnings();
  handleTriggerButton();
  setDeviceStateFromSignals();
  renderDisplay();
  delay(5);
}
