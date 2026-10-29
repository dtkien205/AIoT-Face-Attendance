#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include "config.h"

// Compatible with BTL-IoT/Firmware_ESP32: SoftAP 192.168.4.1, port 81.
// The laptop bridge pulls /capture. AI and attendance decisions stay on laptop.
static httpd_handle_t captureServer = nullptr;
static httpd_handle_t streamServer = nullptr;

static esp_err_t captureHandler(httpd_req_t *request) {
  camera_fb_t *frame = esp_camera_fb_get();
  if (!frame) return httpd_resp_send_500(request);
  httpd_resp_set_type(request, "image/jpeg");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  esp_err_t result = httpd_resp_send(request, (const char *)frame->buf, frame->len);
  esp_camera_fb_return(frame);
  return result;
}

static esp_err_t streamHandler(httpd_req_t *request) {
  esp_err_t result = httpd_resp_set_type(request, "multipart/x-mixed-replace;boundary=frame");
  while (result == ESP_OK) {
    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame) return ESP_FAIL;
    char header[100];
    int length = snprintf(header, sizeof(header), "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)frame->len);
    result = httpd_resp_send_chunk(request, header, length);
    if (result == ESP_OK) result = httpd_resp_send_chunk(request, (const char *)frame->buf, frame->len);
    esp_camera_fb_return(frame);
    delay(80);
  }
  return result;
}

void setup() {
  Serial.begin(115200);
  // Do not disable brownout detection: use a stable 5V supply.
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
  config.frame_size = FRAMESIZE_CIF;
  config.jpeg_quality = 12;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera initialization failed");
    return;
  }
  WiFi.mode(WIFI_AP);
  IPAddress address(192, 168, 4, 1);
  if (!WiFi.softAPConfig(address, address, IPAddress(255, 255, 255, 0)) ||
      !WiFi.softAP(AP_SSID, AP_PASSWORD)) {
    Serial.println("SoftAP initialization failed; check password length >= 8");
    return;
  }
  httpd_config_t serverConfig = HTTPD_DEFAULT_CONFIG();
  serverConfig.server_port = 81;
  serverConfig.ctrl_port = 32768;
  httpd_uri_t capture = {};
  capture.uri = "/capture"; capture.method = HTTP_GET; capture.handler = captureHandler;
  if (httpd_start(&captureServer, &serverConfig) != ESP_OK) return;
  httpd_register_uri_handler(captureServer, &capture);

  // Separate server so long-running preview cannot block /capture.
  serverConfig.server_port = 82;
  serverConfig.ctrl_port = 32769;
  httpd_uri_t stream = {};
  stream.uri = "/stream"; stream.method = HTTP_GET; stream.handler = streamHandler;
  if (httpd_start(&streamServer, &serverConfig) == ESP_OK) {
    httpd_register_uri_handler(streamServer, &stream);
  }
  Serial.printf("Wi-Fi: %s\nCapture: http://192.168.4.1:81/capture\nPreview: http://192.168.4.1:82/stream\n", AP_SSID);
  // No success LED: serving a JPEG does not mean attendance accepted.
}

void loop() {
  delay(1000);
}
