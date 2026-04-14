#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <Wire.h>

// =========================
// Config
// =========================
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
static const int FAN_ON_TEMP_C = 25;
static const int FAN_OFF_TEMP_C = 22;

static const unsigned long WIFI_RETRY_INTERVAL_MS = 10000UL;
static const unsigned long TEMP_READ_INTERVAL_MS = 5000UL;
static const unsigned long PAGE_ROTATE_INTERVAL_MS = 2500UL;
static const unsigned long BUTTON_DEBOUNCE_MS = 45UL;
static const unsigned long MESSAGE_DURATION_MS = 1500UL;
static const uint16_t HTTP_TIMEOUT_MS = 3000;

// =========================
// URLs
// =========================
char COUNTER_START_URL[160];
char ESP_CONFIG_URL[160];
char WORKFLOW_STATUS_URL[160];

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

bool triggerInFlight = false;

unsigned long lastWiFiAttemptMs = 0;
unsigned long lastTempReadMs = 0;
unsigned long lastPageSwitchMs = 0;
unsigned long lastButtonChangeMs = 0;

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
    snprintf(line2, 17, "READY %3ds", COUNTDOWN_DEFAULT_SECONDS);
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
  doc["value"] = COUNTDOWN_DEFAULT_SECONDS;

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

void fetchConfig() {
  if (!isWiFiConnected()) return;

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(ESP_CONFIG_URL)) {
    Serial.println("[HTTP] begin failed /api/esp/config");
    return;
  }

  int code = http.GET();
  if (code <= 0) {
    Serial.printf("[HTTP] /api/esp/config returned %d\n", code);
    http.end();
    return;
  }

  String body = http.getString();
  Serial.printf("[HTTP] /api/esp/config -> %d | %s\n", code, body.c_str());
  http.end();
}

void fetchWorkflowStatus() {
  if (!isWiFiConnected()) return;

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(WORKFLOW_STATUS_URL)) {
    Serial.println("[HTTP] begin failed /api/workflow/status");
    return;
  }

  int code = http.GET();
  if (code <= 0) {
    Serial.printf("[HTTP] /api/workflow/status returned %d\n", code);
    http.end();
    return;
  }

  String body = http.getString();
  Serial.printf("[HTTP] /api/workflow/status -> %d | %s\n", code, body.c_str());
  http.end();
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
  countdownRemaining = COUNTDOWN_DEFAULT_SECONDS;
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

  snprintf(COUNTER_START_URL, sizeof(COUNTER_START_URL), "%s/counter-start", SERVER_BASE);
  snprintf(ESP_CONFIG_URL, sizeof(ESP_CONFIG_URL), "%s/api/esp/config", SERVER_BASE);
  snprintf(WORKFLOW_STATUS_URL, sizeof(WORKFLOW_STATUS_URL), "%s/api/workflow/status", SERVER_BASE);

  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN, 100000UL);
  dht.begin();

  initLcd();
  renderDisplay();

  beginWiFiConnect();
  readTemperatureIfNeeded();
  fetchConfig();
  fetchWorkflowStatus();

  renderDisplay();
}

void loop() {
  maintainWiFi();
  readTemperatureIfNeeded();
  handleTriggerButton();
  tickCountdown();
  renderDisplay();
  delay(5);
}