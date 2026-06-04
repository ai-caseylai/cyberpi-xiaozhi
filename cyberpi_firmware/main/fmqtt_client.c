#include "fmqtt_client.h"
#include "mqtt_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

static const char *TAG = "MQTT";
static esp_mqtt_client_handle_t mqtt = NULL;
static bool mqtt_ok = false;
static void (*sensor_cb)(int temp, int humidity) = NULL;

#define MQTT_TOPIC_PREFIX "funconnect/default"

static void mqtt_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "Connected to broker");
        mqtt_ok = true;
        // Subscribe to command topics
        {
            char topic[128];
            snprintf(topic, sizeof(topic), "%s/%s/cmd/#", MQTT_TOPIC_PREFIX, "cyberpi");
            esp_mqtt_client_subscribe(mqtt, topic, 0);
            ESP_LOGI(TAG, "Subscribed to %s", topic);
        }
        break;
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "Disconnected");
        mqtt_ok = false;
        break;
    case MQTT_EVENT_DATA:
        if (event->topic && event->data) {
            ESP_LOGI(TAG, "RX: %.*s = %.*s",
                     event->topic_len, event->topic,
                     event->data_len, event->data);
            // Parse IoT commands
            if (sensor_cb && strstr(event->topic, "state") == NULL) {
                // Handle command — future: parse and execute
            }
        }
        break;
    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT error");
        break;
    default:
        break;
    }
}

esp_err_t mqtt_client_init(const char *broker_url) {
    uint8_t mac[6]; char mac_str[20];
    esp_efuse_mac_get_default(mac);
    snprintf(mac_str, sizeof(mac_str), "%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = broker_url,
        .credentials.client_id = mac_str,
    };

    mqtt = esp_mqtt_client_init(&cfg);
    if (!mqtt) { ESP_LOGE(TAG, "Init failed"); return ESP_FAIL; }

    esp_mqtt_client_register_event(mqtt, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(mqtt);

    ESP_LOGI(TAG, "Connecting to %s...", broker_url);
    return ESP_OK;
}

esp_err_t mqtt_publish(const char *topic, const char *payload) {
    if (!mqtt_ok) return ESP_FAIL;
    int ret = esp_mqtt_client_publish(mqtt, topic, payload, 0, 0, 0);
    return (ret >= 0) ? ESP_OK : ESP_FAIL;
}

esp_err_t mqtt_subscribe(const char *topic) {
    if (!mqtt_ok) return ESP_FAIL;
    int ret = esp_mqtt_client_subscribe(mqtt, topic, 0);
    return (ret >= 0) ? ESP_OK : ESP_FAIL;
}

bool mqtt_is_connected(void) { return mqtt_ok; }

void mqtt_set_sensor_cb(void (*cb)(int temp, int humidity)) { sensor_cb = cb; }

esp_err_t mqtt_publish_sensor(int temp, int humidity) {
    char buf[128];
    snprintf(buf, sizeof(buf), "{\"temp\":%d,\"humidity\":%d}", temp, humidity);
    char topic[128];
    snprintf(topic, sizeof(topic), "%s/%s/state/sensor", MQTT_TOPIC_PREFIX, "cyberpi");
    return mqtt_publish(topic, buf);
}

esp_err_t mqtt_publish_state(const char *device, const char *state) {
    char topic[128];
    snprintf(topic, sizeof(topic), "%s/%s/state/%s", MQTT_TOPIC_PREFIX, "cyberpi", device);
    return mqtt_publish(topic, state);
}
