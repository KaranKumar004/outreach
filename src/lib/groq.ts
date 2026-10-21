import OpenAI from 'openai';

const groqApiKey = process.env.GROQ_API_KEY;

if (!groqApiKey) {
  // We'll throw an error when attempting to use the client rather than on import,
  // in case the build step doesn't have the API key but doesn't run execution paths.
  console.warn('Warning: GROQ_API_KEY is not defined in environment variables.');
}

export const groq = new OpenAI({
  baseURL: 'https://api.groq.com/openai/v1',
  apiKey: groqApiKey || 'dummy-key',
});

export const GROQ_MODEL = 'llama-3.3-70b-versatile';
