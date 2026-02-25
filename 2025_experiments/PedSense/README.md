# PedSense

PedSense is a Java-based server application designed to collect sensor data from embedded devices. It receives data from an **ultrasonic distance sensor** and a **PIR sensor** and stores the readings in CSV files.

## Directory Structure
```
PedSense/
│── SensorDataServer.java  # Java server application
│── sensordata/            # Directory where CSV files are stored
│── arduino/               # Arduino code for embedded sensors
```

## Embedded Devices
- **Ultrasonic Distance Sensor** - Measures distance and transmits data to the server.
- **PIR Sensor** - Detects motion and transmits data to the server.

The corresponding Arduino code for these sensors is located in:
```
PedSense/arduino/
```

## Network Setup
Before running the system, configure your network settings:
1. **Set up a private network** (e.g., smartphone tethering for ease of use).
2. **Connect your laptop/server** to the same network.
3. **Check the IP address** of your laptop/server.
   - On Windows: Run `ipconfig`
   - On macOS/Linux: Run `ifconfig` or `ip a`

## Modify Arduino Code
Update the following lines in the Arduino code to match your network settings:
```cpp
const char* WIFI_SSID = "<YOUR_WIFI_SSID>";
const char* WIFI_PASSWORD = "<YOUR_WIFI_PASSWORD>";
const char* IP_ADDRESS = "<YOUR_IP_ADDRESS>"; // Laptop/server IP address
```
Save the changes and upload the code to the embedded device.

## Running the Java Server
1. Navigate to the **PedSense** directory.
2. Compile and run the Java application:
   ```sh
   javac SensorDataServer.java
   java ee.utartu.dps.SensorDataServer
   ```
3. The server starts two instances:
   - **Ultrasonic Sensor Server** on port `8080`
   - **PIR Sensor Server** on port `8090`

## Data Storage
Once the system is running, the Java program creates a directory called `sensordata/` inside `PedSense/`. It stores sensor readings in CSV files, separated by sensor type:
```
PedSense/sensordata/
│── UltrasonicData_YYYY_MM_DD_HH_mm.csv
│── PIRData_YYYY_MM_DD_HH_mm.csv
```
Each file contains timestamps and sensor readings.

## Troubleshooting
- Ensure both the **server** and **embedded device** are connected to the same network.
- Verify the **IP address** in the Arduino code matches your server's IP.
- Check for firewall settings that may block communication on ports `8080` and `8090`.