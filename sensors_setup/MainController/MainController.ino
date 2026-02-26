#include <M5StickCPlus.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include "M5_STHS34PF80.h"
#include <Unit_Sonic.h>

// ——— Configuration ————————————————————————————
/*static const char*   WIFI_SSID     = "";
static const char*   WIFI_PASSWORD = "";*/

static const char*   WIFI_SSID     = "kalev-bitter-70";
static const char*   WIFI_PASSWORD = "shutakjp";

static const uint8_t WS_PORT       = 81;
static const uint8_t I2C_MUX_ADDR  = 0x70;  // TCA9548A address

static const uint8_t MLX1_BUS      = 4;   // first camera
static const uint8_t MLX2_BUS      = 0;   // second camera
static const uint8_t SONAR_BUS     = 5;   // I2C mux channel for Unit_Sonic (adjust if wired differently)

static const uint8_t PIR_PIN       = 32;  // Digital PIR input pin (set to your wiring)

static const uint8_t MLX_I2C_ADDR  = 0x33;
static const uint8_t MLX_COLS      = 32;
static const uint8_t MLX_ROWS      = 24;
static const float   FRAME_DELAY   = 100;   // ms between frames

int16_t motionVal        = 0;
int16_t presenceVal      = 0;
int16_t pirValue         = 0;   // Digital PIR (0/1)
float   ambientTemp      = 0.0;
float   distanceCm       = 0.0;
// IMU values to transmit (converted units)
float gyroX_dps = 0.0;
float gyroY_dps = 0.0;
float gyroZ_dps = 0.0;
float accelX_mps2 = 0.0;
float accelY_mps2 = 0.0;
float accelZ_mps2 = 0.0;

// ——— Globals ————————————————————————————————————————
WebSocketsServer  webSocket(WS_PORT);

// two separate camera objects and two buffers:
Adafruit_MLX90640 mlx1;
Adafruit_MLX90640 mlx2;
float pixels1[MLX_COLS * MLX_ROWS];
float pixels2[MLX_COLS * MLX_ROWS];

// --- Compact binary packet (no CSV/JSON on-device) ---------------------------
// Packet layout (little-endian):
//  Header: uint16 cols, uint16 rows
//  Meta:   int16 motion, int16 presence, int16 pir,
//          float ambient, float distance_cm,
//          float gyroX_dps, float gyroY_dps, float gyroZ_dps,
//          float accelX_mps2, float accelY_mps2, float accelZ_mps2
//  Data:   float pixels1[cols*rows], float pixels2[cols*rows]
struct __attribute__((packed)) PacketHeader {
  uint16_t cols;
  uint16_t rows;
};

// Fixed packet sizing (compile-time)
static constexpr size_t N_PIXELS = (size_t)MLX_COLS * (size_t)MLX_ROWS;
static constexpr size_t BYTES_HEADER = sizeof(PacketHeader);
static constexpr size_t BYTES_META   = sizeof(int16_t) * 3 + sizeof(float) * (2 + 6); // motion,presence,pir + (ambient,distance) + 6 IMU floats
static constexpr size_t BYTES_DATA   = (N_PIXELS * sizeof(float)) * 2;                // two cameras
static constexpr size_t PACKET_BYTES = BYTES_HEADER + BYTES_META + BYTES_DATA;

M5_STHS34PF80           tmos;
SONIC_I2C sonar;

// ——— Function Prototypes ————————————————————————
void connectToWiFi();
void initDisplay();
void initThermalCameras();
void selectI2CBus(uint8_t bus);
void initOtherSensors();
void handleWebSocketEvent(uint8_t client, WStype_t type, uint8_t* payload, size_t length);
void broadcastThermalFrames();
void readPIR();
void readIMU();
void readDistance();

// ——— Setup ——————————————————————————————————————
void setup() {
  M5.begin();
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);

  Wire.begin(/* SDA */ 32, /* SCL */ 33, 400000);

  connectToWiFi();
  initDisplay();
  
  initThermalCameras();
  initOtherSensors();
  scanI2COnMux();

  webSocket.begin();
  webSocket.onEvent(handleWebSocketEvent);
}

// ——— Main Loop ————————————————————————————————————
void loop() {
  webSocket.loop();
  broadcastThermalFrames();
  readPIR();
  readDistance();
  readIMU();
  delay(FRAME_DELAY);
}

// ——— Implementations ———————————————————————————

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
  // Camera 1
  selectI2CBus(MLX1_BUS);
  if (!mlx1.begin(MLX_I2C_ADDR, &Wire)) {
    Serial.println("Error: MLX90640 #1 not detected!");
    while (1) delay(10);
  }
  mlx1.setMode(MLX90640_CHESS);
  mlx1.setResolution(MLX90640_ADC_18BIT);
  mlx1.setRefreshRate(MLX90640_8_HZ);

  // Camera 2
  selectI2CBus(MLX2_BUS);
  if (!mlx2.begin(MLX_I2C_ADDR, &Wire)) {
    Serial.println("Error: MLX90640 #2 not detected!");
    while (1) delay(10);
  }
  mlx2.setMode(MLX90640_CHESS);
  mlx2.setResolution(MLX90640_ADC_18BIT);
  mlx2.setRefreshRate(MLX90640_8_HZ);
}

void initOtherSensors() {

  M5.IMU.Init();

  // PIR/Temp on bus 3
  selectI2CBus(3);
  tmos.begin();
  tmos.setGainMode(STHS34PF80_GAIN_DEFAULT_MODE);
  tmos.setMotionThreshold(0xFF);
  tmos.setPresenceThreshold(0xC8);
  tmos.setMotionHysteresis(0x32);
  tmos.setPresenceHysteresis(0x32);

  // Ultrasonic (Unit_Sonic) on its mux channel
  selectI2CBus(SONAR_BUS);
  sonar.begin();

}

// Selects which channel on the TCA9548A I2C multiplexer to use
void selectI2CBus(uint8_t bus) {
  Wire.beginTransmission(I2C_MUX_ADDR);
  Wire.write(1 << bus);
  Wire.endTransmission();
}

// WebSocket event handler (we only broadcast, so this is empty)
void handleWebSocketEvent(uint8_t client, WStype_t type, uint8_t* payload, size_t length) {
  // No incoming messages handled
}

void readPIR() {
  // Digital PIR (0/1)
  pirValue = (digitalRead(PIR_PIN) == HIGH) ? 1 : 0;

  // STHS34PF80 (presence/motion/ambient) on mux bus 3
  selectI2CBus(3);
  tmos.getPresenceValue(&presenceVal);
  tmos.getMotionValue(&motionVal);
  tmos.getTemperatureData(&ambientTemp);
}

void readDistance() {
  // Unit_Sonic returns distance in mm (raw). Convert to cm.
  selectI2CBus(SONAR_BUS);
  float rawDistance = sonar.getDistance();
  distanceCm = rawDistance / 10.0f;

  // Optional sanity clamp consistent with the reference sketch display logic
  // if (!(distanceCm < 240.0f && distanceCm > 1.0f)) {
  //   distanceCm = 250.0f; // mark as too far / invalid
  // }
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

// Reads one frame from the MLX90640 and broadcasts as binary packet
void broadcastThermalFrames() {
  // Read first camera
  selectI2CBus(MLX1_BUS);
  if (mlx1.getFrame(pixels1) != 0) {
    Serial.println("Error: failed to read MLX90640 #1");
    return;
  }
  // Read second camera
  selectI2CBus(MLX2_BUS);
  if (mlx2.getFrame(pixels2) != 0) {
    Serial.println("Error: failed to read MLX90640 #2");
    return;
  }

  // Build a compact binary packet (no CSV/JSON here)
  PacketHeader hdr;
  hdr.cols     = MLX_COLS;
  hdr.rows     = MLX_ROWS;

  const int16_t motion   = motionVal;
  const int16_t presence = presenceVal;
  const int16_t pir      = pirValue;
  const float   ambient  = ambientTemp;
  const float   distance = distanceCm;

  const float gX = gyroX_dps;
  const float gY = gyroY_dps;
  const float gZ = gyroZ_dps;
  const float aX = accelX_mps2;
  const float aY = accelY_mps2;
  const float aZ = accelZ_mps2;

  // Allocate a buffer on the stack (fixed size)
  uint8_t buf[PACKET_BYTES];
  size_t off = 0;

  memcpy(buf + off, &hdr, sizeof(hdr));
  off += sizeof(hdr);

  memcpy(buf + off, &motion, sizeof(motion));
  off += sizeof(motion);

  memcpy(buf + off, &presence, sizeof(presence));
  off += sizeof(presence);

  memcpy(buf + off, &pir, sizeof(pir));
  off += sizeof(pir);

  memcpy(buf + off, &ambient, sizeof(ambient));
  off += sizeof(ambient);

  memcpy(buf + off, &distance, sizeof(distance));
  off += sizeof(distance);

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

  memcpy(buf + off, pixels2, N_PIXELS * sizeof(float));
  off += N_PIXELS * sizeof(float);

  // Broadcast as binary
  webSocket.broadcastBIN(buf, PACKET_BYTES);
}


// DEBUG
void scanI2COnMux() {
  Serial.println("=== I2C scan on each TCA9548A channel ===");
  for (uint8_t ch = 0; ch < 8; ch++) {
    selectI2CBus(ch);
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
