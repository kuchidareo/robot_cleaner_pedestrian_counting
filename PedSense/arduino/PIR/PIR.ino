#include <M5Atom.h>
#include <HTTPClient.h>
#include <WiFiUdp.h>
#include <NTPClient.h>

// ----- WiFi & Server Configuration -----
const char* WIFI_SSID = "<YOUR_WIFI_SSID>";
const char* WIFI_PASSWORD = "<YOUR_WIFI_PASSWORD>";
const char* IP_ADDRESS = "<YOUR_IP_ADDRESS>";

String SERVER_URL = "http://" + String(IP_ADDRESS) + ":8090/upload";

// ----- Time Configuration -----
const long UTC_OFFSET_SECONDS = 7200; // UTC offset in seconds

// ----- PIR Sensor Configuration -----
const int PIR_PIN = 32;  // PIR sensor connected to digital pin 32

// ----- Global Variables -----
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", UTC_OFFSET_SECONDS);
int hr   = 0;
int minn = 0;
int sec  = 0;
int pirValue = 0;

// ----- Function Prototypes -----
void initWiFi();
void updateTime();
void readPIR();
void sendData();


// ----- Setup Function -----
void setup() {
  Serial.begin(115200);
  M5.begin();  // Initialize M5Atom
  Serial.println("PIR Sensor Example");
  
  // Set PIR sensor pin as input
  pinMode(PIR_PIN, INPUT);

  // Initialize WiFi and NTP
  initWiFi();
  timeClient.begin();
  
  // Optional delay for connection stabilization
  delay(5000);
}


// ----- Main Loop -----
void loop() {
  readPIR();
  sendData();
  delay(200);
}


// ----- Function Definitions -----

// Connects to the specified WiFi network
void initWiFi() {
  Serial.println("Connecting to WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while(WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected! IP address: ");
  Serial.println(WiFi.localIP());
}

// Updates the NTP client and extracts the current time
void updateTime() {
  timeClient.update();
  hr   = timeClient.getHours();
  minn = timeClient.getMinutes();
  sec  = timeClient.getSeconds();
  
  Serial.print("Time: ");
  Serial.print(hr);
  Serial.print(":");
  Serial.print(minn);
  Serial.print(":");
  Serial.println(sec);
}

// Reads the PIR sensor value and sets the global variable accordingly
void readPIR() {
  // If digital read returns HIGH (1), sensor is triggered
  if (digitalRead(PIR_PIN) == HIGH) {
    Serial.println("PIR: Sensing (1)");
    pirValue = 1;
  } else {
    Serial.println("PIR: Not Sensed (0)");
    pirValue = 0;
  }
}

// Sends sensor data to the remote server via HTTP GET request
void sendData() {
  updateTime(); // Ensure we have the latest time
  
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    // Build URL with query parameters
    String url = SERVER_URL + "?Hrs=" + String(hr) +
                 "&minn=" + String(minn) +
                 "&sec=" + String(sec) +
                 "&PirVal=" + String(pirValue);
                 
    Serial.println("Sending data to: " + url);
    http.begin(url);
    int httpResponseCode = http.GET();
    
    if (httpResponseCode > 0) {
      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);
      String payload = http.getString();
      // Optionally, print the server response:
      // Serial.println(payload);
    } else {
      Serial.print("HTTP Error code: ");
      Serial.println(httpResponseCode);
    }
    http.end(); // Free resources
  } else {
    Serial.println("WiFi not connected.");
  }
}