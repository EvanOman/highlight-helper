import { CkBase } from '../../lib/ck-base.js';
export interface ArtifactTab {
    label: string;
    content: string;
    type?: "html" | "code" | "table" | "text";
}
export interface ArtifactData {
    id?: string;
    type?: string;
    data?: unknown;
    code?: string;
    error?: string;
    result_json?: string;
    result_type?: string;
}
export declare class CkArtifact extends CkBase {
    #private;
    static styles: CSSStyleSheet[];
    /** Set the artifact data and auto-generate tabs. */
    setData(data: ArtifactData): void;
    protected update(): void;
}
//# sourceMappingURL=ck-artifact.d.ts.map