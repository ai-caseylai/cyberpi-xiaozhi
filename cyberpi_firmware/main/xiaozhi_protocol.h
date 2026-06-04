#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Protocol constants */
#define XZ_PROTOCOL_VERSION    3
#define XZ_AUDIO_SAMPLE_RATE   16000
#define XZ_FRAME_DURATION_MS   60
#define XZ_FRAME_SAMPLES       (XZ_AUDIO_SAMPLE_RATE * XZ_FRAME_DURATION_MS / 1000)  // 960

#define XZ_SESSION_ID_MAX      64
#define XZ_TEXT_MAX            512
#define XZ_EMOTION_MAX         32
#define XZ_AUTH_HEADER_MAX     384

/* Binary Protocol v3 header (4 bytes, big-endian payload_size) */
typedef struct __attribute__((packed)) {
    uint8_t  type;          // 0 = audio
    uint8_t  reserved;      // 0
    uint16_t payload_size;  // big-endian
} xz_binary_header_t;

/* Message types parsed from server JSON */
typedef enum {
    XZ_MSG_UNKNOWN      = 0,
    XZ_MSG_HELLO        = 1,
    XZ_MSG_STT          = 2,
    XZ_MSG_LLM          = 3,
    XZ_MSG_TTS_START    = 4,
    XZ_MSG_TTS_STOP     = 5,
    XZ_MSG_TTS_SENTENCE = 6,
    XZ_MSG_ABORT        = 7,
    XZ_MSG_SYSTEM       = 8,
    XZ_MSG_ALERT        = 9,
    XZ_MSG_MCP          = 10,
} xz_message_type_t;

/* Helds parsed from server hello */
typedef struct {
    char session_id[XZ_SESSION_ID_MAX];
    char format[16];
    int  sample_rate;
    int  channels;
    int  frame_duration;
} xz_server_hello_t;

/* --- WebSocket header construction --- */

/**
 * Build WebSocket upgrade headers string.
 * Format: "Authorization: Bearer <token>\r\nProtocol-Version: 3\r\nDevice-Id: <id>\r\nClient-Id: <client>\r\n"
 */
void xz_build_headers(char *buf, size_t buf_size,
                      const char *token, const char *device_id,
                      const char *client_id);

/* --- JSON message builders (caller must free the returned string) --- */

/** Build hello JSON: {"type":"hello","version":3,"transport":"websocket","features":{"mcp":true},...} */
char *xz_build_hello(void);

/** Build listen JSON: {"type":"listen","state":"start|stop","mode":"manual"} */
char *xz_build_listen(const char *state, const char *mode);

/** Build listen detect (text-only): {"type":"listen","state":"detect","text":"..."} */
char *xz_build_detect(const char *text, const char *mode);

/** Build abort JSON: {"type":"abort","reason":"..."} */
char *xz_build_abort(const char *reason);

/* --- Server message parser --- */

/**
 * Parse a JSON message from server.
 * Returns message type.
 * For hello: fills server_hello struct.
 * For stt/llm/tts_sentence/alert: fills text_out and emotion_out.
 * For system: fills text_out with command name.
 */
xz_message_type_t xz_parse_server_message(const char *json, int json_len,
                                          xz_server_hello_t *hello_out,
                                          char *text_out, size_t text_max,
                                          char *emotion_out, size_t emotion_max);

/* --- Binary frame construction --- */

/** Write 4-byte binary protocol v3 header. payload_size in network byte order. */
static inline void xz_build_binary_header(uint8_t *buf, uint16_t payload_size) {
    buf[0] = 0;                           // type = audio
    buf[1] = 0;                           // reserved
    buf[2] = (payload_size >> 8) & 0xFF;  // payload_size big-endian high byte
    buf[3] = payload_size & 0xFF;         // low byte
}

#ifdef __cplusplus
}
#endif
