#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"

// AI Thinker ESP32-CAM. AI and attendance decisions run only on the server.
static const int STATUS_LED = 33; // active low
static uint32_t lastHeartbeat = 0;
static uint32_t lastFrame = 0;
static uint32_t lastReconnect = 0;
static int sessionId = 0;
static bool cameraReady = false;

void configureHttp(HTTPClient &http, const String &path) {
  http.begin(String(SERVER_URL) + path);
  http.setConnectTimeout(3000);
  http.setTimeout(10000);
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.addHeader("X-Device-ID", DEVICE_ID);
}

void heartbeatAndConfig() {
  HTTPClient http;
  configureHttp(http, "/api/devices/heartbeat");
  http.addHeader("Content-Type", "application/json");
  JsonDocument payload;
  payload["name"] = "ESP32-CAM";
  payload["ip_address"] = WiFi.localIP().toString();
  String body;
  serializeJson(payload, body);
  int status = http.POST(body);
  http.end();
  sessionId = 0; // fail closed if any request fails
  if (status != 200) {
    Serial.printf("Heartbeat failed: %d\n", status);
    return;
  }
  configureHttp(http, "/api/devices/config");
  status = http.GET();
  if (status == 200) {
    JsonDocument config;
    if (deserializeJson(config, http.getString()) == DeserializationError::Ok && config["active"].as<bool>()) {
      sessionId = config["session_id"].as<int>();
    }
  }
  http.end();
}

void sendFrame() {
  camera_fb_t *frame = esp_camera_fb_get();
  if (!frame) {
    Serial.println("Camera capture failed");
    return;
  }
  // JPEG is binary: build multipart without converting it to a String.
  const String boundary = "ESP32AttendanceBoundary";
  String head = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"frame.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";
  size_t length = head.length() + frame->len + tail.length();
  uint8_t *body = (uint8_t *)ps_malloc(length);
  if (!body) body = (uint8_t *)malloc(length);
  if (!body) {
    esp_camera_fb_return(frame);
    Serial.println("Insufficient upload memory");
    return;
  }
  memcpy(body, head.c_str(), head.length());
  memcpy(body + head.length(), frame->buf, frame->len);
  memcpy(body + head.length() + frame->len, tail.c_str(), tail.length());
  esp_camera_fb_return(frame);
  HTTPClient http;
  configureHttp(http, String("/api/devices/") + DEVICE_ID + "/frames?session_id=" + sessionId);
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  int status = http.POST(body, length);
  free(body);
  bool accepted = false;
  if (status == 202) {
    JsonDocument result;
    if (deserializeJson(result, http.getString()) == DeserializationError::Ok) {
      accepted = result["accepted"].as<bool>();
      Serial.printf("Frame: %s\n", accepted ? "attendance confirmed" : "not accepted");
    }
  } else {
    Serial.printf("Frame request failed: %d\n", status);
    if (status == 409) sessionId = 0;
  }
  http.end();
  if (accepted) {
    digitalWrite(STATUS_LED, LOW);
    delay(120);
    digitalWrite(STATUS_LED, HIGH);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, HIGH);
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5; config.pin_d1 = 18; config.pin_d2 = 19; config.pin_d3 = 21;
  config.pin_d4 = 36; config.pin_d5 = 39; config.pin_d6 = 34; config.pin_d7 = 35;
  config.pin_xclk = 0; config.pin_pclk = 22; config.pin_vsync = 25; config.pin_href = 23;
  config.pin_sccb_sda = 26; config.pin_sccb_scl = 27;
  config.pin_pwdn = 32; config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  cameraReady = esp_camera_init(&config) == ESP_OK;
  if (!cameraReady) Serial.println("Camera initialization failed; no attendance will be reported");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
  uint32_t now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    sessionId = 0;
    digitalWrite(STATUS_LED, HIGH);
    if (now - lastReconnect > 10000) {
      lastReconnect = now;
      WiFi.reconnect();
      Serial.println("Reconnecting Wi-Fi; no attendance confirmed");
    }
    delay(20);
    return;
  }
  if (lastHeartbeat == 0 || now - lastHeartbeat >= 10000) {
    lastHeartbeat = now;
    heartbeatAndConfig();
  }
  if (cameraReady && sessionId > 0 && now - lastFrame >= FRAME_INTERVAL_MS) {
    lastFrame = now;
    sendFrame();
  }
  delay(10);
}
