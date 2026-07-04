import { CkBase } from '../../lib/ck-base.js';
export declare class CkMessages extends CkBase {
    #private;
    static styles: CSSStyleSheet[];
    /** Get or create the current assistant turn container. */
    getOrCreateTurn(): HTMLDivElement;
    /** Reset the current turn (call after "done" event). */
    resetTurn(): void;
    /** Add a child element to the current turn as a new phase. */
    addTurnPhase(element: HTMLElement): void;
    /** Find a rendered element by selector. Content lives in the shadow root,
     * so external `querySelector` calls cannot reach it — use this instead. */
    findRendered<T extends Element>(selector: string): T | null;
    /** Add a standalone element outside of turns (e.g., user messages). */
    addMessage(element: HTMLElement): void;
    /** Show a status message with pulsing dots. */
    showStatus(message: string): void;
    /** Remove the status indicator. */
    hideStatus(): void;
    /** Clear all messages and show empty state. */
    clear(): void;
    /** Schedule a scroll-to-bottom on next animation frame. */
    scheduleScroll(): void;
    protected update(): void;
}
//# sourceMappingURL=ck-messages.d.ts.map