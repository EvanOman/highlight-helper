import { CkBase } from '../../lib/ck-base.js';
export type OnBeforeFetchCallback = ((info: {
    url: string;
    origin: string;
}) => Record<string, string> | Promise<Record<string, string>>) | null;
export declare class CkApp extends CkBase {
    #private;
    static properties: {
        apiBase: {
            type: StringConstructor;
            attribute: string;
        };
        theme: {
            type: StringConstructor;
            attribute: string;
            reflect: boolean;
        };
    };
    static styles: CSSStyleSheet[];
    apiBase: string;
    theme: string;
    /** Optional callback to inject custom headers before each fetch. */
    onBeforeFetch: OnBeforeFetchCallback;
    constructor();
    /** The current thread ID, if any. */
    get threadId(): string | null;
    connectedCallback(): void;
    disconnectedCallback(): void;
    /** Toggle between light and dark themes. */
    toggleTheme(): void;
    /** Set the theme explicitly. */
    setTheme(theme: "dark" | "light"): void;
    /** Load the thread list into the sidebar. */
    loadThreads(): Promise<void>;
    /** Load a specific thread's messages. */
    loadThread(id: string): Promise<void>;
    /** Delete a thread. */
    deleteThread(id: string): Promise<void>;
    /** Start a new chat — clear messages and thread ID. */
    newChat(): void;
    protected update(): void;
}
//# sourceMappingURL=ck-app.d.ts.map