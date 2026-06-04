/**
 * FunConnect AIOT Platform — Cloudflare Worker Entry Point
 *
 * Routes:
 *   /xiaozhi/v1/       WebSocket upgrade → Durable Object session
 *   /api/health        Health check
 *   /api/schools/:id   REST API (future: teacher dashboard)
 */

export { FunConnectSession } from './durable_object';

export interface Env {
  FUNCONNECT_SESSION: DurableObjectNamespace;
  AI: Ai;
  AUTH_TOKEN: string;
  QWEN_API_KEY: string;
  QWEN_MODEL: string;
  LLM_MODEL: string;
  TTS_MODEL: string;
  STT_MODEL: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === '/api/health') {
      return new Response(JSON.stringify({ status: 'ok', timestamp: Date.now() }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // WebSocket upgrade for xiaozhi-esp32 protocol
    if (url.pathname === '/xiaozhi/v1/') {
      const upgrade = request.headers.get('Upgrade');
      if (upgrade !== 'websocket') {
        return new Response('WebSocket required', { status: 426 });
      }

      // Validate auth token
      const auth = request.headers.get('Authorization');
      if (!auth || auth !== `Bearer ${env.AUTH_TOKEN}`) {
        return new Response('Unauthorized', { status: 401 });
      }

      // Extract device info from headers
      const deviceId = request.headers.get('Device-Id') || 'unknown';
      const protocolVersion = request.headers.get('Protocol-Version') || '3';

      // Create Durable Object for this session
      const sessionId = crypto.randomUUID();
      const doId = env.FUNCONNECT_SESSION.idFromName(sessionId);
      const stub = env.FUNCONNECT_SESSION.get(doId);

      // Forward to DO with device info in headers
      const doRequest = new Request(request.url, {
        headers: {
          ...Object.fromEntries(request.headers),
          'X-Session-Id': sessionId,
          'X-Device-Id': deviceId,
          'X-Protocol-Version': protocolVersion,
        },
      });

      return stub.fetch(doRequest);
    }

    // Fallback
    return new Response('FunConnect AIOT Platform', {
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  },
};
