#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct opus_codec_ctx opus_codec_ctx_t;

/**
 * Create Opus encoder.
 * @param sample_rate  16000 (uplink mic)
 * @param frame_ms     60 (960 samples @ 16kHz)
 * @return context, or NULL on error
 */
opus_codec_ctx_t *x_opus_encoder_create(int sample_rate, int frame_ms);

/**
 * Encode one frame of PCM to Opus.
 * @param ctx      encoder context
 * @param pcm      input PCM samples (int16_t, mono)
 * @param samples  number of samples (must match frame size)
 * @param out      output buffer for Opus data
 * @param out_max  max output bytes (1275 is safe for 60ms frame)
 * @return encoded bytes, or <0 on error
 */
int opus_encode_frame(opus_codec_ctx_t *ctx, const int16_t *pcm, int samples,
                      uint8_t *out, int out_max);

/**
 * Create Opus decoder.
 * @param sample_rate  24000 (downlink TTS from server hello)
 * @param frame_ms     60 (1440 samples @ 24kHz)
 * @return context, or NULL on error
 */
opus_codec_ctx_t *x_opus_decoder_create(int sample_rate, int frame_ms);

/**
 * Decode one Opus frame to PCM.
 * @param ctx       decoder context
 * @param opus_data input Opus data
 * @param opus_len  input Opus length in bytes
 * @param pcm_out   output PCM buffer (int16_t, mono)
 * @param pcm_max   max output samples
 * @return number of PCM samples decoded, or <0 on error
 */
int opus_decode_frame(opus_codec_ctx_t *ctx, const uint8_t *opus_data, int opus_len,
                      int16_t *pcm_out, int pcm_max);

/**
 * Get frame size in samples for this context.
 */
int opus_frame_samples(opus_codec_ctx_t *ctx);

/**
 * Get sample rate for this context.
 */
int opus_sample_rate(opus_codec_ctx_t *ctx);

/**
 * Free encoder or decoder.
 */
void opus_codec_destroy(opus_codec_ctx_t *ctx);

#ifdef __cplusplus
}
#endif
