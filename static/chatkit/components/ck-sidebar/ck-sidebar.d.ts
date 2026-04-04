import { CkBase } from '../../lib/ck-base.js';
export interface ThreadItem {
    id: string;
    title: string;
    updated_at: string;
}
export declare class CkSidebar extends CkBase {
    #private;
    static properties: {
        activeThreadId: {
            type: StringConstructor;
            attribute: string;
        };
        open: {
            type: BooleanConstructor;
            reflect: boolean;
        };
    };
    static styles: CSSStyleSheet[];
    activeThreadId: string | null;
    open: boolean;
    /** Replace the displayed thread list. */
    setThreads(threads: ThreadItem[]): void;
    /** Open the sidebar drawer (mobile). */
    show(): void;
    /** Close the sidebar drawer (mobile). */
    close(): void;
    protected update(): void;
}
//# sourceMappingURL=ck-sidebar.d.ts.map