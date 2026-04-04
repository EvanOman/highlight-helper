/**
 * SSE event types for the chatkit protocol.
 * Mirrors the Python ChatEventType StrEnum.
 */
export declare const EventType: {
    readonly INIT: "init";
    readonly TEXT: "text";
    readonly STATUS: "status";
    readonly CODE: "code";
    readonly TOOL_USE: "tool_use";
    readonly TOOL_DONE: "tool_done";
    readonly ARTIFACT: "artifact";
    readonly ERROR: "error";
    readonly DONE: "done";
};
export type EventTypeName = (typeof EventType)[keyof typeof EventType];
/** A parsed SSE event from the stream. */
export interface SSEEvent {
    /** The event type (e.g., "text", "init", "done"). Defaults to "message". */
    readonly event: string;
    /** The event data payload. */
    readonly data: string;
    /** The event ID, if provided by the server. */
    readonly id: string | null;
}
//# sourceMappingURL=event-types.d.ts.map