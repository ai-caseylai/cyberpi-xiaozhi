/**
 * FunConnectSession — Durable Object for per-device xiaozhi-esp32 sessions.
 *
 * State machine: hello → idle → listening → processing → speaking → idle
 *
 * LLM: Alibaba Cloud Bailian (DashScope) Qwen
 * STT: Cloudflare Workers AI (Nova-3) / Alibaba Cloud ASR
 * TTS: Cloudflare Workers AI (Aura-1)
 */

import {
  type HelloRequest,
  type HelloResponse,
  type ListenMessage,
  type ServerMessage,
  buildBinaryHeader,
  parseBinaryHeader,
  FRAME_DURATION_MS,
  frameSamples,
} from './protocol';
import type { Env } from './index';
import { DurableObject } from 'cloudflare:workers';

type SessionState = 'hello' | 'idle' | 'listening' | 'processing' | 'speaking';

const UPLINK_RATE = 16000;
const DOWNLINK_RATE = 16000; // Match ESP32 speaker SAMPLE_RATE
const MAX_AUDIO_BYTES = 10 * 1024 * 1024; // 10 MB safety limit

/** System prompt — Cantonese by default */
const SYSTEM_PROMPT = `你係「小芳」，香港中小學AI助教，係FunConnect AIOT平台嘅一部分。
請遵守以下規則：
- 用粵語（廣東話）同繁體中文回答
- 語氣友善、有耐心，適合中小學生理解
- 只回答學術、學校、知識相關問題
- 如果問題唔適合學生，請婉轉拒絕
- 回答盡量簡潔，唔好太長`;

export class FunConnectSession extends DurableObject {
  private ws: WebSocket | null = null;
  private state: SessionState = 'hello';
  private sessionId: string;
  private deviceId: string;
  private audioChunks: Uint8Array[] = [];
  private audioTotalSize = 0;
  private env: Env;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.env = env;
    this.sessionId = '';
    this.deviceId = '';

    // Restore from hibernation if applicable
    ctx.blockConcurrencyWhile(async () => {
      // Future: restore session state from storage
    });
  }

  async fetch(request: Request): Promise<Response> {
    // Extract session metadata from forwarded headers
    this.sessionId = request.headers.get('X-Session-Id') || crypto.randomUUID();
    this.deviceId = request.headers.get('X-Device-Id') || 'unknown';

    const pair = new WebSocketPair();
    this.ws = pair[1];
    this.ws.accept();

    this.ws.addEventListener('message', (event) => this.onMessage(event));
    this.ws.addEventListener('close', () => this.onClose());
    this.ws.addEventListener('error', (err) => console.error('WS error:', err));

    console.log(`Session started: ${this.sessionId} device=${this.deviceId}`);
    return new Response(null, { status: 101, webSocket: pair[0] });
  }

  // ── Message dispatch ──

  private async onMessage(event: MessageEvent) {
    try {
      if (typeof event.data === 'string') {
        await this.onJsonMessage(JSON.parse(event.data));
      } else if (event.data instanceof ArrayBuffer) {
        this.onBinaryMessage(new Uint8Array(event.data));
      }
    } catch (err) {
      console.error('Message error:', err);
    }
  }

  private async onJsonMessage(msg: Record<string, unknown>) {
    const type = msg.type as string;

    switch (type) {
      case 'hello':
        await this.handleHello(msg as unknown as HelloRequest);
        break;
      case 'listen':
        await this.handleListen(msg as unknown as ListenMessage);
        break;
      case 'abort':
        this.state = 'idle';
        this.audioChunks = [];
        this.audioTotalSize = 0;
        console.log('Session aborted');
        break;
      default:
        console.log('Unknown message type:', type);
    }
  }

  private onBinaryMessage(data: Uint8Array) {
    if (this.state !== 'listening') return;

    const { type, payloadSize } = parseBinaryHeader(data);
    if (type !== 0) return; // Only audio frames

    const payload = data.slice(4, 4 + payloadSize);
    this.audioChunks.push(payload);
    this.audioTotalSize += payloadSize;

    if (this.audioTotalSize > MAX_AUDIO_BYTES) {
      this.audioChunks = [];
      this.audioTotalSize = 0;
      this.state = 'idle';
      this.sendJson({ type: 'alert', status: 'error', message: '錄音太長', emotion: 'sad' });
    }
  }

  private onClose() {
    this.ws = null;
    this.audioChunks = [];
    console.log(`Session ended: ${this.sessionId}`);
  }

  // ── Protocol handlers ──

  private handleHello(req: HelloRequest) {
    const response: HelloResponse = {
      type: 'hello',
      transport: 'websocket',
      session_id: this.sessionId,
      audio_params: {
        format: 'opus',
        sample_rate: DOWNLINK_RATE,
        channels: 1,
        frame_duration: FRAME_DURATION_MS,
      },
    };

    this.sendJson(response);
    this.state = 'idle';
    console.log(`Hello complete: session=${this.sessionId}`);
  }

  private async handleListen(msg: ListenMessage) {
    if (msg.state === 'start') {
      this.state = 'listening';
      this.audioChunks = [];
      this.audioTotalSize = 0;
    } else if (msg.state === 'stop') {
      this.state = 'processing';
      await this.processAudio();
    } else if (msg.state === 'detect' && msg.text) {
      this.state = 'processing';
      await this.processText(msg.text);
    }
  }

  // ── AI Pipeline ──

  private async processText(text: string) {
    console.log(`Text query: "${text}"`);
    await this.runLlm(text);
    this.state = 'idle';
  }

  private async processAudio() {
    // Concat all Opus chunks
    const audioData = new Uint8Array(this.audioTotalSize);
    let offset = 0;
    for (const chunk of this.audioChunks) {
      audioData.set(chunk, offset);
      offset += chunk.length;
    }
    this.audioChunks = [];
    this.audioTotalSize = 0;

    console.log(`Processing audio: ${audioData.length} bytes Opus`);

    // 1. STT — Workers AI Nova-3
    let transcribed = '';
    try {
      const sttResult = await this.env.AI.run(
        this.env.STT_MODEL || '@cf/deepgram/nova-3',
        {
          audio: { data: [...audioData], contentType: 'audio/opus' },
          detect_language: true,
        }
      );
      transcribed = (sttResult as any).text ||
        (sttResult as any).channel?.alternatives?.[0]?.transcript || '';
    } catch (err) {
      console.error('STT error:', err);
      // Fallback: try Whisper if Nova-3 fails
      try {
        const whisperResult = await this.env.AI.run(
          '@cf/openai/whisper-large-v3-turbo',
          {
            audio: audioData,
            task: 'transcribe',
          }
        );
        transcribed = (whisperResult as any).text || '';
      } catch (err2) {
        console.error('Whisper fallback also failed:', err2);
        this.sendJson({ type: 'stt', text: '' });
        this.sendJson({ type: 'llm', emotion: 'sad', text: '唔好意思，聽唔清楚，可以再講一次嗎？' });
        this.state = 'idle';
        return;
      }
    }

    if (!transcribed.trim()) {
      this.sendJson({ type: 'stt', text: '' });
      this.sendJson({ type: 'llm', emotion: 'neutral', text: '我聽唔到你講咩，可唔可以再試一次？' });
      this.state = 'idle';
      return;
    }

    console.log(`STT result: "${transcribed}"`);

    // Send STT result to device
    this.sendJson({ type: 'stt', text: transcribed });

    // 2. LLM
    await this.runLlm(transcribed);

    this.state = 'idle';
  }

  private async runLlm(userText: string) {
    // Send a thinking emotion
    this.sendJson({ type: 'llm', emotion: 'thinking', text: '...' });

    let llmResponse = '';

    // Try Alibaba Cloud Bailian DashScope (Qwen) first
    if (this.env.QWEN_API_KEY) {
      try {
        llmResponse = await this.callQwen(userText);
      } catch (err) {
        console.error('Qwen error:', err);
      }
    }

    // Fallback to Cloudflare Workers AI LLM
    if (!llmResponse) {
      try {
        const llmResult = await this.env.AI.run(
          this.env.LLM_MODEL || '@cf/meta/llama-4-scout-17b-16e-instruct',
          {
            messages: [
              { role: 'system', content: SYSTEM_PROMPT },
              { role: 'user', content: userText },
            ],
            stream: false,
            max_tokens: 500,
          }
        );
        llmResponse = (llmResult as any).response || '';
      } catch (err) {
        console.error('LLM error:', err);
        this.sendJson({ type: 'llm', emotion: 'sad', text: '唔好意思，暫時答唔到你，請再試一次。' });
        return;
      }
    }

    if (!llmResponse.trim()) {
      this.sendJson({ type: 'llm', emotion: 'neutral', text: '我諗唔到點答，不如你問過第二樣？' });
      return;
    }

    // Send LLM response text to device
    this.sendJson({ type: 'llm', emotion: 'happy', text: llmResponse });

    // 3. TTS — Workers AI Aura-1
    await this.synthesizeSpeech(llmResponse);
  }

  /** Call Alibaba Cloud Bailian DashScope Qwen model (OpenAI-compatible API) */
  private async callQwen(userText: string): Promise<string> {
    const response = await fetch(
      'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.env.QWEN_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: this.env.QWEN_MODEL || 'qwen-plus',
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user', content: userText },
          ],
          max_tokens: 500,
          temperature: 0.7,
        }),
      }
    );

    if (!response.ok) {
      console.error(`Qwen HTTP ${response.status}: ${await response.text()}`);
      return '';
    }

    const data = await response.json() as any;
    return data.choices?.[0]?.message?.content || '';
  }

  private async synthesizeSpeech(text: string) {
    try {
      this.state = 'speaking';
      this.sendJson({ type: 'tts', state: 'start' });

      const ttsResult = await this.env.AI.run(
        this.env.TTS_MODEL || '@cf/deepgram/aura-1',
        {
          text,
          // Aura-1: try different speakers
          // Options: aura-asteria-en, aura-luna-en, aura-stella-en, etc.
          // For Chinese/Cantonese support, may need fallback
          encoding: 'linear16',
          container: 'wav',
          sample_rate: DOWNLINK_RATE,
        }
      );

      // TTS returns a ReadableStream or base64 WAV bytes
      let wavBytes: Uint8Array;

      if (ttsResult instanceof ReadableStream) {
        const reader = ttsResult.getReader();
        const chunks: Uint8Array[] = [];
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
        }
        const totalLen = chunks.reduce((s, c) => s + c.length, 0);
        wavBytes = new Uint8Array(totalLen);
        let off = 0;
        for (const c of chunks) { wavBytes.set(c, off); off += c.length; }
      } else if (ttsResult instanceof Uint8Array) {
        wavBytes = ttsResult;
      } else {
        // Base64 string or other format
        const base64 = (ttsResult as any).audio || (ttsResult as any).data || '';
        if (base64) {
          const binaryStr = atob(base64);
          wavBytes = new Uint8Array(binaryStr.length);
          for (let i = 0; i < binaryStr.length; i++)
            wavBytes[i] = binaryStr.charCodeAt(i);
        } else {
          throw new Error('Unknown TTS response format');
        }
      }

      // Parse WAV → PCM samples, then Opus-encode
      // Skip WAV header (44 bytes typically)
      const pcmStart = this.findWavDataOffset(wavBytes);
      const pcmBytes = wavBytes.slice(pcmStart);
      const pcm16 = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, pcmBytes.length / 2);

      // Encode PCM → Opus frames (60ms each)
      await this.sendOpusFrames(pcm16);

      this.sendJson({ type: 'tts', state: 'stop' });
      this.state = 'idle';
      console.log(`TTS complete: ${pcm16.length} samples`);
    } catch (err) {
      console.error('TTS error:', err);
      this.sendJson({ type: 'tts', state: 'stop' });
      this.state = 'idle';
      // TTS failed but LLM text was already sent — device can display text
    }
  }

  // ── Helpers ──

  private findWavDataOffset(wav: Uint8Array): number {
    // Find 'data' chunk in WAV
    for (let i = 0; i < wav.length - 8; i++) {
      if (wav[i] === 0x64 && wav[i+1] === 0x61 &&
          wav[i+2] === 0x74 && wav[i+3] === 0x61) {
        return i + 8; // Skip 'data' + 4-byte size
      }
    }
    return 44; // Default WAV header size
  }

  private async sendOpusFrames(pcm: Int16Array) {
    // Send PCM as binary frames (type=1 for raw PCM, no Opus encoding needed server-side)
    // ESP32 will play PCM directly via I2S DAC
    const CHUNK_SIZE = 1024; // 1024 samples per chunk (~64ms @ 16kHz)
    let pos = 0;

    while (pos < pcm.length) {
      const end = Math.min(pos + CHUNK_SIZE, pcm.length);
      const chunk = pcm.slice(pos, end);
      const payload = new Uint8Array(chunk.length * 2);
      const view = new DataView(payload.buffer);
      for (let i = 0; i < chunk.length; i++) {
        view.setInt16(i * 2, chunk[i], true); // little-endian (ESP32 native)
      }

      // Binary header: type=1 (PCM), reserved=0, payload_size=BE
      const header = new Uint8Array(4);
      header[0] = 1;                           // type = PCM
      header[1] = 0;                           // reserved
      header[2] = (payload.length >> 8) & 0xFF;
      header[3] = payload.length & 0xFF;

      const frame = new Uint8Array(4 + payload.length);
      frame.set(header, 0);
      frame.set(payload, 4);

      if (this.ws) {
        try {
          this.ws.send(frame.buffer);
        } catch (err) {
          console.error('PCM send error:', err);
          break;
        }
      }

      pos = end;

      // Small delay to avoid overwhelming ESP32 buffer
      if (pos < pcm.length) {
        await new Promise(r => setTimeout(r, 5));
      }
    }

    console.log(`Sent ${Math.ceil(pcm.length / CHUNK_SIZE)} PCM chunks, ${pcm.length} samples total`);
  }

  private sendJson(msg: ServerMessage) {
    if (!this.ws) return;
    try {
      this.ws.send(JSON.stringify(msg));
    } catch (err) {
      console.error('WS send error:', err);
    }
  }
}
