#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Initialize MQTT client and connect to broker */
esp_err_t mqtt_client_init(const char *broker_url);

/** Publish a message to a topic */
esp_err_t mqtt_publish(const char *topic, const char *payload);

/** Subscribe to a topic */
esp_err_t mqtt_subscribe(const char *topic);

/** Check if connected */
bool mqtt_is_connected(void);

/** Set sensor data callback */
void mqtt_set_sensor_cb(void (*cb)(int temp, int humidity));

/** Publish sensor reading */
esp_err_t mqtt_publish_sensor(int temp, int humidity);

/** Publish device state */
esp_err_t mqtt_publish_state(const char *device, const char *state);

#ifdef __cplusplus
}
#endif
