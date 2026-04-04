import { SSEEvent } from './event-types.js';
export type { SSEEvent };
export { EventType } from './event-types.js';
export type { EventTypeName } from './event-types.js';
export interface SSEOptions {
    /** POST body — JSON-serialized and sent as application/json. */
    body?: unknown;
    /** Custom headers to include in the request. */
    headers?: Record<string, string>;
    /** AbortSignal for external cancellation (e.g., from an AbortController). */
    signal?: AbortSignal;
}
export interface SSEConnection {
    /** Async iterable of parsed SSE events. */
    [Symbol.asyncIterator](): AsyncIterableIterator<SSEEvent>;
    /** Abort the connection immediately. */
    abort(): void;
    /** Promise that resolves when the stream ends or rejects on fatal error. */
    readonly done: Promise<void>;
}
/**
 * Connect to an SSE endpoint via POST and return an async iterable of events.
 *
 * @example
 * ```ts
 * const sse = connectSSE('/api/chat', {
 *   body: { thread_id: null, message: 'Hello', metadata: {} },
 *   signal: controller.signal,
 * });
 *
 * try {
 *   for await (const event of sse) {
 *     if (event.event === 'text') appendText(event.data);
 *     if (event.event === 'done') break;
 *   }
 * } catch (err) {
 *   if (err.name !== 'AbortError') showError(err);
 * }
 * ```
 */
export declare function connectSSE(url: string, options?: SSEOptions): SSEConnection;
//# sourceMappingURL=sse-client.d.ts.map