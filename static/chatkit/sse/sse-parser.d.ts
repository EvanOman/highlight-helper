import { SSEEvent } from './event-types.js';
/**
 * Parse an SSE text stream into individual events.
 * Yields SSEEvent objects as complete events are received.
 *
 * @param stream - A ReadableStream of decoded text chunks.
 */
export declare function parseSSEStream(stream: ReadableStream<string>): AsyncGenerator<SSEEvent>;
//# sourceMappingURL=sse-parser.d.ts.map