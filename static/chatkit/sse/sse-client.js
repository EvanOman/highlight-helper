async function* parseSSEStream(stream) {
  const reader = stream.getReader();
  let tail = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = tail + value.replace(/\r\n|\r/g, "\n");
      const lastBoundary = text.lastIndexOf("\n\n");
      if (lastBoundary === -1) {
        tail = text;
        continue;
      }
      const complete = text.substring(0, lastBoundary);
      tail = text.substring(lastBoundary + 2);
      const rawEvents = complete.split("\n\n");
      for (const raw of rawEvents) {
        if (!raw.trim()) continue;
        const event = parseRawEvent(raw);
        if (event) yield event;
      }
    }
    if (tail.trim()) {
      const event = parseRawEvent(tail);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
function parseRawEvent(raw) {
  const lines = raw.split("\n");
  let event = "message";
  let data = "";
  let id = null;
  let hasData = false;
  for (const line of lines) {
    if (line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      event = line.substring(6).trim();
    } else if (line.startsWith("data:")) {
      if (hasData) data += "\n";
      const raw2 = line.substring(5);
      data += raw2.startsWith(" ") ? raw2.substring(1) : raw2;
      hasData = true;
    } else if (line.startsWith("id:")) {
      id = line.substring(3).trim();
    }
  }
  if (!hasData) return null;
  return { event, data, id };
}
const EventType = {
  INIT: "init",
  TEXT: "text",
  STATUS: "status",
  CODE: "code",
  TOOL_USE: "tool_use",
  TOOL_DONE: "tool_done",
  ARTIFACT: "artifact",
  ERROR: "error",
  DONE: "done"
};
function connectSSE(url, options) {
  const abortController = new AbortController();
  const externalSignal = options?.signal;
  if (externalSignal) {
    if (externalSignal.aborted) {
      abortController.abort(externalSignal.reason);
    } else {
      const onExternalAbort = () => abortController.abort(externalSignal.reason);
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  let iterator = null;
  const done = (async () => {
    const headers = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...options?.headers
    };
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: options?.body != null ? JSON.stringify(options.body) : void 0,
      signal: abortController.signal
    });
    if (!response.ok) {
      throw new Error(
        `SSE request failed: ${response.status} ${response.statusText}`
      );
    }
    if (!response.body) {
      throw new Error("SSE response has no body");
    }
    const textStream = response.body.pipeThrough(new TextDecoderStream());
    iterator = parseSSEStream(textStream);
  })();
  const connection = {
    [Symbol.asyncIterator]() {
      return {
        async next() {
          if (!iterator) {
            await done;
          }
          if (!iterator) {
            return { done: true, value: void 0 };
          }
          return iterator.next();
        },
        async return() {
          abortController.abort();
          return { done: true, value: void 0 };
        },
        [Symbol.asyncIterator]() {
          return this;
        }
      };
    },
    abort() {
      abortController.abort();
    },
    done
  };
  return connection;
}
export {
  EventType,
  connectSSE
};
//# sourceMappingURL=sse-client.js.map
