#include "xiaozhi_protocol.h"
#include "cJSON.h"
#include "esp_log.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static const char *TAG = "XZ-PROTO";

void xz_build_headers(char *buf, size_t buf_size,
                      const char *token, const char *device_id,
                      const char *client_id) {
    snprintf(buf, buf_size,
             "Authorization: Bearer %s\r\n"
             "Protocol-Version: 3\r\n"
             "Device-Id: %s\r\n"
             "Client-Id: %s\r\n",
             token ? token : "", device_id ? device_id : "", client_id ? client_id : "");
}

char *xz_build_hello(void) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "hello");
    cJSON_AddNumberToObject(root, "version", XZ_PROTOCOL_VERSION);
    cJSON_AddStringToObject(root, "transport", "websocket");

    cJSON *features = cJSON_CreateObject();
    cJSON_AddBoolToObject(features, "mcp", true);
    cJSON_AddItemToObject(root, "features", features);

    cJSON *ap = cJSON_CreateObject();
    cJSON_AddStringToObject(ap, "format", "opus");
    cJSON_AddNumberToObject(ap, "sample_rate", XZ_AUDIO_SAMPLE_RATE);
    cJSON_AddNumberToObject(ap, "channels", 1);
    cJSON_AddNumberToObject(ap, "frame_duration", XZ_FRAME_DURATION_MS);
    cJSON_AddItemToObject(root, "audio_params", ap);

    char *s = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return s;
}

char *xz_build_listen(const char *state, const char *mode) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "listen");
    cJSON_AddStringToObject(root, "state", state);
    cJSON_AddStringToObject(root, "mode", mode ? mode : "manual");
    char *s = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return s;
}

char *xz_build_detect(const char *text, const char *mode) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "listen");
    cJSON_AddStringToObject(root, "state", "detect");
    cJSON_AddStringToObject(root, "text", text);
    cJSON_AddStringToObject(root, "mode", mode ? mode : "auto");
    char *s = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return s;
}

char *xz_build_abort(const char *reason) {
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "abort");
    cJSON_AddStringToObject(root, "reason", reason);
    char *s = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return s;
}

xz_message_type_t xz_parse_server_message(const char *json, int json_len,
                                          xz_server_hello_t *hello_out,
                                          char *text_out, size_t text_max,
                                          char *emotion_out, size_t emotion_max) {
    if (!json || json_len < 4) return XZ_MSG_UNKNOWN;

    cJSON *msg = cJSON_ParseWithLength(json, json_len);
    if (!msg) return XZ_MSG_UNKNOWN;

    cJSON *type = cJSON_GetObjectItem(msg, "type");
    if (!type || !type->valuestring) {
        cJSON_Delete(msg);
        return XZ_MSG_UNKNOWN;
    }

    xz_message_type_t result = XZ_MSG_UNKNOWN;
    const char *t = type->valuestring;

    if (strcmp(t, "hello") == 0) {
        result = XZ_MSG_HELLO;
        if (hello_out) {
            memset(hello_out, 0, sizeof(*hello_out));
            cJSON *sid = cJSON_GetObjectItem(msg, "session_id");
            if (sid && sid->valuestring)
                strncpy(hello_out->session_id, sid->valuestring, XZ_SESSION_ID_MAX - 1);

            cJSON *ap = cJSON_GetObjectItem(msg, "audio_params");
            if (ap) {
                cJSON *fmt = cJSON_GetObjectItem(ap, "format");
                cJSON *sr  = cJSON_GetObjectItem(ap, "sample_rate");
                cJSON *ch  = cJSON_GetObjectItem(ap, "channels");
                cJSON *fd  = cJSON_GetObjectItem(ap, "frame_duration");
                if (fmt && fmt->valuestring)
                    strncpy(hello_out->format, fmt->valuestring, sizeof(hello_out->format) - 1);
                if (sr)  hello_out->sample_rate    = sr->valueint;
                if (ch)  hello_out->channels        = ch->valueint;
                if (fd)  hello_out->frame_duration  = fd->valueint;
            }
        }
    } else if (strcmp(t, "stt") == 0) {
        result = XZ_MSG_STT;
        if (text_out) {
            cJSON *txt = cJSON_GetObjectItem(msg, "text");
            text_out[0] = 0;
            if (txt && txt->valuestring)
                strncpy(text_out, txt->valuestring, text_max - 1);
        }
    } else if (strcmp(t, "llm") == 0) {
        result = XZ_MSG_LLM;
        if (text_out) {
            cJSON *txt = cJSON_GetObjectItem(msg, "text");
            text_out[0] = 0;
            if (txt && txt->valuestring)
                strncpy(text_out, txt->valuestring, text_max - 1);
        }
        if (emotion_out) {
            cJSON *e = cJSON_GetObjectItem(msg, "emotion");
            emotion_out[0] = 0;
            if (e && e->valuestring)
                strncpy(emotion_out, e->valuestring, emotion_max - 1);
        }
    } else if (strcmp(t, "tts") == 0) {
        cJSON *state = cJSON_GetObjectItem(msg, "state");
        if (state && state->valuestring) {
            if (strcmp(state->valuestring, "start") == 0)
                result = XZ_MSG_TTS_START;
            else if (strcmp(state->valuestring, "stop") == 0)
                result = XZ_MSG_TTS_STOP;
            else if (strcmp(state->valuestring, "sentence_start") == 0) {
                result = XZ_MSG_TTS_SENTENCE;
                if (text_out) {
                    cJSON *txt = cJSON_GetObjectItem(msg, "text");
                    text_out[0] = 0;
                    if (txt && txt->valuestring)
                        strncpy(text_out, txt->valuestring, text_max - 1);
                }
            }
        }
    } else if (strcmp(t, "system") == 0) {
        result = XZ_MSG_SYSTEM;
        if (text_out) {
            cJSON *cmd = cJSON_GetObjectItem(msg, "command");
            text_out[0] = 0;
            if (cmd && cmd->valuestring)
                strncpy(text_out, cmd->valuestring, text_max - 1);
        }
    } else if (strcmp(t, "alert") == 0) {
        result = XZ_MSG_ALERT;
        if (text_out) {
            cJSON *txt = cJSON_GetObjectItem(msg, "message");
            text_out[0] = 0;
            if (txt && txt->valuestring)
                strncpy(text_out, txt->valuestring, text_max - 1);
        }
        if (emotion_out) {
            cJSON *e = cJSON_GetObjectItem(msg, "emotion");
            emotion_out[0] = 0;
            if (e && e->valuestring)
                strncpy(emotion_out, e->valuestring, emotion_max - 1);
        }
    } else if (strcmp(t, "mcp") == 0) {
        result = XZ_MSG_MCP;
    }

    cJSON_Delete(msg);
    return result;
}
