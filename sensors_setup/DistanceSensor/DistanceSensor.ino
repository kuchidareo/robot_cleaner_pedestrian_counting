#include <Wire.h>
#include <Unit_Sonic.h>
#include <M5StickCPlus.h>
#include <WiFi.h>
#include <WebSocketsClient.h>

// === WiFi ===
const char* WIFI_SSID     = "kalev-bitter-70";
const char* WIFI_PASSWORD = "shutakjp";

// === WebSocket destination (receiver) ===
const char* WS_HOST = "192.168.121.188";
const char* WS_PATH = "/";
const uint16_t WS_PORT = 82;
WebSocketsClient webSocket;

// === Timing ===
const uint32_t SEND_INTERVAL_MS = 200;

// === Sensor ===
SONIC_I2C sonar;

// === State ===
float distanceCm = 0.0f;

void connectToWiFi();
void readDistance();
void updateDisplay();
void sendDistance();
void onWsEvent(WStype_t type, uint8_t* payload, size_t length);

void setup() {
  Serial.begin(115200);

  // I2C (SDA, SCL)
  Wire.begin(32, 33);

  // M5StickCPlus
  M5.begin();
  M5.Lcd.fillScreen(BLACK);
  M5.Lcd.setRotation(1);
  M5.Lcd.setCursor(0, 10);
  M5.Lcd.setTextColor(WHITE);
  M5.Lcd.setTextSize(2);

  // WiFi
  connectToWiFi();

  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWsEvent);
  webSocket.setReconnectInterval(2000);

  // Optional: Disable internal pull-up/pull-down on GPIO25 if needed
  gpio_pulldown_dis(GPIO_NUM_25);
  gpio_pullup_dis(GPIO_NUM_25);

  // Sensor
  sonar.begin();
}

void loop() {
  M5.update();

  webSocket.loop();

  readDistance();
  updateDisplay();
  sendDistance();

  delay(SEND_INTERVAL_MS);
}

void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print('.');
    delay(500);
  }
  Serial.println("\nWiFi connected");
  Serial.printf("IP address: %s\n", WiFi.localIP().toString().c_str());

  M5.Lcd.fillScreen(BLACK);
  M5.Lcd.setCursor(0, 10);
  M5.Lcd.print("IP: ");
  M5.Lcd.println(WiFi.localIP());
}

void readDistance() {
  // Library returns mm -> convert to cm
  const float rawDistance = sonar.getDistance();
  distanceCm = rawDistance / 10.0f;
}

void updateDisplay() {
  M5.Lcd.setCursor(30, 55);
  M5.Lcd.printf("WS send...\n");

  M5.Lcd.setCursor(5, 100);
  M5.Lcd.printf("Distance: ");
  M5.Lcd.fillRect(130, 100, 200, 20, BLACK);
  M5.Lcd.setCursor(130, 100);

  if (distanceCm < 250 && distanceCm > 1) {
    M5.Lcd.printf("%.2fcm", distanceCm);
    Serial.println(distanceCm);
  } else {
    M5.Lcd.printf("Too far");
    Serial.println("Too far");
    distanceCm = 250; // Mark as too far
  }
}

void sendDistance() {
  if (!webSocket.isConnected()) {
    Serial.println("WS not connected, skipping send");
    return;
  }
  uint8_t buf[sizeof(distanceCm)];
  memcpy(buf, &distanceCm, sizeof(distanceCm));
  webSocket.sendBIN(buf, sizeof(distanceCm));
  Serial.println("WS sent");
}

void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("WS connected");
      break;
    case WStype_DISCONNECTED:
      Serial.println("WS disconnected");
      break;
    case WStype_ERROR:
      Serial.println("WS error");
      break;
    default:
      break;
  }
}