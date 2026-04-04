import { CkBase } from '../../lib/ck-base.js';
export declare class CkToolCard extends CkBase {
    #private;
    static properties: {
        toolName: {
            type: StringConstructor;
            attribute: string;
        };
        status: {
            type: StringConstructor;
            reflect: boolean;
        };
        summary: {
            type: StringConstructor;
        };
    };
    static styles: CSSStyleSheet[];
    toolName: string;
    status: string;
    summary: string;
    protected update(): void;
}
//# sourceMappingURL=ck-tool-card.d.ts.map