/**
 * Highlight Editor - Word-level selection UI for adjusting extracted highlights.
 *
 * Reads window.__highlightData = { fullText, highlightStart, highlightEnd, matchStatus }
 * Renders words as spans, highlights the selected range, and provides
 * draggable handles to adjust the selection boundaries.
 *
 * When matchStatus is "failed" (the extractor couldn't locate the highlighted
 * passage in the page text), nothing is pre-selected: the user must tap the
 * first and last word of the passage, and Save stays disabled until they do.
 */
(function () {
  "use strict";

  const data = window.__highlightData;
  if (!data || !data.fullText) return;

  const container = document.getElementById("highlight-editor");
  const hiddenInput = document.getElementById("highlight-text-input");
  if (!container || !hiddenInput) return;

  const saveButton = document.getElementById("save-highlight-btn");
  const matchStatus = data.matchStatus || "exact";

  /**
   * Build the saved highlight from the exact character-offset slice of the
   * full text (never a word join, which would reflow spacing), then apply one
   * deterministic cleanup rule:
   *   1. Rejoin hyphenated line breaks ("beau-\ntiful" -> "beautiful") when
   *      the continuation starts with a lowercase letter.
   *   2. Collapse each line-break whitespace run to a single space.
   */
  function sliceHighlightText(fullText, charStart, charEnd) {
    var raw = fullText.slice(charStart, charEnd);
    var rejoined = raw.replace(/([A-Za-z])-[ \t]*\r?\n[ \t]*([a-z])/g, "$1$2");
    return rejoined.replace(/[ \t]*(?:\r?\n[ \t]*)+/g, " ").trim();
  }

  // Split full text into words, preserving character offsets
  const words = [];
  const regex = /(\S+)/g;
  let match;
  while ((match = regex.exec(data.fullText)) !== null) {
    words.push({
      text: match[1],
      start: match.index,
      end: match.index + match[1].length,
    });
  }

  if (words.length === 0) return;

  // Selection state: null indices mean "no selection yet" (failed match).
  let selStart = null;
  let selEnd = null;

  if (matchStatus !== "failed") {
    // Determine initial selected word range from character offsets
    selStart = 0;
    selEnd = words.length - 1;
    for (let i = 0; i < words.length; i++) {
      if (words[i].end > data.highlightStart) {
        selStart = i;
        break;
      }
    }
    for (let i = words.length - 1; i >= 0; i--) {
      if (words[i].start < data.highlightEnd) {
        selEnd = i;
        break;
      }
    }
  }

  function hasSelection() {
    return selStart !== null && selEnd !== null;
  }

  // Build word spans
  const wordSpans = [];
  words.forEach(function (w, idx) {
    const span = document.createElement("span");
    span.textContent = w.text + " ";
    span.dataset.wordIdx = idx;
    span.className = "highlight-word";
    container.appendChild(span);
    wordSpans.push(span);
  });

  // Create handles
  const startHandle = createHandle("start");
  const endHandle = createHandle("end");
  container.style.position = "relative";
  container.appendChild(startHandle);
  container.appendChild(endHandle);

  // Apply initial state (highlight classes, hidden input, save gating)
  syncSelectionState();

  // Position handles AFTER browser completes layout
  requestAnimationFrame(positionHandles);

  function createHandle(type) {
    const handle = document.createElement("div");
    handle.className = "highlight-handle highlight-handle-" + type;
    handle.innerHTML = '<div class="handle-grip"></div><div class="handle-line"></div>';
    handle.dataset.handleType = type;
    return handle;
  }

  function syncSelectionState() {
    wordSpans.forEach(function (span, idx) {
      if (hasSelection() && idx >= selStart && idx <= selEnd) {
        span.classList.add("highlighted");
      } else {
        span.classList.remove("highlighted");
      }
    });

    // Saved text = exact char-offset slice of full_text, cleaned up.
    if (hasSelection()) {
      hiddenInput.value = sliceHighlightText(
        data.fullText,
        words[selStart].start,
        words[selEnd].end
      );
    } else {
      hiddenInput.value = "";
    }

    if (saveButton) {
      saveButton.disabled = !hiddenInput.value.trim();
    }
  }

  function updateHighlight() {
    syncSelectionState();
    positionHandles();
  }

  function positionHandles() {
    if (!hasSelection()) {
      startHandle.style.display = "none";
      endHandle.style.display = "none";
      return;
    }
    startHandle.style.display = "";
    endHandle.style.display = "";

    const startSpan = wordSpans[selStart];
    const endSpan = wordSpans[selEnd];
    if (!startSpan || !endSpan) return;

    const containerRect = container.getBoundingClientRect();
    const startRect = startSpan.getBoundingClientRect();
    const endRect = endSpan.getBoundingClientRect();

    // Check if rects are valid (non-zero), retry if layout not ready
    if (startRect.height === 0 || containerRect.width === 0) {
      requestAnimationFrame(positionHandles);
      return;
    }

    // Start handle: left edge of first selected word
    startHandle.style.left = (startRect.left - containerRect.left - 6) + "px";
    startHandle.style.top = (startRect.top - containerRect.top) + "px";
    startHandle.style.height = startRect.height + "px";

    // End handle: right edge of last selected word
    endHandle.style.left = (endRect.right - containerRect.left - 6) + "px";
    endHandle.style.top = (endRect.top - containerRect.top) + "px";
    endHandle.style.height = endRect.height + "px";
  }

  // Drag state
  let activeHandle = null;

  // Touch events
  startHandle.addEventListener("touchstart", onTouchStart, { passive: false });
  endHandle.addEventListener("touchstart", onTouchStart, { passive: false });
  document.addEventListener("touchmove", onTouchMove, { passive: false });
  document.addEventListener("touchend", onTouchEnd);

  // Mouse events
  startHandle.addEventListener("mousedown", onMouseDown);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);

  function onTouchStart(e) {
    e.preventDefault();
    activeHandle = e.currentTarget.dataset.handleType;
    e.currentTarget.classList.add("active");
  }

  function onTouchMove(e) {
    if (!activeHandle) return;
    e.preventDefault();
    var touch = e.touches[0];
    // Offset Y by 30px upward so the finger doesn't obscure the word
    var wordIdx = getWordAtPoint(touch.clientX, touch.clientY - 30);
    if (wordIdx !== null) {
      applyDrag(wordIdx);
    }
  }

  function onTouchEnd() {
    if (activeHandle) {
      startHandle.classList.remove("active");
      endHandle.classList.remove("active");
      activeHandle = null;
    }
  }

  function onMouseDown(e) {
    e.preventDefault();
    activeHandle = e.currentTarget.dataset.handleType;
    e.currentTarget.classList.add("active");
  }

  function onMouseMove(e) {
    if (!activeHandle) return;
    var wordIdx = getWordAtPoint(e.clientX, e.clientY);
    if (wordIdx !== null) {
      applyDrag(wordIdx);
    }
  }

  function onMouseUp() {
    if (activeHandle) {
      startHandle.classList.remove("active");
      endHandle.classList.remove("active");
      activeHandle = null;
    }
  }

  function getWordAtPoint(x, y) {
    // Try elementFromPoint first
    var el = document.elementFromPoint(x, y);
    if (el && el.dataset && el.dataset.wordIdx !== undefined) {
      return parseInt(el.dataset.wordIdx, 10);
    }

    // Fallback: find nearest word by bounding rect
    var minDist = Infinity;
    var nearest = null;
    for (var i = 0; i < wordSpans.length; i++) {
      var rect = wordSpans[i].getBoundingClientRect();
      var cx = (rect.left + rect.right) / 2;
      var cy = (rect.top + rect.bottom) / 2;
      var dist = Math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy));
      if (dist < minDist) {
        minDist = dist;
        nearest = i;
      }
    }
    return nearest;
  }

  function applyDrag(wordIdx) {
    if (!hasSelection()) return;
    if (activeHandle === "start") {
      if (wordIdx <= selEnd) {
        selStart = wordIdx;
        updateHighlight();
      }
    } else if (activeHandle === "end") {
      if (wordIdx >= selStart) {
        selEnd = wordIdx;
        updateHighlight();
      }
    }
  }

  // Also allow clicking on words to set selection boundaries
  container.addEventListener("click", function (e) {
    if (activeHandle) return;
    var el = e.target;
    if (el.dataset && el.dataset.wordIdx !== undefined) {
      var idx = parseInt(el.dataset.wordIdx, 10);
      if (!hasSelection()) {
        // Failed match: the first tap seeds the selection at one word.
        selStart = idx;
        selEnd = idx;
      } else {
        // If click is before midpoint of selection, adjust start; otherwise adjust end
        var mid = (selStart + selEnd) / 2;
        if (idx <= mid) {
          selStart = idx;
        } else {
          selEnd = idx;
        }
      }
      updateHighlight();
    }
  });

  // Reposition handles on resize
  window.addEventListener("resize", positionHandles);

  // Expose API for external control (e.g., edit mode toggle)
  window.__highlightEditorAPI = {
    /**
     * Get the words array with character positions
     */
    getWords: function () {
      return words;
    },
    /**
     * Get current selection bounds (word indices); nulls when nothing selected
     */
    getSelection: function () {
      return { selStart: selStart, selEnd: selEnd };
    },
    /**
     * Set selection by word indices and update the UI
     */
    setSelection: function (newStart, newEnd) {
      if (
        newStart >= 0 &&
        newEnd < words.length &&
        newStart <= newEnd
      ) {
        selStart = newStart;
        selEnd = newEnd;
        updateHighlight();
        return true;
      }
      return false;
    },
    /**
     * Set selection by character positions (finds containing words)
     */
    setSelectionByCharPos: function (charStart, charEnd) {
      var newSelStart = 0;
      var newSelEnd = words.length - 1;

      // Find word containing or after charStart
      for (var i = 0; i < words.length; i++) {
        if (words[i].end > charStart) {
          newSelStart = i;
          break;
        }
      }
      // Find word containing or before charEnd
      for (var j = words.length - 1; j >= 0; j--) {
        if (words[j].start < charEnd) {
          newSelEnd = j;
          break;
        }
      }

      if (newSelStart <= newSelEnd) {
        selStart = newSelStart;
        selEnd = newSelEnd;
        updateHighlight();
        return true;
      }
      return false;
    },
    /**
     * Get the full text
     */
    getFullText: function () {
      return data.fullText;
    },
    /**
     * Pure slice+cleanup used to build the saved text (exposed for tests)
     */
    sliceHighlightText: sliceHighlightText,
  };
})();
