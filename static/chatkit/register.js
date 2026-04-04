import { CkApp, CkSidebar, CkMessage, CkMessages, CkInput, CkToolCard, CkArtifact } from "./index.js";
const components = [
  { tag: "ck-app", cls: CkApp },
  { tag: "ck-sidebar", cls: CkSidebar },
  { tag: "ck-message", cls: CkMessage },
  { tag: "ck-messages", cls: CkMessages },
  { tag: "ck-input", cls: CkInput },
  { tag: "ck-tool-card", cls: CkToolCard },
  { tag: "ck-artifact", cls: CkArtifact }
];
for (const { tag, cls } of components) {
  if (!customElements.get(tag)) {
    customElements.define(tag, cls);
  }
}
//# sourceMappingURL=register.js.map
