#include <M5StickC.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <string.h>

//———————— WiFi Credentials ——————————
/*static const char* WIFI_SSID     = "";
static const char* WIFI_PASSWORD = "";*/

static const char* WIFI_SSID     = "kalev-bitter-70";
static const char* WIFI_PASSWORD = "shutakjp";

//———————— WebSocket Setup ——————————
static const uint16_t WS_PORT = 86;

WebSocketsServer webSocket(WS_PORT);
Adafruit_MLX90640 mlx;
static volatile uint8_t wsClientCount = 0;

const uint32_t SEND_INTERVAL_MS = 200;

// --- Compact binary packet (single thermal frame) ---------------------------
// Packet layout (little-endian):
//  Header: uint16 cols, uint16 rows
//  Data:   float pixels[cols*rows]
struct __attribute__((packed)) PacketHeader {
  uint16_t cols;
  uint16_t rows;
};

static const uint16_t MLX_COLS = 32;
static const uint16_t MLX_ROWS = 24;

static constexpr size_t N_PIXELS     = (size_t)MLX_COLS * (size_t)MLX_ROWS;
static constexpr size_t BYTES_HEADER = sizeof(PacketHeader);
static constexpr size_t BYTES_DATA   = N_PIXELS * sizeof(float);
static constexpr size_t PACKET_BYTES = BYTES_HEADER + BYTES_DATA;

//———————— Function Prototypes ——————————
void connectToWiFi();
void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length);

float pixels1[MLX_COLS * MLX_ROWS];  // MLX90640 resolution

void setup() {
  M5.begin();
  Wire.begin(0, 26);  // SDA = GPIO0, SCL = GPIO26 for Thermal Hat
  Serial.begin(115200);
  esp_log_level_set("wifi", ESP_LOG_NONE);
  delay(1000);

  M5.Lcd.setRotation(1);  
  M5.Lcd.setTextSize(2);    
  M5.Lcd.fillScreen(BLACK);

  Serial.println("Initializing MLX90640...");
  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire)) {
    Serial.println("Failed to find MLX90640 sensor!");
    while (1) delay(10);
  }

  Serial.println("MLX90640 found!");
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_4_HZ);  // ~4 FPS

  connectToWiFi(); // connect to WiFi

  webSocket.begin();
  webSocket.onEvent(onWsEvent);

  Serial.printf("WebSocket server listening on port %d\n", WS_PORT);
}

void loop() {
  // Always service websocket frequently.
  webSocket.loop();

  // Don't do slow sensor reads or send data until at least one websocket client is connected.
  if (wsClientCount == 0) {
    delay(10);
    return;
  }

  if (mlx.getFrame(pixels1) != 0) {
    Serial.println("Failed to get frame");
    delay(10);
    return;
  }

  // Build a compact binary packet (no CSV/JSON here)
  PacketHeader hdr;
  hdr.cols = MLX_COLS;
  hdr.rows = MLX_ROWS;

  uint8_t buf[PACKET_BYTES];
  size_t off = 0;

  memcpy(buf + off, &hdr, sizeof(hdr));
  off += sizeof(hdr);

  memcpy(buf + off, pixels1, N_PIXELS * sizeof(float));
  off += N_PIXELS * sizeof(float);

  // Sanity check: if this ever fails, we'd risk buffer issues.
  if (off != PACKET_BYTES) {
    Serial.printf("[ERR] Packed size mismatch: off=%u PACKET_BYTES=%u\n", (unsigned)off, (unsigned)PACKET_BYTES);
    delay(10);
    return;
  }

  webSocket.broadcastBIN(buf, PACKET_BYTES);
  delay(SEND_INTERVAL_MS);
}

void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nWiFi connected");
  delay(500);  // Allow time for M5.Lcd to initialize
  IPAddress ip = WiFi.localIP();
  Serial.printf("IP address: %s\n", ip.toString().c_str());
}

void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsClientCount++;
      Serial.printf("[WS] client #%u connected (clients=%u)\n", num, wsClientCount);
      break;

    case WStype_DISCONNECTED:
      if (wsClientCount > 0) {
        wsClientCount--;
      }
      Serial.printf("[WS] client #%u disconnected (clients=%u)\n", num, wsClientCount);
      break;

    case WStype_ERROR:
      Serial.printf("[WS] error from client #%u (len=%u)\n", num, (unsigned)length);
      break;

    default:
      break;
  }
}
