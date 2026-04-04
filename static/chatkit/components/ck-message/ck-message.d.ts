import { CkBase } from '../../lib/ck-base.js';
export declare class CkMessage extends CkBase {
    #private;
    static properties: {
        role: {
            type: StringConstructor;
            reflect: boolean;
        };
    };
    static styles: CSSStyleSheet[];
    /** The message role: "user", "assistant", or "error". */
    role: string;
    /** Start streaming mode — subsequent appendText() calls render incrementally. */
    startStreaming(): void;
    /** Append a chunk of streaming text (for assistant messages). */
    appendText(chunk: string): void;
    /** End streaming and finalize the message content. */
    endStreaming(): void;
    /** Set full message content (for loading history, not streaming). */
    setContent(content: string): void;
    /** Append a collapsible code block to the message. */
    appendCodeBlock(code: string, label?: string): void;
    protected update(): void;
}
//# sourceMappingURL=ck-message.d.ts.map