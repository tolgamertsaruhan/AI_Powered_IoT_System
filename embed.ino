#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <time.h>

#define WIFI_SSID "G301"
#define WIFI_PASSWORD "tolga123"
#define FIREBASE_STORAGE_BUCKET "iott-32784.firebasestorage.app"

const int micPin = 32;
const int sampleRate = 8000;
const int recordSeconds = 2;
const int numSamples = sampleRate * recordSeconds;
uint16_t samples[numSamples];

#define SOIL_PIN 34
#define PIR_PIN 35
#define SEALEVELPRESSURE_HPA (1013.25)

#define REC_PIN   2
#define PLAYL_PIN 5
#define PLAYE_PIN 4

Adafruit_BME280 bme;
float temperature, humidity, pressure;
int soil;
bool motion;

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
}

String getTimestamp() {
  time_t now = time(nullptr);
  struct tm timeinfo;
  gmtime_r(&now, &timeinfo);  // UTC time
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H-%M-%S", &timeinfo);
  return String(buf);  // Example: "2025-05-30T11-24-55"
}


void recordAudio() {
  Serial.println("Start recording...");
  unsigned long startMicros = micros();
  for (int i = 0; i < numSamples; i++) {
    samples[i] = analogRead(micPin);
    unsigned long targetMicros = startMicros + (i + 1) * 1000000 / sampleRate;
    while (micros() < targetMicros) {
      yield();
    }
  }
  Serial.println("Recording done.");
}

bool uploadBinaryToFirebaseStorage(String fileName, uint8_t* data, size_t length, const String& contentType) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  String url = "https://firebasestorage.googleapis.com/v0/b/" + String(FIREBASE_STORAGE_BUCKET) + "/o?uploadType=media&name=" + fileName;

  http.begin(url);
  http.addHeader("Content-Type", contentType);

  int httpResponseCode = http.POST(data, length);
  if (httpResponseCode == 200 || httpResponseCode == 201) {
    Serial.println("Upload successful: " + fileName);
    http.end();
    return true;
  } else {
    Serial.printf("Upload failed (%s). Code: %d\n", fileName.c_str(), httpResponseCode);
    Serial.println(http.getString());
    http.end();
    return false;
  }
}

void uploadAudioFile(String timestamp) {
  String fileName = "audio_" + timestamp + ".raw";
  uploadBinaryToFirebaseStorage(fileName, (uint8_t*)samples, numSamples * sizeof(uint16_t), "application/octet-stream");
}

void uploadSensorDataFile(String timestamp) {
  temperature = bme.readTemperature();
  humidity = bme.readHumidity();
  pressure = bme.readPressure() / 100.0F;
  soil = analogRead(SOIL_PIN);
  motion = digitalRead(PIR_PIN);

  String jsonData = "{";
  jsonData += "\"timestamp\": \"" + timestamp + "\",";
  jsonData += "\"temperature\": " + String(temperature) + ",";
  jsonData += "\"humidity\": " + String(humidity) + ",";
  jsonData += "\"pressure\": " + String(pressure) + ",";
  jsonData += "\"soil_moisture\": " + String(soil) + ",";
  jsonData += "\"motion_detected\": " + String(motion ? "true" : "false");
  jsonData += "}";

  Serial.println(jsonData);  // Optional: debug output

  String fileName = "sensor_" + timestamp + ".json";
  uploadBinaryToFirebaseStorage(fileName, (uint8_t*)jsonData.c_str(), jsonData.length(), "application/json");
}

void checkAndPlayFromEndpoint() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin("https://firebasestorage.googleapis.com/v0/b/iott-32784.firebasestorage.app/o/warning.txt?alt=media");

    int httpCode = http.GET();
    if (httpCode == 200) {
      String payload = http.getString();
      Serial.println("File contents:");
      Serial.println(payload);
      if (payload == "true") {
        Serial.println("Triggering playback via PLAYE_PIN");
        digitalWrite(PLAYE_PIN, HIGH);
        delay(100);  // short pulse
        digitalWrite(PLAYE_PIN, LOW);
      } else {
        Serial.println("No playback triggered.");
      }
    } else {
      Serial.printf("Failed to get file, HTTP code: %d\n", httpCode);
    }

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}


void setup() {
  Serial.begin(115200);
  connectWiFi();
  // Set your time zone (UTC+3 for Turkey)
  configTime(10800, 0, "pool.ntp.org", "time.nist.gov");

// Wait for NTP to sync
  Serial.print("Waiting for NTP time sync...");
  time_t now = time(nullptr);
  while (now < 8 * 3600 * 2) {  // wait until valid time
    delay(500);
    Serial.print(".");
    now = time(nullptr);
  }
Serial.println(" done!");

  analogReadResolution(12);

  if (!bme.begin(0x76)) {
    Serial.println("Could not find BME280!");
    while (1);
  }

  pinMode(PIR_PIN, INPUT);
  pinMode(REC_PIN, OUTPUT);
  pinMode(PLAYL_PIN, OUTPUT);
  pinMode(PLAYE_PIN, OUTPUT);
  digitalWrite(REC_PIN, LOW);
  digitalWrite(PLAYL_PIN, LOW);
  digitalWrite(PLAYE_PIN, LOW);
}

void loop() {
  String timestamp = getTimestamp();

  recordAudio();
  uploadAudioFile(timestamp);
  uploadSensorDataFile(timestamp);
  checkAndPlayFromEndpoint();
  delay(10000);  // 10 seconds between cycles
}
