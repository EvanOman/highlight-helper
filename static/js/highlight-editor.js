/**
 * Highlight Editor - Word-level selection UI for adjusting extracted highlights.
 *
 * Reads window.__highlightData = { fullText, highlightStart, highlightEnd }
 * Renders words as spans, highlights the selected range, and provides
 * draggable handles to adjust the selection boundaries.
 */
(function () {
  "use strict";

  const data = window.__highlightData;
  if (!data || !data.fullText) return;

  const container = document.getElementById("highlight-editor");
  const hiddenInput = document.getElementById("highlight-text-input");
  if (!container || !hiddenInput) return;

  // Split full text into words, preserving whitespace info
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

  // Determine initial selected word range from character offsets
  let selStart = 0;
  let selEnd = words.length - 1;

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

  // Apply initial highlight (CSS classes only, not positioning)
  wordSpans.forEach(function (span, idx) {
    if (idx >= selStart && idx <= selEnd) {
      span.classList.add("highlighted");
    } else {
      span.classList.remove("highlighted");
    }
  });

  // Update hidden input with selected text
  var selectedWords = words.slice(selStart, selEnd + 1).map(function (w) {
    return w.text;
  });
  hiddenInput.value = selectedWords.join(" ");

  // Position handles AFTER browser completes layout
  requestAnimationFrame(positionHandles);

  function createHandle(type) {
    const handle = document.createElement("div");
    handle.className = "highlight-handle highlight-handle-" + type;
    handle.innerHTML = '<div class="handle-grip"></div><div class="handle-line"></div>';
    handle.dataset.handleType = type;
    return handle;
  }

  function updateHighlight() {
    wordSpans.forEach(function (span, idx) {
      if (idx >= selStart && idx <= selEnd) {
        span.classList.add("highlighted");
      } else {
        span.classList.remove("highlighted");
      }
    });

    // Update hidden input with selected text
    const selectedWords = words.slice(selStart, selEnd + 1).map(function (w) {
      return w.text;
    });
    hiddenInput.value = selectedWords.join(" ");

    // Position handles
    positionHandles();
  }

  function positionHandles() {
    if (wordSpans.length === 0) return;

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
      // If click is before midpoint of selection, adjust start; otherwise adjust end
      var mid = (selStart + selEnd) / 2;
      if (idx <= mid) {
        selStart = idx;
      } else {
        selEnd = idx;
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
     * Get current selection bounds (word indices)
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
  };
})();
