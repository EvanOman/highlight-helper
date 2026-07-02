// Re-export chatkit symbols so chat.js can use a relative import
// instead of a template-interpolated absolute path.
export { connectSSE, EventType } from '../chatkit/index.js';
