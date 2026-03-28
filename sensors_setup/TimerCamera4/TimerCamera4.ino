#include <string.h>
#include <M5TimerCAM.h>
#include <WiFi.h>
#include <WebSocketsClient.h>

// Wi-Fi credentials
static const char* WIFI_SSID     = "kalev-bitter-70";
static const char* WIFI_PASSWORD = "shutakjp";

// WebSocket server settings
static const char* WS_HOST       = "192.168.121.188";
static const char* WS_PATH       = "/";
static const uint16_t WS_PORT    = 90;

static const uint32_t SEND_INTERVAL_MS = 333;

WebSocketsClient webSocket;
static volatile bool wsConnected = false;

void connectToWiFi();
void onWsEvent(WStype_t type, uint8_t* payload, size_t length);
bool captureAndSendFrame();

void setup() {
  TimerCAM.begin();
  delay(1000);

  Serial.println("Initializing TimerCAM...");
  if (!TimerCAM.Camera.begin()) {
    Serial.println("Camera init failed");
    while (true) {
      delay(100);
    }
  }

  TimerCAM.Camera.sensor->set_pixformat(TimerCAM.Camera.sensor, PIXFORMAT_JPEG);
  TimerCAM.Camera.sensor->set_framesize(TimerCAM.Camera.sensor, FRAMESIZE_VGA);
  TimerCAM.Camera.sensor->set_vflip(TimerCAM.Camera.sensor, 1);
  TimerCAM.Camera.sensor->set_hmirror(TimerCAM.Camera.sensor, 0);
  TimerCAM.Camera.sensor->set_quality(TimerCAM.Camera.sensor, 12);

  connectToWiFi();

  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWsEvent);
  webSocket.setReconnectInterval(2000);

  Serial.printf("WebSocket client configured for ws://%s:%u%s\n", WS_HOST, WS_PORT, WS_PATH);
}

void loop() {
  webSocket.loop();

  if (!wsConnected) {
    delay(10);
    return;
  }

  captureAndSendFrame();
  delay(SEND_INTERVAL_MS);
}

void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }

  Serial.println();
  Serial.println("WiFi connected");
  Serial.printf("IP address: %s\n", WiFi.localIP().toString().c_str());
}

void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
  (void)payload;

  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      Serial.printf("[WS] connected to %s:%u%s\n", WS_HOST, WS_PORT, WS_PATH);
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      Serial.println("[WS] disconnected");
      break;

    case WStype_ERROR:
      wsConnected = false;
      Serial.printf("[WS] error (len=%u)\n", (unsigned)length);
      break;

    default:
      break;
  }
}

bool captureAndSendFrame() {
  if (!TimerCAM.Camera.get()) {
    Serial.println("Capture failed");
    return false;
  }

  TimerCAM.Power.setLed(255);
  webSocket.sendBIN(TimerCAM.Camera.fb->buf, TimerCAM.Camera.fb->len);
  Serial.printf("Sent JPEG frame: %u bytes\n", (unsigned)TimerCAM.Camera.fb->len);
  TimerCAM.Camera.free();
  TimerCAM.Power.setLed(0);
  return true;
}
