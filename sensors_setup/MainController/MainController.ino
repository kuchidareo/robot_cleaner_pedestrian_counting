#include <M5StickCPlus.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <string.h>

static const char* WIFI_SSID = "RoombaSense";
static const char* WIFI_PASSWORD = "Asdf1234";
static const uint16_t WS_PORT = 81;
static const uint32_t SEND_INTERVAL_MS = 0;

static const uint16_t MLX_COLS = 32;
static const uint16_t MLX_ROWS = 24;
static constexpr size_t N_PIXELS = (size_t)MLX_COLS * (size_t)MLX_ROWS;
static constexpr size_t IMU_VALUE_COUNT = 6;
static constexpr size_t PACKET_BYTES =
    sizeof(uint16_t) * 2 + IMU_VALUE_COUNT * sizeof(float) + N_PIXELS * sizeof(float);

WebSocketsServer webSocket(WS_PORT);
Adafruit_MLX90640 mlx;
static volatile uint8_t wsClientCount = 0;
float pixels[MLX_COLS * MLX_ROWS];

struct __attribute__((packed)) PacketHeader {
  uint16_t cols;
  uint16_t rows;
};

void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nWiFi connected");
  Serial.printf("IP address: %s\n", WiFi.localIP().toString().c_str());

  M5.Lcd.fillScreen(BLACK);
  M5.Lcd.setTextSize(2);
  M5.Lcd.setCursor(0, 20);
  M5.Lcd.println("IP:");
  M5.Lcd.println(WiFi.localIP());
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

void setup() {
  M5.begin();
  Serial.begin(115200);
  Wire.begin(0, 26);  // Direct pins: SDA=0, SCL=26
  M5.IMU.Init();

  M5.Lcd.setRotation(3);
  M5.Lcd.setTextSize(2);
  M5.Lcd.fillScreen(BLACK);

  Serial.println("Initializing MLX90640...");
  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire)) {
    Serial.println("Failed to find MLX90640 sensor!");
    while (1) {
      delay(10);
    }
  }

  Serial.println("MLX90640 found!");
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_8_HZ);
  Wire.setClock(1000000);  // Required to read MLX90640 reliably at 8 Hz.

  connectToWiFi();
  webSocket.begin();
  webSocket.onEvent(onWsEvent);
  Serial.printf("WebSocket server listening on port %u\n", WS_PORT);
}

void loop() {
  webSocket.loop();

  if (wsClientCount == 0) {
    delay(10);
    return;
  }

  const int frameStatus = mlx.getFrame(pixels);
  if (frameStatus != 0) {
    Serial.printf("Failed to get frame: %d\n", frameStatus);
    delay(10);
    return;
  }

  float gx, gy, gz;
  float ax, ay, az;
  M5.IMU.getGyroData(&gx, &gy, &gz);
  M5.IMU.getAccelData(&ax, &ay, &az);

  const float imuValues[IMU_VALUE_COUNT] = {
      gx / 131.0f,
      gy / 131.0f,
      gz / 131.0f,
      ax * 9.81f,
      ay * 9.81f,
      az * 9.81f,
  };

  const PacketHeader header = {MLX_COLS, MLX_ROWS};
  uint8_t buffer[PACKET_BYTES];
  size_t offset = 0;

  memcpy(buffer + offset, &header, sizeof(header));
  offset += sizeof(header);
  memcpy(buffer + offset, imuValues, sizeof(imuValues));
  offset += sizeof(imuValues);
  memcpy(buffer + offset, pixels, sizeof(pixels));
  offset += sizeof(pixels);

  if (offset != PACKET_BYTES) {
    Serial.println("Packet size mismatch");
    return;
  }

  webSocket.broadcastBIN(buffer, PACKET_BYTES);
  delay(SEND_INTERVAL_MS);
}
