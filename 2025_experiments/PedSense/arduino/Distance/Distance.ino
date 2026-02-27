#include <NTPClient.h>
#include <Wire.h>
#include <Unit_Sonic.h>
#include <M5StickCPlus.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ADXL345.h>
#include <WiFiUdp.h>

// === Global Constants ===
const char* WIFI_SSID = "kalev-bitter-70";
const char* WIFI_PASSWORD = "shutakjp";
const char* IP_ADDRESS = "192.168.121.188";
const int   MIC_PIN        = 36;
const long  UTC_OFFSET     = 7200; // in seconds

// Server URL to send sensor data
String SERVER_URL = "http://" + String(IP_ADDRESS) + ":8080/upload";

// === Sensor and Utility Objects ===
SONIC_I2C sonar;
ADXL345 accel(ADXL345_ALT); // Accelerometer (optional)
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", UTC_OFFSET);

// === Global Variables ===
float distanceCm = 0;
int micValue    = 0;
int hr          = 0, minVal = 0, sec = 0;
// Accelerometer readings (optional)
int accelX = 0, accelY = 0, accelZ = 0;

// === Function Prototypes ===
void initWiFi();
void updateTime();
void readMic();
void readDistance();
void updateDisplay();
void sendSensorData();
// Optional accelerometer functions
// void initAccelerometer();
// void readAccelerometer();


// === Setup ===
void setup() {
  Serial.begin(115200);
  
  // Initialize I2C (SDA, SCL)
  Wire.begin(32, 33);
  
  // Initialize M5StickCPlus
  M5.begin();
  M5.Lcd.fillScreen(BLACK);
  M5.Lcd.setRotation(1);
  M5.Lcd.setCursor(0, 10);
  M5.Lcd.setTextColor(WHITE);
  M5.Lcd.setTextSize(2);
  
  // Initialize WiFi connection
  initWiFi();
  
  // Initialize NTP client for time synchronization
  timeClient.begin();
  
  // Set up sensor pin modes
  pinMode(MIC_PIN, INPUT);
  
  // Optional: Disable internal pull-up/pull-down on GPIO25 if needed
  gpio_pulldown_dis(GPIO_NUM_25);
  gpio_pullup_dis(GPIO_NUM_25);
  
  // Initialize sensors
  sonar.begin();
  // Uncomment to initialize the accelerometer:
  // initAccelerometer();
}


// === Main Loop ===
void loop() {
  M5.update();
  
  // Update sensor readings
  readDistance();
  readMic();
  // Uncomment to read accelerometer values:
  // readAccelerometer();
  
  // Update display with the latest sensor readings
  updateDisplay();
  
  // Uncomment to send sensor data over WiFi:
  sendSensorData();
  
  delay(200);
}


// === Function Definitions ===

// Initialize WiFi connection
void initWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("Connecting to WiFi...");
  M5.Lcd.print("Connecting...");
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    M5.Lcd.print(".");
  }
  
  Serial.println();
  Serial.print("Connected! IP: ");
  Serial.println(WiFi.localIP());
  
  M5.Lcd.fillScreen(BLACK);
  M5.Lcd.setCursor(0, 10);
  M5.Lcd.print("IP: ");
  M5.Lcd.println(WiFi.localIP());
}

// Update NTP time and extract current time values
void updateTime() {
  timeClient.update();
  hr     = timeClient.getHours();
  minVal = timeClient.getMinutes();
  sec    = timeClient.getSeconds();
  Serial.print("Time is: ");
  Serial.print(hr);
  Serial.print(":");
  Serial.print(minVal);
  Serial.print(":");
  Serial.println(sec);
}

// Read the microphone analog value
void readMic() {
  micValue = analogRead(MIC_PIN);
  Serial.print("Mic Value: ");
  Serial.println(micValue);
}

// Read the distance from the ultrasonic sensor
void readDistance() {
  // Get the raw value and convert it to centimeters
  float rawDistance = sonar.getDistance();
  distanceCm = rawDistance / 10.0;
}

// Update the M5StickCPlus display with sensor data
void updateDisplay() {
  // Display microphone value
  M5.Lcd.setCursor(30, 55);
  M5.Lcd.printf("Sending ...\n");
  M5.Lcd.fillRect(5, 120, 180, 40, BLACK);
  M5.Lcd.setCursor(5, 120);
  M5.Lcd.printf("Mic V : %04d\n", micValue);
  
  // Display distance reading
  M5.Lcd.setCursor(5, 100);
  M5.Lcd.printf("Distance: ");
  M5.Lcd.fillRect(130, 100, 200, 20, BLACK);
  M5.Lcd.setCursor(130, 100);
  if (distanceCm < 240 && distanceCm > 1) {
    M5.Lcd.printf("%.2fcm", distanceCm);
    Serial.println(distanceCm);
  } else {
    M5.Lcd.printf("Too far");
    Serial.println("Too far");
    distanceCm = 250; // Mark as too far
  }
}

// Send sensor data to the server via HTTP GET request
void sendSensorData() {
  updateTime(); // Ensure time is updated
  
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    // Build the URL with sensor data parameters
    String serverPath = SERVER_URL + "?Hrs=" + String(hr) +
                        "&minn=" + String(minVal) +
                        "&sec=" + String(sec) +
                        "&mic=" + String(micValue) +
                        "&Dis=" + String(distanceCm);
    http.begin(serverPath.c_str());
    
    int httpResponseCode = http.GET();
    if (httpResponseCode > 0) {
      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);
      String payload = http.getString();
      // Optionally, print payload:
      // Serial.println(payload);
    } else {
      Serial.print("Error code: ");
      Serial.println(httpResponseCode);
    }
    http.end();
  }
}
