import { CkBase } from '../../lib/ck-base.js';
export declare class CkInput extends CkBase {
    #private;
    static properties: {
        streaming: {
            type: BooleanConstructor;
            reflect: boolean;
        };
        disabled: {
            type: BooleanConstructor;
            reflect: boolean;
        };
        placeholder: {
            type: StringConstructor;
        };
    };
    static styles: CSSStyleSheet[];
    streaming: boolean;
    disabled: boolean;
    placeholder: string;
    /** Focus the input field. */
    focusInput(): void;
    protected update(): void;
}
//# sourceMappingURL=ck-input.d.ts.map