/**
 * FunConnect AI helpers — Workers AI integration utilities
 */

export interface SttResult {
  text: string;
  language?: string;
  confidence?: number;
}

export interface LlmResult {
  text: string;
  emotion: string;
}

export interface TtsResult {
  audio: Uint8Array;
  sampleRate: number;
}

/**
 * Determine emotion from LLM response text.
 * Simple keyword-based classification.
 */
export function classifyEmotion(text: string): string {
  const t = text.toLowerCase();
  if (t.includes('?') || t.includes('?') || t.includes('how') || t.includes('點樣'))
    return 'thinking';
  if (t.includes('!') || t.includes('好') || t.includes('great') || t.includes('good'))
    return 'happy';
  if (t.includes('sorry') || t.includes('唔好意思') || t.includes('對唔住'))
    return 'sad';
  if (t.includes('wow') || t.includes('嘩') || t.includes('interesting'))
    return 'surprised';
  return 'neutral';
}

/**
 * Build a Cantonese RAG prompt with optional context.
 */
export function buildRagPrompt(
  query: string,
  context?: string,
  grade?: string
): string {
  const gradeHint = grade ? `適合${grade}程度` : '適合中小學生理解';

  let prompt = `你係「小芳」，香港中小學AI助教，係FunConnect AIOT平台嘅一部分。
請遵守以下規則：
- 用粵語（廣東話）同繁體中文回答
- 語氣友善、有耐心，${gradeHint}
- 只回答學術、學校、知識相關問題
- 如果問題唔適合學生，請婉轉拒絕
- 回答盡量簡潔，唔好太長
`;

  if (context) {
    prompt += `
【參考資料】
${context}

請根據以上參考資料回答學生問題。如果資料不足，請誠實說明。
`;
  }

  prompt += `
【學生問題】
${query}
`;

  return prompt;
}

/**
 * Vectorize search helper (requires Vectorize binding).
 * Placeholder — activate when Vectorize index is created.
 */
export async function searchRagKnowledge(
  _query: string,
  _ai: Ai,
  _vectorize?: any
): Promise<string | null> {
  // TODO: Implement when Vectorize index is ready
  // 1. Embed query: ai.run('@cf/baai/bge-base-zh', { text: query })
  // 2. Search: vectorize.query(embedding, { topK: 3 })
  // 3. Return concatenated context
  return null;
}

/**
 * Content safety filter for student queries.
 * Returns true if the query is safe for school use.
 */
export function isSafeForSchool(text: string): boolean {
  const blockedPatterns = [
    /\b(violence|weapon|kill|murder|sex|porn|drug|gambling|suicide)\b/i,
    /暴力|武器|殺|色情|毒品|賭|自殺|自殘|性/,
    /\b(hack|crack|exploit|cheat code)\b/i,
    /黑客|破解|外掛/,
  ];

  for (const pattern of blockedPatterns) {
    if (pattern.test(text)) return false;
  }
  return true;
}
