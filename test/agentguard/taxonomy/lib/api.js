/**
 * @module lib/api
 * @description Unified API helper supporting OpenAI, Anthropic, and Google Gemini.
 * Automatically detects provider from TARGET_MODEL or PROVIDER env var.
 * All attack scripts use this single interface for consistency.
 */

import 'dotenv/config';
import OpenAI from 'openai';
import Anthropic from '@anthropic-ai/sdk';
import { GoogleGenerativeAI } from '@google/generative-ai';

const MODEL = process.env.TARGET_MODEL || 'gpt-4o';
const MAX_TOKENS = parseInt(process.env.MAX_TOKENS || '1024', 10);
const TEMPERATURE = parseFloat(process.env.TEMPERATURE ?? '0');

/**
 * Detect provider from model name or explicit env var
 */
function detectProvider() {
  const explicit = process.env.PROVIDER?.toLowerCase();
  if (explicit) return explicit;
  if (MODEL.startsWith('gpt') || MODEL.startsWith('o1') || MODEL.startsWith('o3')) return 'openai';
  if (MODEL.startsWith('claude')) return 'anthropic';
  if (MODEL.startsWith('gemini')) return 'gemini';
  return 'openai'; // default
}

const PROVIDER = detectProvider();

// Lazy-initialized clients
let _openai, _anthropic, _gemini;

function getOpenAI() {
  if (!_openai) {
    if (!process.env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY not set');
    _openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  }
  return _openai;
}

function getAnthropic() {
  if (!_anthropic) {
    if (!process.env.ANTHROPIC_API_KEY) throw new Error('ANTHROPIC_API_KEY not set');
    _anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  }
  return _anthropic;
}

function getGemini() {
  if (!_gemini) {
    if (!process.env.GEMINI_API_KEY) throw new Error('GEMINI_API_KEY not set');
    _gemini = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
  }
  return _gemini;
}

/**
 * Send a chat completion request to the configured provider.
 *
 * @param {Object} options
 * @param {string} [options.system] - System prompt
 * @param {Array<{role: string, content: string}>} options.messages - Chat messages
 * @param {number} [options.maxTokens] - Override max tokens
 * @param {number} [options.temperature] - Override temperature
 * @returns {Promise<string>} The assistant's response text
 */
export async function chat({ system, messages, maxTokens, temperature }) {
  const temp = temperature ?? TEMPERATURE;
  const max = maxTokens ?? MAX_TOKENS;

  if (PROVIDER === 'openai') {
    const client = getOpenAI();
    const msgs = [];
    if (system) msgs.push({ role: 'system', content: system });
    msgs.push(...messages);
    const res = await client.chat.completions.create({
      model: MODEL,
      messages: msgs,
      max_tokens: max,
      temperature: temp,
    });
    return res.choices[0]?.message?.content || '';
  }

  if (PROVIDER === 'anthropic') {
    const client = getAnthropic();
    const res = await client.messages.create({
      model: MODEL,
      max_tokens: max,
      temperature: temp,
      ...(system ? { system } : {}),
      messages,
    });
    return res.content.map(b => b.text).join('');
  }

  if (PROVIDER === 'gemini') {
    const client = getGemini();
    const model = client.getGenerativeModel({ model: MODEL });
    // Gemini uses a flat prompt; we concatenate messages
    const parts = [];
    if (system) parts.push(`System: ${system}`);
    for (const m of messages) {
      parts.push(`${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`);
    }
    const res = await model.generateContent(parts.join('\n\n'));
    return res.response.text();
  }

  throw new Error(`Unknown provider: ${PROVIDER}`);
}

/**
 * Send a chat with pre-filled assistant prefix (for prefix injection attacks).
 * Only supported on OpenAI and Anthropic.
 *
 * @param {Object} options
 * @param {string} [options.system] - System prompt
 * @param {Array<{role: string, content: string}>} options.messages - Messages including partial assistant turn
 * @returns {Promise<string>} The full assistant response
 */
export async function chatWithPrefix({ system, messages, maxTokens, temperature }) {
  // Same as chat — the caller constructs messages with an assistant turn at the end
  return chat({ system, messages, maxTokens, temperature });
}

/**
 * Get model and provider info for logging
 */
export function getModelInfo() {
  return { model: MODEL, provider: PROVIDER, maxTokens: MAX_TOKENS, temperature: TEMPERATURE };
}

export { PROVIDER, MODEL };
