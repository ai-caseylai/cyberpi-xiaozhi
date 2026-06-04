#include "audio_pipeline.h"
#include "opus_codec.h"
#include "xiaozhi_protocol.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "AUDIO";

static opus_codec_ctx_t *p_enc = NULL;
static opus_codec_ctx_t *p_dec = NULL;
static int p_downlink_rate = 24000;

static bool p_capturing = false;
static bool p_playing = false;
static int  p_captured_frames = 0;

/* WebSocket sender */
static void *p_ws_client = NULL;
static int (*p_ws_send_bin)(void *client, const uint8_t *data, size_t len) = NULL;

/* Downlink Opus buffer: ring buffer for TTS frames */
#define MAX_OPUS_FRAME    1500
#define MAX_TTS_FRAMES    32
static uint8_t p_tts_buf[MAX_TTS_FRAMES][MAX_OPUS_FRAME];
static int    p_tts_len[MAX_TTS_FRAMES];
static int    p_tts_head = 0, p_tts_tail = 0, p_tts_count = 0;

/* ── Uplink ── */

void audio_pipeline_set_ws_sender(void *ws_client,
    int (*send_bin)(void *client, const uint8_t *data, size_t len))
{
    p_ws_client = ws_client;
    p_ws_send_bin = send_bin;
}

esp_err_t audio_pipeline_init(void) {
    if (!p_enc) p_enc = x_opus_encoder_create(16000, 60);
    if (!p_dec) p_dec = x_opus_decoder_create(24000, 60);
    if (!p_enc || !p_dec) {
        ESP_LOGE(TAG, "Opus init failed");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Pipeline ready: enc=16kHz dec=%dHz", p_downlink_rate);
    return ESP_OK;
}

void audio_pipeline_set_downlink_rate(int rate) {
    if (rate != p_downlink_rate && rate > 0) {
        p_downlink_rate = rate;
        if (p_dec) opus_codec_destroy(p_dec);
        p_dec = x_opus_decoder_create(rate, 60);
        ESP_LOGI(TAG, "Downlink rate changed to %d Hz", rate);
    }
}

void audio_pipeline_start_capture(void) {
    p_capturing = true;
    p_captured_frames = 0;
}

void audio_pipeline_stop_capture(void) {
    p_capturing = false;
}

bool audio_pipeline_is_capturing(void) {
    return p_capturing;
}

int audio_pipeline_captured_frames(void) {
    return p_captured_frames;
}

/* Called from main loop for each 960-sample chunk from I2S */
esp_err_t audio_pipeline_encode_and_send(const int16_t *pcm, int samples) {
    if (!p_enc || !p_ws_client || !p_ws_send_bin) return ESP_FAIL;

    static uint8_t frame[MAX_OPUS_FRAME + 4]; // static: avoid stack overflow
    int encoded = opus_encode_frame(p_enc, pcm, samples, frame + 4, sizeof(frame) - 4);
    if (encoded < 0) {
        ESP_LOGE(TAG, "Opus encode failed: %d", encoded);
        return ESP_FAIL;
    }

    xz_build_binary_header(frame, (uint16_t)encoded);
    p_ws_send_bin(p_ws_client, frame, encoded + 4);
    p_captured_frames++;
    return ESP_OK;
}

/* ── Downlink ── */

esp_err_t audio_pipeline_push_opus(const uint8_t *opus_data, size_t opus_len) {
    if (opus_len > MAX_OPUS_FRAME) {
        ESP_LOGE(TAG, "Opus frame too large: %d", (int)opus_len);
        return ESP_FAIL;
    }
    if (p_tts_count >= MAX_TTS_FRAMES) {
        ESP_LOGW(TAG, "TTS buffer full, dropping frame");
        return ESP_FAIL;
    }
    memcpy(p_tts_buf[p_tts_head], opus_data, opus_len);
    p_tts_len[p_tts_head] = opus_len;
    p_tts_head = (p_tts_head + 1) % MAX_TTS_FRAMES;
    p_tts_count++;
    return ESP_OK;
}

int audio_pipeline_tts_buffered(void) {
    return p_tts_count;
}

void audio_pipeline_start_playback(void) {
    p_playing = true;
}

void audio_pipeline_stop_playback(void) {
    p_playing = false;
    p_tts_head = p_tts_tail = p_tts_count = 0;
}

bool audio_pipeline_is_playing(void) {
    return p_playing;
}

/* Decode and play one buffered Opus frame. Returns samples decoded, <0 on error, 0 if none buffered. */
int audio_pipeline_play_one_frame(int16_t *pcm_out, int pcm_max) {
    if (!p_playing || p_tts_count == 0) return 0;

    if (!p_dec) return -1;

    int samples = opus_decode_frame(p_dec, p_tts_buf[p_tts_tail], p_tts_len[p_tts_tail],
                                    pcm_out, pcm_max);
    p_tts_tail = (p_tts_tail + 1) % MAX_TTS_FRAMES;
    p_tts_count--;

    if (samples < 0) {
        ESP_LOGE(TAG, "Opus decode failed: %d", samples);
        return samples;
    }
    return samples;
}

/* ── Downlink PCM buffer ── */
#define PCM_BUF_SAMPLES  (16000 * 30)  // 30 seconds TTS @ 16kHz (960KB PSRAM)
static int16_t *p_pcm_buf = NULL;
static int p_pcm_head = 0, p_pcm_tail = 0, p_pcm_count = 0;

esp_err_t audio_pipeline_push_pcm(const int16_t *pcm, int samples) {
    if (!p_pcm_buf) {
        p_pcm_buf = (int16_t *)heap_caps_malloc(PCM_BUF_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM);
        if (!p_pcm_buf) p_pcm_buf = (int16_t *)malloc(PCM_BUF_SAMPLES * sizeof(int16_t));
        if (!p_pcm_buf) { ESP_LOGE(TAG, "PCM buf alloc failed"); return ESP_FAIL; }
        p_pcm_head = p_pcm_tail = p_pcm_count = 0;
    }
    if (p_pcm_count + samples > PCM_BUF_SAMPLES) {
        ESP_LOGW(TAG, "PCM buffer full, flushing old data");
        p_pcm_head = p_pcm_tail = p_pcm_count = 0;
    }
    for (int i = 0; i < samples; i++) {
        p_pcm_buf[p_pcm_head] = pcm[i];
        p_pcm_head = (p_pcm_head + 1) % PCM_BUF_SAMPLES;
    }
    p_pcm_count += samples;
    return ESP_OK;
}

int audio_pipeline_pcm_buffered(void) {
    return p_pcm_count;
}

int audio_pipeline_read_pcm(int16_t *pcm_out, int max_samples) {
    if (p_pcm_count == 0 || !p_pcm_buf) return 0;
    int to_read = (max_samples < p_pcm_count) ? max_samples : p_pcm_count;
    for (int i = 0; i < to_read; i++) {
        pcm_out[i] = p_pcm_buf[p_pcm_tail];
        p_pcm_tail = (p_pcm_tail + 1) % PCM_BUF_SAMPLES;
    }
    p_pcm_count -= to_read;
    return to_read;
}

void audio_pipeline_reset(void) {
    p_capturing = false;
    p_playing = false;
    p_captured_frames = 0;
    p_tts_head = p_tts_tail = p_tts_count = 0;
    p_pcm_head = p_pcm_tail = p_pcm_count = 0;
    if (p_enc) opus_codec_destroy(p_enc);
    if (p_dec) opus_codec_destroy(p_dec);
    p_enc = NULL;
    p_dec = NULL;
}
