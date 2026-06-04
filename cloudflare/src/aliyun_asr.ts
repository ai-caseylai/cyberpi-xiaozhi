/**
 * Alibaba Cloud ASR (智能语音交互) — One-sentence Recognition
 *
 * Uses HMAC-SHA1 token-based authentication.
 * API: https://help.aliyun.com/document_detail/324194.html
 */

export interface AliyunAsrConfig {
  accessKeyId: string;
  accessKeySecret: string;
  appKey: string;
  endpoint?: string; // default: nls-gateway-cn-shanghai.aliyuncs.com
}

interface AliyunAsrResponse {
  status: number;
  result: string;
  message?: string;
}

/**
 * Generate a signed token for Alibaba Cloud ASR.
 * Token format: accessKeyId:expiration:signature
 */
async function generateToken(accessKeyId: string, accessKeySecret: string): Promise<string> {
  const expiration = Math.floor(Date.now() / 1000) + 3600; // 1 hour

  // String to sign: "accessKeyId + ":" + expiration"
  const stringToSign = `${accessKeyId}:${expiration}`;

  // HMAC-SHA1 sign with AccessKey Secret
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(accessKeySecret),
    { name: 'HMAC', hash: 'SHA-1' },
    false,
    ['sign']
  );
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(stringToSign));
  const signatureBase64 = btoa(String.fromCharCode(...new Uint8Array(signature)));

  return `${accessKeyId}:${expiration}:${signatureBase64}`;
}

/**
 * Call Alibaba Cloud one-sentence recognition.
 *
 * @param audioData  Raw Opus audio bytes
 * @param config     Alibaba Cloud credentials
 * @param sampleRate Audio sample rate (e.g. 16000)
 * @returns Transcribed text
 */
export async function aliyunAsrRecognize(
  audioData: Uint8Array,
  config: AliyunAsrConfig,
  sampleRate: number = 16000
): Promise<string> {
  const endpoint = config.endpoint || 'nls-gateway-cn-shanghai.aliyuncs.com';
  const url = `https://${endpoint}/stream/v1/asr`;

  // Generate token
  const token = await generateToken(config.accessKeyId, config.accessKeySecret);

  // Build request — Alibaba Cloud ASR accepts PCM/WAV/OPUS
  // For OPUS format: need to specify format=opus, sample_rate=16000
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'X-NLS-Token': token,
      'Content-Type': 'application/octet-stream',
    },
    body: audioData,
  });

  if (!response.ok) {
    console.error(`Aliyun ASR HTTP error: ${response.status}`);
    const errText = await response.text();
    console.error(`Aliyun ASR response: ${errText}`);
    return '';
  }

  const result: AliyunAsrResponse = await response.json();

  if (result.status !== 20000000) {
    console.error(`Aliyun ASR error: status=${result.status} message=${result.message}`);
    return '';
  }

  return result.result || '';
}

/**
 * Call Alibaba Cloud ASR with parameters via query string.
 * More configurable version that specifies appkey, format, sample_rate, etc.
 */
export async function aliyunAsrWithParams(
  audioData: Uint8Array,
  config: AliyunAsrConfig,
  params: {
    format?: string;    // pcm, wav, opus, speex, etc.
    sampleRate?: number;
    enablePunctuation?: boolean;
    enableITN?: boolean; // Inverse Text Normalization
    language?: string;   // Cantonese/Chinese/English
  } = {}
): Promise<string> {
  const endpoint = config.endpoint || 'nls-gateway-cn-shanghai.aliyuncs.com';
  const format = params.format || 'opus';
  const sampleRate = params.sampleRate || 16000;

  // Build URL with query parameters
  const queryParams = new URLSearchParams({
    appkey: config.appKey,
    format,
    sample_rate: String(sampleRate),
    enable_punctuation_prediction: String(params.enablePunctuation ?? true),
    enable_inverse_text_normalization: String(params.enableITN ?? true),
  });

  // Language parameter (for Cantonese use "cantonese" or "yue")
  // Alibaba Cloud supports: mandarin, cantonese, english, etc.
  if (params.language) {
    queryParams.set('language', params.language);
  }

  const url = `https://${endpoint}/stream/v1/asr?${queryParams.toString()}`;
  const token = await generateToken(config.accessKeyId, config.accessKeySecret);

  console.log(`Aliyun ASR: format=${format} rate=${sampleRate} lang=${params.language || 'auto'} size=${audioData.length}`);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-NLS-Token': token,
        'Content-Type': 'application/octet-stream',
      },
      body: audioData,
    });

    const text = await response.text();

    // Parse JSON response
    let result: AliyunAsrResponse;
    try {
      result = JSON.parse(text);
    } catch {
      console.error(`Aliyun ASR non-JSON response: ${text.substring(0, 200)}`);
      return '';
    }

    if (result.status !== 20000000) {
      console.error(`Aliyun ASR error: status=${result.status} message=${result.message || ''}`);
      return '';
    }

    console.log(`Aliyun ASR result: "${result.result}"`);
    return result.result || '';
  } catch (err) {
    console.error(`Aliyun ASR fetch error:`, err);
    return '';
  }
}
