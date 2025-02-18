package ee.utartu.dps;

import fi.iki.elonen.NanoHTTPD;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.DateFormat;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

/**
 * Main class that starts two server instances:
 *  - UltrasonicSensorServer on port 8080
 *  - PirSensorServer on port 8090
 */
public class SensorDataServer {

    public static void main(String[] args) {
        try {
            // Start server for ultrasonic and mic sensor data (port 8080);
            UltrasonicSensorServer ultrasonicServer = new UltrasonicSensorServer(8080);
            // Start server for PIR sensor data (port 8090);
            PirSensorServer pirServer = new PirSensorServer(8090);
            System.out.println("Servers running:");
            System.out.println("Ultrasonic/Mic sensor server on port 8080 (endpoint: /upload)");
            System.out.println("PIR sensor server on port 8090 (endpoint: /upload)");
        } catch (IOException e) {
            System.err.println("Error starting server(s): " + e);
        }
    }
}

/**
 * Server for handling ultrasonic/microphone sensor data.
 * Expected GET parameters: Hrs, minn, sec, mic, Dis
 */
class UltrasonicSensorServer extends NanoHTTPD {
    private static final DateFormat dateFormat = new SimpleDateFormat("yyyy_MM_dd_HH_mm");
    private static final String ENDPOINT = "/upload";

    public UltrasonicSensorServer(int port) throws IOException {
        super(port);
        start(SOCKET_READ_TIMEOUT, false);
        System.out.println("Ultrasonic sensor server running on port " + port);
    }

    @Override
    public Response serve(IHTTPSession session) {
        // Only process GET requests to "/upload"
        if (Method.GET.equals(session.getMethod()) && ENDPOINT.equals(session.getUri())) {
            try {
                // Parse URL parameters
                Map<String, String> files = new HashMap<>();
                session.parseBody(files);
                Map<String, String> params = session.getParms();

                // Get parameters from the request
                String hrs = params.get("Hrs");
                String minn = params.get("minn");
                String sec = params.get("sec");
                String mic = params.get("mic");
                String dis = params.get("Dis");

                // Create a timestamp for logging and file naming
                String currentTimestamp = dateFormat.format(new Date());
                String logMsg = String.format("Ultrasonic Data (%s): %s:%s:%s | Mic: %s | Distance: %s",
                        currentTimestamp, hrs, minn, sec, mic, dis);
                System.out.println(logMsg);

                String directoryPath = new File(".").getCanonicalPath() + File.separator + "sensordata";
                File directory = new File(directoryPath);
                if (!directory.exists()) {
                    directory.mkdirs();
                }
                String fileName = "UltrasonicData_" + currentTimestamp + ".csv";
                File file = new File(directory, fileName);

                // Append data to the CSV file
                try (BufferedWriter out = new BufferedWriter(new FileWriter(file, true))) {
                    // CSV columns: Hrs, minn, sec, mic, Dis
                    out.write(hrs + "," + minn + "," + sec + "," + mic + "," + dis);
                    out.newLine();
                }
            } catch (Exception e) {
                System.out.println("Error in UltrasonicSensorServer: " + e);
                return newFixedLengthResponse("Error receiving ultrasonic sensor data");
            }
        }
        return newFixedLengthResponse("");
    }
}

/**
 * Server for handling PIR sensor data.
 * Expected GET parameters: Hrs, minn, sec, PirVal
 */
class PirSensorServer extends NanoHTTPD {
    private static final DateFormat dateFormat = new SimpleDateFormat("yyyy_MM_dd_HH_mm");
    private static final String ENDPOINT = "/upload";

    public PirSensorServer(int port) throws IOException {
        super(port);
        start(SOCKET_READ_TIMEOUT, false);
        System.out.println("PIR sensor server running on port " + port);
    }

    @Override
    public Response serve(IHTTPSession session) {
        // Only process GET requests to "/upload"
        if (Method.GET.equals(session.getMethod()) && ENDPOINT.equals(session.getUri())) {
            try {
                Map<String, String> files = new HashMap<>();
                session.parseBody(files);
                Map<String, String> params = session.getParms();

                // Get parameters from the request
                String hrs = params.get("Hrs");
                String minn = params.get("minn");
                String sec = params.get("sec");
                String pirVal = params.get("PirVal");

                // Create a timestamp for logging and file naming
                String currentTimestamp = dateFormat.format(new Date());
                String logMsg = String.format("PIR Data (%s): %s:%s:%s | PirVal: %s",
                        currentTimestamp, hrs, minn, sec, pirVal);
                System.out.println(logMsg);

                String directoryPath = new File(".").getCanonicalPath() + File.separator + "sensordata";
                File directory = new File(directoryPath);
                if (!directory.exists()) {
                    directory.mkdirs();
                }
                String fileName = "PIRData_" + currentTimestamp + ".csv";
                File file = new File(directory, fileName);

                // Append data to the CSV file
                try (BufferedWriter out = new BufferedWriter(new FileWriter(file, true))) {
                    // CSV columns: Hrs, minn, sec, PirVal
                    out.write(hrs + "," + minn + "," + sec + "," + pirVal);
                    out.newLine();
                }
            } catch (Exception e) {
                System.out.println("Error in PirSensorServer: " + e);
                return newFixedLengthResponse("Error receiving PIR sensor data");
            }
        }
        return newFixedLengthResponse("");
    }
}