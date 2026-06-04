#include "opus_codec.h"
#include "opus.h"
#include "esp_log.h"
#include <stdlib.h>
#include <string.h>

static const char *TAG = "OPUS";

struct opus_codec_ctx {
    void *handle;       // OpusEncoder* or OpusDecoder*
    int sample_rate;
    int channels;
    int frame_samples;
    bool is_encoder;
};

opus_codec_ctx_t *x_opus_encoder_create(int sample_rate, int frame_ms) {
    opus_codec_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) { ESP_LOGE(TAG, "OOM encoder ctx"); return NULL; }

    int frame_samples = sample_rate * frame_ms / 1000;
    int err = 0;
    OpusEncoder *enc = opus_encoder_create(sample_rate, 1, OPUS_APPLICATION_VOIP, &err);
    if (err != OPUS_OK || !enc) {
        ESP_LOGE(TAG, "opus_encoder_create failed: %d", err);
        free(ctx);
        return NULL;
    }
    // Minimum complexity for lowest CPU usage on ESP32
    opus_encoder_ctl(enc, OPUS_SET_COMPLEXITY(1));
    // Disable variable bitrate for consistent packet sizes
    opus_encoder_ctl(enc, OPUS_SET_VBR(0));
    opus_encoder_ctl(enc, OPUS_SET_BITRATE(32000));

    ctx->handle = enc;
    ctx->sample_rate = sample_rate;
    ctx->channels = 1;
    ctx->frame_samples = frame_samples;
    ctx->is_encoder = true;

    ESP_LOGI(TAG, "Encoder created: %dHz %dms frame=%d samples",
             sample_rate, frame_ms, frame_samples);
    return ctx;
}

int opus_encode_frame(opus_codec_ctx_t *ctx, const int16_t *pcm, int samples,
                      uint8_t *out, int out_max) {
    if (!ctx || !ctx->is_encoder || !pcm || !out) return -1;
    if (samples != ctx->frame_samples) {
        ESP_LOGW(TAG, "encode: expected %d samples, got %d", ctx->frame_samples, samples);
        return -2;
    }
    int len = opus_encode((OpusEncoder*)ctx->handle, pcm, samples, out, out_max);
    if (len < 0) {
        ESP_LOGE(TAG, "opus_encode error: %d", len);
    }
    return len;
}

opus_codec_ctx_t *x_opus_decoder_create(int sample_rate, int frame_ms) {
    opus_codec_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) { ESP_LOGE(TAG, "OOM decoder ctx"); return NULL; }

    int frame_samples = sample_rate * frame_ms / 1000;
    int err = 0;
    OpusDecoder *dec = opus_decoder_create(sample_rate, 1, &err);
    if (err != OPUS_OK || !dec) {
        ESP_LOGE(TAG, "opus_decoder_create failed: %d", err);
        free(ctx);
        return NULL;
    }

    ctx->handle = dec;
    ctx->sample_rate = sample_rate;
    ctx->channels = 1;
    ctx->frame_samples = frame_samples;
    ctx->is_encoder = false;

    ESP_LOGI(TAG, "Decoder created: %dHz %dms frame=%d samples",
             sample_rate, frame_ms, frame_samples);
    return ctx;
}

int opus_decode_frame(opus_codec_ctx_t *ctx, const uint8_t *opus_data, int opus_len,
                      int16_t *pcm_out, int pcm_max) {
    if (!ctx || ctx->is_encoder || !opus_data || !pcm_out) return -1;
    if (pcm_max < ctx->frame_samples) {
        ESP_LOGW(TAG, "decode: pcm_max %d < frame_samples %d", pcm_max, ctx->frame_samples);
        return -2;
    }
    int samples = opus_decode((OpusDecoder*)ctx->handle, opus_data, opus_len,
                              pcm_out, pcm_max, 0);
    if (samples < 0) {
        ESP_LOGE(TAG, "opus_decode error: %d", samples);
    }
    return samples;
}

int opus_frame_samples(opus_codec_ctx_t *ctx) {
    return ctx ? ctx->frame_samples : 0;
}

int opus_sample_rate(opus_codec_ctx_t *ctx) {
    return ctx ? ctx->sample_rate : 0;
}

void opus_codec_destroy(opus_codec_ctx_t *ctx) {
    if (!ctx) return;
    if (ctx->is_encoder) {
        opus_encoder_destroy((OpusEncoder*)ctx->handle);
    } else {
        opus_decoder_destroy((OpusDecoder*)ctx->handle);
    }
    free(ctx);
}
