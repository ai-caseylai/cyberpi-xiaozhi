/** xiaozhi-esp32 WebSocket protocol types */

export const PROTOCOL_VERSION = 3;
export const FRAME_DURATION_MS = 60;

// ── JSON messages ──

export interface HelloRequest {
  type: 'hello';
  version: number;
  transport: 'websocket';
  features?: { mcp?: boolean; aec?: boolean };
  audio_params: AudioParams;
}

export interface HelloResponse {
  type: 'hello';
  transport: 'websocket';
  session_id: string;
  audio_params: AudioParams;
}

export interface ListenMessage {
  type: 'listen';
  state: 'start' | 'stop' | 'detect';
  mode?: 'auto' | 'manual' | 'realtime';
  text?: string;
}

export interface SttMessage {
  type: 'stt';
  text: string;
}

export interface LlmMessage {
  type: 'llm';
  emotion: string;
  text: string;
}

export interface TtsMessage {
  type: 'tts';
  state: 'start' | 'stop' | 'sentence_start';
  text?: string;
}

export interface AbortMessage {
  type: 'abort';
  reason: string;
}

export interface AlertMessage {
  type: 'alert';
  status: string;
  message: string;
  emotion: string;
}

export interface SystemMessage {
  type: 'system';
  command: string;
}

export type ServerMessage =
  | HelloResponse
  | SttMessage
  | LlmMessage
  | TtsMessage
  | AlertMessage
  | SystemMessage;

// ── Audio params ──

export interface AudioParams {
  format: 'opus' | 'pcm';
  sample_rate: number;
  channels: number;
  frame_duration: number;
}

// ── Binary protocol v3 header ──

export function buildBinaryHeader(payloadSize: number): Uint8Array {
  const header = new Uint8Array(4);
  header[0] = 0;                          // type = audio
  header[1] = 0;                          // reserved
  header[2] = (payloadSize >> 8) & 0xFF;  // payload_size BE
  header[3] = payloadSize & 0xFF;
  return header;
}

export function parseBinaryHeader(data: Uint8Array): {
  type: number;
  payloadSize: number;
} {
  return {
    type: data[0],
    payloadSize: (data[2] << 8) | data[3],
  };
}

// ── Frame helpers ──

export function frameSamples(sampleRate: number): number {
  return sampleRate * FRAME_DURATION_MS / 1000;
}
