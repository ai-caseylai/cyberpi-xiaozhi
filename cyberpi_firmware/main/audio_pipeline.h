#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize audio hardware and allocate buffers.
 * Must be called once before any other pipeline functions.
 */
esp_err_t audio_pipeline_init(void);

/* ── Uplink (Mic → Opus → WebSocket) ── */

/** Start streaming capture: I2S RX → Opus encode → callback for each frame */
void audio_pipeline_start_capture(void);

/** Stop capture loop */
void audio_pipeline_stop_capture(void);

/** Set the WebSocket client handle for sending binary frames */
void audio_pipeline_set_ws_sender(void *ws_client,
    int (*send_bin)(void *client, const uint8_t *data, size_t len));

/** Change downlink sample rate (called when server hello received) */
void audio_pipeline_set_downlink_rate(int rate);

/** Encode PCM and send via WebSocket (called from main loop during capture) */
esp_err_t audio_pipeline_encode_and_send(const int16_t *pcm, int samples);

/** Get number of frames captured (for debug/logging) */
int audio_pipeline_captured_frames(void);

/* ── Downlink (WebSocket → Opus → Speaker) ── */

/** Push an Opus frame into the TTS playback buffer */
esp_err_t audio_pipeline_push_opus(const uint8_t *opus_data, size_t opus_len);

/** Start playback: decode and play all buffered Opus frames */
void audio_pipeline_start_playback(void);

/** Stop playback immediately */
void audio_pipeline_stop_playback(void);

/** True if playback is currently active */
bool audio_pipeline_is_playing(void);

/** Get number of buffered TTS frames */
int audio_pipeline_tts_buffered(void);

/** Decode one buffered Opus frame. Returns samples decoded, <0 on error, 0 if none. */
int audio_pipeline_play_one_frame(int16_t *pcm_out, int pcm_max);

/** True if capture is currently active */
bool audio_pipeline_is_capturing(void);

/* ── Downlink PCM (direct playback, no Opus decode needed) ── */

/** Push raw PCM samples into playback buffer (for server-side TTS without Opus) */
esp_err_t audio_pipeline_push_pcm(const int16_t *pcm, int samples);

/** Get number of PCM samples currently buffered */
int audio_pipeline_pcm_buffered(void);

/** Read PCM samples from buffer for playback. Returns samples read. */
int audio_pipeline_read_pcm(int16_t *pcm_out, int max_samples);

/** Reset all buffers and state */
void audio_pipeline_reset(void);

#ifdef __cplusplus
}
#endif
