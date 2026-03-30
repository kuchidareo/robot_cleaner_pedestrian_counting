#include <M5StickC.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <string.h>

//———————— WiFi Credentials ——————————
/*static const char* WIFI_SSID     = "";
static const char* WIFI_PASSWORD = "";*/

static const char* WIFI_SSID     = "kalev-bitter-70";
static const char* WIFI_PASSWORD = "shutakjp";

//———————— WebSocket Setup ——————————
static const char*   WS_HOST       = "192.168.121.188";
static const char*   WS_PATH       = "/";
static const uint16_t WS_PORT      = 84;
static const uint8_t I2C_SDA_PIN   = 32;
static const uint8_t I2C_SCL_PIN   = 33;
static const uint32_t I2C_FREQ_HZ  = 400000;
static const uint8_t MLX_I2C_ADDR  = MLX90640_I2CADDR_DEFAULT;

WebSocketsClient webSocket;
Adafruit_MLX90640 mlx;
static volatile bool wsConnected = false;

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
void onWsEvent(WStype_t type, uint8_t* payload, size_t length);
void scanI2C();

float pixels1[MLX_COLS * MLX_ROWS];  // MLX90640 resolution

void setup() {
  M5.begin();
  Serial.begin(115200);
  esp_log_level_set("wifi", ESP_LOG_NONE);
  delay(1000);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ_HZ);

  M5.Lcd.setRotation(1);  
  M5.Lcd.setTextSize(2);    
  M5.Lcd.fillScreen(BLACK);

  Serial.printf("Initializing I2C on SDA=%u SCL=%u @ %u Hz\n", I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ_HZ);
  scanI2C();
  Serial.println("Initializing MLX90640...");
  if (!mlx.begin(MLX_I2C_ADDR, &Wire)) {
    Serial.printf("Failed to find MLX90640 sensor at 0x%02X\n", MLX_I2C_ADDR);
    while (1) delay(10);
  }

  Serial.println("MLX90640 found!");
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_4_HZ);  // ~4 FPS

  connectToWiFi(); // connect to WiFi

  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWsEvent);
  webSocket.setReconnectInterval(2000);

  Serial.printf("WebSocket server started on port %d\n", WS_PORT);
}

void loop() {
  // Always service websocket frequently; handshake + ping/pong depends on this.
  webSocket.loop();

  // Don't do slow sensor reads or send data until the websocket is actually connected.
  if (!wsConnected) {
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

  webSocket.sendBIN(buf, PACKET_BYTES);
  delay(SEND_INTERVAL_MS);
}

void scanI2C() {
  bool foundDevice = false;
  Serial.println("Scanning I2C bus...");
  for (uint8_t addr = 1; addr < 127; ++addr) {
    Wire.beginTransmission(addr);
    const uint8_t err = Wire.endTransmission();
    if (err == 0) {
      foundDevice = true;
      Serial.printf("I2C device found at 0x%02X\n", addr);
    }
  }
  if (!foundDevice) {
    Serial.println("No I2C devices found");
  }
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

void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
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
      // payload content is library-dependent, but printing length helps.
      wsConnected = false;
      Serial.printf("[WS] error (len=%u)\n", (unsigned)length);
      break;

    default:
      break;
  }
}
