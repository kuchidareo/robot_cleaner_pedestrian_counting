#include <M5StickCPlus.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include "M5_STHS34PF80.h"

// ——— Configuration ————————————————————————————
/*static const char*   WIFI_SSID     = "";
static const char*   WIFI_PASSWORD = "";*/

// === WebSocket destination (receiver) ===
static const char*   WS_HOST       = "192.168.121.188";
static const char*   WS_PATH       = "/";
static const uint16_t WS_PORT      = 81;

static const char*   WIFI_SSID     = "kalev-bitter-70";
static const char*   WIFI_PASSWORD = "shutakjp";

static const uint8_t I2C_MUX_ADDR  = 0x70;  // TCA9548A address

static const uint8_t MLX_I2C_ADDR  = 0x33;
static const uint8_t MLX1_BUS      = 0;   // first camera

static const uint8_t PIR_I2C_ADDR  = 0x5A;
static const uint8_t PIR_BUS       = 3;   // I2C mux channel for PIR

static const uint8_t MLX_COLS      = 32;
static const uint8_t MLX_ROWS      = 24;
static const float   FRAME_DELAY   = 100;   // ms between frames

int16_t motionVal        = 0;
int16_t presenceVal      = 0;
float   ambientTemp      = 0.0;

// IMU values to transmit (converted units)
float gyroX_dps = 0.0;
float gyroY_dps = 0.0;
float gyroZ_dps = 0.0;
float accelX_mps2 = 0.0;
float accelY_mps2 = 0.0;
float accelZ_mps2 = 0.0;

// ——— Globals ————————————————————————————————————————
WebSocketsClient  webSocket;

// one thermal camera object and one buffer:
Adafruit_MLX90640 mlx1;
M5_STHS34PF80 tmos;
float pixels1[MLX_COLS * MLX_ROWS];

// --- Compact binary packet (no CSV/JSON on-device) ---------------------------
// Packet layout (little-endian):
//  Header: uint16 cols, uint16 rows
//  Meta:   int16 motion, int16 presence,
//          float ambient,
//          float gyroX_dps, float gyroY_dps, float gyroZ_dps,
//          float accelX_mps2, float accelY_mps2, float accelZ_mps2
//  Data:   float pixels1[cols*rows]
struct __attribute__((packed)) PacketHeader {
  uint16_t cols;
  uint16_t rows;
};

// NOTE: Keep this in sync with what `sendThermalPacket()` actually packs.
// Packed meta fields (current):
//   int16 motion, int16 presence,
//   float ambient,
//   float gyroX_dps, gyroY_dps, gyroZ_dps,
//   float accelX_mps2, accelY_mps2, accelZ_mps2
static constexpr size_t N_PIXELS = (size_t)MLX_COLS * (size_t)MLX_ROWS;
static constexpr size_t BYTES_HEADER = sizeof(PacketHeader);
static constexpr size_t BYTES_META   = sizeof(int16_t) * 2 + sizeof(float) * 7; // 2 int16 + 7 floats
static constexpr size_t BYTES_DATA   = (N_PIXELS * sizeof(float));               // one camera
static constexpr size_t PACKET_BYTES = BYTES_HEADER + BYTES_META + BYTES_DATA;

// Sanity check: header(4) + meta(32) + data(3072) = 3108 bytes for 32x24 floats
static_assert(PACKET_BYTES == (sizeof(PacketHeader) + (sizeof(int16_t) * 2) + (sizeof(float) * 7) + (N_PIXELS * sizeof(float))),
              "PACKET_BYTES mismatch: update BYTES_META/PACKET_BYTES to match sendThermalPacket()");



// ——— Function Prototypes ————————————————————————
void connectToWiFi();
void initDisplay();
void initThermalCameras();
void selectMux(uint8_t ch);
void scanI2COnMux();
bool readThermalFrames();
void sendThermalPacket();
void readPIR();
void readIMU();

// ——— Setup ——————————————————————————————————————
void setup() {
  M5.begin();
  Serial.begin(115200);

  Wire.begin(/* SDA */ 32, /* SCL */ 33, 400000);

  connectToWiFi();
  initDisplay();
  scanI2COnMux();
  
  initThermalCameras();
  initOtherSensors();


  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(handleWebSocketEvent);
  webSocket.setReconnectInterval(2000);
  Serial.printf("[WS] connecting to ws://%s:%u%s\n", WS_HOST, WS_PORT, WS_PATH);
}

// ——— Main Loop ————————————————————————————————————
void loop() {
  webSocket.loop();

  readPIR();
  readIMU();

  if (readThermalFrames()) {
    sendThermalPacket();
  }

  delay(FRAME_DELAY);
}

void handleWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("[WS] connected");
      break;
    case WStype_DISCONNECTED:
      Serial.println("[WS] disconnected");
      break;
    case WStype_ERROR:
      Serial.println("[WS] error");
      break;
    default:
      break;
  }
}
// ——— Implementations ———————————————————————————
// Selects which channel on the TCA9548A I2C multiplexer to use
void selectMux(uint8_t ch) {
  Wire.beginTransmission(I2C_MUX_ADDR);
  Wire.write(1 << ch);
  Wire.endTransmission();
}

// Connects to WiFi and prints the IP on Serial
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
}

// Sets up the LCD to show IP address
void initDisplay() {
  M5.Lcd.setRotation(3);
  M5.Lcd.setTextSize(2);
  M5.Lcd.setCursor(0, 20);
  M5.Lcd.println("IP:");
  M5.Lcd.println(WiFi.localIP());
}

// Initializes the MLX90640 sensor over the I2C multiplexer
void initThermalCameras() {
  selectMux(MLX1_BUS);
  if (!mlx1.begin(MLX_I2C_ADDR, &Wire)) {
    Serial.println("Error: MLX90640 #1 not detected!");
    while (1) delay(10);
  }
  mlx1.setMode(MLX90640_CHESS);
  mlx1.setResolution(MLX90640_ADC_18BIT);
  mlx1.setRefreshRate(MLX90640_8_HZ);
}

void initOtherSensors() {
  M5.IMU.Init();

  // PIR/Temp
  selectMux(PIR_BUS);
  tmos.begin(&Wire, PIR_I2C_ADDR);
  tmos.setGainMode(STHS34PF80_GAIN_DEFAULT_MODE);
  tmos.setMotionThreshold(0xFF);
  tmos.setPresenceThreshold(0xC8);
  tmos.setMotionHysteresis(0x32);
  tmos.setPresenceHysteresis(0x32);
}

void readPIR() {
  // STHS34PF80 (presence/motion/ambient) on mux bus 3
  selectMux(PIR_BUS);
  tmos.getPresenceValue(&presenceVal);
  tmos.getMotionValue(&motionVal);
  tmos.getTemperatureData(&ambientTemp);
}

void readIMU(){
  float gx, gy, gz;
  float ax, ay, az;

  // Get gyroscope and accelerometer data
  M5.IMU.getGyroData(&gx, &gy, &gz);
  M5.IMU.getAccelData(&ax, &ay, &az);

  // Convert gyroscope data to deg/s (library units depend on IMU configuration)
  gyroX_dps = gx / 131.0;
  gyroY_dps = gy / 131.0;
  gyroZ_dps = gz / 131.0;

  // Convert accelerometer data to m/s²
  accelX_mps2 = ax * 9.81;
  accelY_mps2 = ay * 9.81;
  accelZ_mps2 = az * 9.81;
}

// Reads one frame from the MLX90640 into the global pixels buffer.
// Returns true if the frame was read successfully.
bool readThermalFrames() {
  selectMux(MLX1_BUS);
  if (mlx1.getFrame(pixels1) != 0) {
    Serial.println("Error: failed to read MLX90640 #1");
    return false;
  }
  return true;
}

// Builds and broadcasts the compact binary packet using the latest sensor values.
void sendThermalPacket() {
  PacketHeader hdr;
  hdr.cols = MLX_COLS;
  hdr.rows = MLX_ROWS;

  const int16_t motion   = motionVal;
  const int16_t presence = presenceVal;
  const float   ambient  = ambientTemp;

  const float gX = gyroX_dps;
  const float gY = gyroY_dps;
  const float gZ = gyroZ_dps;
  const float aX = accelX_mps2;
  const float aY = accelY_mps2;
  const float aZ = accelZ_mps2;

  // Allocate a buffer on the stack (fixed size)
  uint8_t buf[PACKET_BYTES];
  size_t off = 0;

  // Guard against accidental size mismatches (would cause stack smashing)
  if (PACKET_BYTES > sizeof(buf)) {
    Serial.printf("[ERR] PACKET_BYTES(%u) > buf(%u)\n", (unsigned)PACKET_BYTES, (unsigned)sizeof(buf));
    return;
  }

  memcpy(buf + off, &hdr, sizeof(hdr));
  off += sizeof(hdr);

  memcpy(buf + off, &motion, sizeof(motion));
  off += sizeof(motion);

  memcpy(buf + off, &presence, sizeof(presence));
  off += sizeof(presence);

  memcpy(buf + off, &ambient, sizeof(ambient));
  off += sizeof(ambient);

  memcpy(buf + off, &gX, sizeof(gX));
  off += sizeof(gX);
  memcpy(buf + off, &gY, sizeof(gY));
  off += sizeof(gY);
  memcpy(buf + off, &gZ, sizeof(gZ));
  off += sizeof(gZ);

  memcpy(buf + off, &aX, sizeof(aX));
  off += sizeof(aX);
  memcpy(buf + off, &aY, sizeof(aY));
  off += sizeof(aY);
  memcpy(buf + off, &aZ, sizeof(aZ));
  off += sizeof(aZ);

  memcpy(buf + off, pixels1, N_PIXELS * sizeof(float));
  off += N_PIXELS * sizeof(float);

  // Final consistency check
  if (off != PACKET_BYTES) {
    Serial.printf("[ERR] Packed size mismatch: off=%u PACKET_BYTES=%u\n", (unsigned)off, (unsigned)PACKET_BYTES);
    return;
  }

  // Broadcast as binary
  webSocket.sendBIN(buf, PACKET_BYTES);
}

// DEBUG
void scanI2COnMux() {
  Serial.println("=== I2C scan on each TCA9548A channel ===");
  for (uint8_t ch = 0; ch < 8; ch++) {
    selectMux(ch);
    delay(10);

    Serial.printf("CH %u: ", ch);
    bool foundAny = false;

    for (uint8_t addr = 1; addr < 127; addr++) {
      Wire.beginTransmission(addr);
      if (Wire.endTransmission() == 0) {
        Serial.printf("0x%02X ", addr);
        foundAny = true;
      }
    }
    if (!foundAny) Serial.print("(none)");
    Serial.println();
  }
  Serial.println("========================================");
}