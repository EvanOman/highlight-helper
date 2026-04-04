/**
 * Chatkit — Reusable Web Components chat UI with SSE streaming.
 *
 * This is the barrel export. Import classes here; use register.ts for auto-registration.
 */
export { CkBase } from './lib/ck-base.js';
export type { PropertyDeclaration, PropertyDeclarationMap } from './lib/ck-base.js';
export { StreamStateMachine, StreamState } from './lib/stream-state.js';
export type { StreamStateName, FinalizeReason, StreamStateCallbacks } from './lib/stream-state.js';
export { connectSSE, EventType } from './sse/sse-client.js';
export type { SSEConnection, SSEOptions, SSEEvent, EventTypeName } from './sse/sse-client.js';
export { CkApp } from './components/ck-app/ck-app.js';
export type { OnBeforeFetchCallback } from './components/ck-app/ck-app.js';
export { CkSidebar } from './components/ck-sidebar/ck-sidebar.js';
export { CkMessage } from './components/ck-message/ck-message.js';
export { CkMessages } from './components/ck-messages/ck-messages.js';
export { CkInput } from './components/ck-input/ck-input.js';
export { CkToolCard } from './components/ck-tool-card/ck-tool-card.js';
export { CkArtifact } from './components/ck-artifact/ck-artifact.js';
export type { ArtifactData, ArtifactTab } from './components/ck-artifact/ck-artifact.js';
export { resetSheet, animationsSheet, markdownSheet } from './theme/shared-styles.js';
//# sourceMappingURL=index.d.ts.map