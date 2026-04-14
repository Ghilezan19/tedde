#include "Arduino_GFX_Library.h"
#include <DHT.h>
#include <WiFi.h>
#include <HTTPClient.h>

// =====================================================
// WiFi / HTTP
// =====================================================
const char* WIFI_SSID = "Ghile";
const char* WIFI_PASS = "ghilezan";
// IP-ul PC-ului unde rulează FastAPI (uvicorn pe portul 8000)
// Verifică cu: ipconfig getifaddr en0  (pe Mac)
const char* SERVER_BASE = "http://10.27.252.192:8000";
// Construite în setup() din SERVER_BASE
char POST_URL[128];
char CONFIG_URL[128];

// =====================================================
// DHT11
// =====================================================
#define DHTPIN   4
#define DHTTYPE  DHT11
DHT dht(DHTPIN, DHTTYPE);

// =====================================================
// Ventilatoare cu histerezis
// Pornesc la 40, se opresc la 35
// =====================================================
#define FAN_PIN        19
#define FAN_ON_TEMP    40
#define FAN_OFF_TEMP   35

// =====================================================
// Buton countdown  (secunde — sincronizat cu GET /api/esp/config dacă reușește)
// =====================================================
#define BUTTON_PIN       23
#define COUNTDOWN_DEFAULT 30

// =====================================================
// LCD pins - Waveshare ESP32-C6-LCD-1.47
// =====================================================
#define TFT_MOSI  6
#define TFT_SCLK  7
#define TFT_CS    14
#define TFT_DC    15
#define TFT_RST   21
#define TFT_BL    22

// =====================================================
// Culori RGB565
// =====================================================
#define BLACK       0x0000
#define WHITE       0xFFFF
#define RED         0xF800
#define GREEN       0x07E0
#define BLUE        0x001F
#define CYAN        0x07FF
#define YELLOW      0xFFE0
#define ORANGE      0xFD20
#define DARKGRAY    0x4208
#define LIGHTGRAY   0xC618
#define MIDGRAY     0x8410
#define NAVY        0x0010
#define BG          0x1082
#define CARD        0x18C3

// =====================================================
// Display
// =====================================================
Arduino_DataBus *bus = new Arduino_ESP32SPI(
  TFT_DC,
  TFT_CS,
  TFT_SCLK,
  TFT_MOSI,
  GFX_NOT_DEFINED
);

Arduino_GFX *gfx = new Arduino_ST7789(
  bus,
  TFT_RST,
  0,
  true,
  172,
  320,
  34,
  0,
  34,
  0
);

// =====================================================
// Variabile
// =====================================================
int lastTemp = -1000;
bool fanState = false;
bool lastFanStateDrawn = false;

unsigned long lastTempReadMs = 0;
unsigned long lastCountdownMs = 0;
unsigned long lastWifiRetryMs = 0;

bool countdownRunning = false;
// Valoare afișată / trimisă la server (aceeași ca RECORDING_DURATION sau ESP_COUNTDOWN din .env)
int countdownStartSeconds = COUNTDOWN_DEFAULT;
int countdownValue = COUNTDOWN_DEFAULT;

int lastButtonState = HIGH;
int currentButtonState = HIGH;

// =====================================================
// Helpers UI
// =====================================================
void drawCenteredTextInBox(const String &text, int x, int y, int w, int h, int size, uint16_t color, uint16_t bg)
{
  int16_t x1, y1;
  uint16_t tw, th;

  gfx->setTextSize(size);
  gfx->getTextBounds(text, 0, 0, &x1, &y1, &tw, &th);

  int cx = x + (w - tw) / 2;
  int cy = y + (h - th) / 2;

  gfx->setTextColor(color, bg);
  gfx->setCursor(cx, cy);
  gfx->print(text);
}

void drawLabel(const String &text, int x, int y, uint16_t color, uint16_t bg, int size = 1)
{
  gfx->setTextSize(size);
  gfx->setTextColor(color, bg);
  gfx->setCursor(x, y);
  gfx->print(text);
}

uint16_t getTempColor(int t)
{
  if (t >= 40) return RED;
  if (t >= 35) return ORANGE;
  if (t >= 20) return GREEN;
  if (t >= 10) return CYAN;
  return BLUE;
}

void drawRoundedCard(int x, int y, int w, int h, uint16_t fillColor)
{
  gfx->fillRoundRect(x, y, w, h, 14, fillColor);
  gfx->drawRoundRect(x, y, w, h, 14, MIDGRAY);
}

// =====================================================
// UI
// =====================================================
void drawHeader()
{
  gfx->fillRoundRect(8, 8, 304, 28, 10, NAVY);
  drawCenteredTextInBox("TEDDE AUTO CAMERA 1", 8, 8, 304, 28, 2, WHITE, NAVY);
}

void drawStaticLayout()
{
  gfx->fillScreen(BG);

  drawHeader();

  drawRoundedCard(10, 48, 145, 92, CARD);
  drawLabel("TEMPERATURA", 24, 60, LIGHTGRAY, CARD, 1);

  drawRoundedCard(165, 48, 145, 92, CARD);
  drawLabel("COUNTDOWN", 192, 60, LIGHTGRAY, CARD, 1);

  drawRoundedCard(10, 146, 300, 18, DARKGRAY);

  drawLabel("DHT11 GPIO4 | FAN GPIO19 | BTN GPIO23", 12, 38, LIGHTGRAY, BG, 1);
}

void drawTemperature(int t)
{
  gfx->fillRect(22, 80, 120, 40, CARD);

  String tempText = String(t) + " C";
  drawCenteredTextInBox(tempText, 18, 78, 128, 42, 3, getTempColor(t), CARD);

  gfx->fillRoundRect(24, 122, 118, 8, 4, DARKGRAY);

  int barW = map(t, 0, 50, 0, 118);
  if (barW < 0) barW = 0;
  if (barW > 118) barW = 118;

  gfx->fillRoundRect(24, 122, barW, 8, 4, getTempColor(t));
}

void drawCountdown(int value, bool running)
{
  gfx->fillRect(177, 76, 120, 48, CARD);

  uint16_t color = WHITE;
  if (value <= 5 && running) color = RED;
  else if (value <= 10 && running) color = ORANGE;
  else if (running) color = CYAN;
  else color = LIGHTGRAY;

  drawCenteredTextInBox(String(value), 173, 74, 128, 46, 4, color, CARD);

  gfx->fillRect(178, 120, 118, 12, CARD);
  if (running) {
    drawCenteredTextInBox("RUNNING", 178, 120, 118, 12, 1, GREEN, CARD);
  } else {
    drawCenteredTextInBox("PRESS BTN", 178, 120, 118, 12, 1, YELLOW, CARD);
  }
}

void drawFanStatus(bool on)
{
  uint16_t bgColor = on ? RED : GREEN;

  gfx->fillRoundRect(12, 148, 296, 14, 8, bgColor);

  String text;
  if (on) text = "VENTILATOARE: PORNITE";
  else    text = "VENTILATOARE: OPRITE";

  drawCenteredTextInBox(text, 12, 148, 296, 14, 1, WHITE, bgColor);
}

void drawError()
{
  gfx->fillRect(22, 80, 120, 40, CARD);
  drawCenteredTextInBox("ERROR", 18, 82, 128, 34, 2, RED, CARD);
}

void drawStartup()
{
  drawStaticLayout();
  drawCenteredTextInBox("-- C", 18, 78, 128, 42, 3, WHITE, CARD);
  drawCountdown(countdownStartSeconds, false);
  drawFanStatus(false);
}

// =====================================================
// WiFi / POST
// =====================================================
void connectWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("Conectare WiFi");
  unsigned long startMs = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - startMs < 10000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi conectat. IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi nereusit");
  }
}

void ensureWiFi()
{
  if (WiFi.status() == WL_CONNECTED) return;

  if (millis() - lastWifiRetryMs >= 10000UL) {
    lastWifiRetryMs = millis();
    Serial.println("Reincerc conectarea la WiFi...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
}

/**
 * Citește countdown_seconds de pe backend (.env) ca LCD și înregistrarea să fie aliniate.
 * Dacă request-ul eșuează, rămâne COUNTDOWN_DEFAULT.
 */
bool fetchTimerFromBackend()
{
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Config timer: fara WiFi");
    return false;
  }

  HTTPClient http;
  http.begin(CONFIG_URL);
  int httpCode = http.GET();

  if (httpCode != 200) {
    Serial.printf("Config timer HTTP: %d\n", httpCode);
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  int keyPos = body.indexOf("\"countdown_seconds\"");
  if (keyPos < 0) {
    Serial.println("Config timer: lipseste countdown_seconds in JSON");
    return false;
  }

  int colon = body.indexOf(':', keyPos);
  if (colon < 0) return false;

  String tail = body.substring(colon + 1);
  tail.trim();
  int v = tail.toInt();
  if (v <= 0 || v > 86400) {
    Serial.printf("Config timer: valoare invalida %d\n", v);
    return false;
  }

  countdownStartSeconds = v;
  if (!countdownRunning) {
    countdownValue = countdownStartSeconds;
  }
  Serial.printf("Timer sincronizat de pe server: %d s\n", countdownStartSeconds);
  return true;
}

void sendCounterStartPost()
{
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("POST ratat: fara WiFi");
    return;
  }

  HTTPClient http;
  http.begin(POST_URL);
  http.addHeader("Content-Type", "application/json");

  String payload = "{";
  payload += "\"event\":\"counter_started\",";
  payload += "\"value\":";
  payload += String(countdownStartSeconds);
  payload += "}";

  int httpCode = http.POST(payload);

  Serial.print("HTTP POST code: ");
  Serial.println(httpCode);

  if (httpCode > 0) {
    String response = http.getString();
    Serial.println("Response:");
    Serial.println(response);
  } else {
    Serial.print("Eroare HTTP: ");
    Serial.println(http.errorToString(httpCode));
  }

  http.end();
}

// =====================================================
// Logică temperatură + histerezis ventilatoare
// =====================================================
void updateFanWithHysteresis(int tempInt)
{
  if (!fanState && tempInt >= FAN_ON_TEMP) {
    fanState = true;
  } else if (fanState && tempInt <= FAN_OFF_TEMP) {
    fanState = false;
  }

  digitalWrite(FAN_PIN, fanState ? HIGH : LOW);

  if (fanState != lastFanStateDrawn) {
    drawFanStatus(fanState);
    lastFanStateDrawn = fanState;
  }
}

void readTemperatureAndControlFan()
{
  float t = dht.readTemperature();

  if (isnan(t)) {
    Serial.println("Eroare citire DHT11");
    digitalWrite(FAN_PIN, LOW);
    fanState = false;
    drawError();
    drawFanStatus(false);
    lastFanStateDrawn = false;
    return;
  }

  int tempInt = (int)t;

  updateFanWithHysteresis(tempInt);

  Serial.print("Temperatura: ");
  Serial.print(tempInt);
  Serial.print(" C | Ventilatoare: ");
  Serial.println(fanState ? "ON" : "OFF");

  if (tempInt != lastTemp) {
    drawTemperature(tempInt);
    lastTemp = tempInt;
  }
}

// =====================================================
// Buton + countdown
// =====================================================
void handleButton()
{
  currentButtonState = digitalRead(BUTTON_PIN);

  if (lastButtonState == HIGH && currentButtonState == LOW) {
    countdownRunning = true;
    countdownValue = countdownStartSeconds;
    lastCountdownMs = millis();
    drawCountdown(countdownValue, true);

    Serial.println("Countdown pornit");
    sendCounterStartPost();
  }

  lastButtonState = currentButtonState;
}

void handleCountdown()
{
  if (!countdownRunning) return;

  if (millis() - lastCountdownMs >= 1000) {
    lastCountdownMs = millis();
    countdownValue--;

    if (countdownValue <= 0) {
      countdownValue = 0;
      countdownRunning = false;
    }

    drawCountdown(countdownValue, countdownRunning);

    Serial.print("Countdown: ");
    Serial.println(countdownValue);
  }
}

// =====================================================
// Setup
// =====================================================
void setup()
{
  Serial.begin(115200);
  dht.begin();

  snprintf(POST_URL, sizeof(POST_URL), "%s/counter-start", SERVER_BASE);
  snprintf(CONFIG_URL, sizeof(CONFIG_URL), "%s/api/esp/config", SERVER_BASE);

  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  if (!gfx->begin()) {
    Serial.println("Eroare init display");
    while (1) {
      delay(100);
    }
  }

  gfx->setRotation(1);
  drawStartup();

  connectWiFi();

  fetchTimerFromBackend();
  drawCountdown(countdownStartSeconds, false);

  readTemperatureAndControlFan();
  lastTempReadMs = millis();
}

// =====================================================
// Loop
// =====================================================
void loop()
{
  ensureWiFi();
  handleButton();
  handleCountdown();

  if (millis() - lastTempReadMs >= 60000UL) {
    lastTempReadMs = millis();
    readTemperatureAndControlFan();
  }
}