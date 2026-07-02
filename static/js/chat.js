import { connectSSE, EventType } from './chatkit-proxy.js';

const cfg = window.CHAT_CONFIG;

const ckApp = document.getElementById('ck-app');
const sidebar = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');
const threadList = document.getElementById('thread-list');
const modelSelect = document.getElementById('model-select');
const chatHeaderTitle = document.getElementById('chat-header-title');
const coachingBanner = document.getElementById('coaching-banner');

const bookId = cfg.bookId;
let currentCoachingCardId = null;

// -- Sidebar controls -------------------------------------------------------

function openSidebar() {
    sidebar.classList.remove('-translate-x-full');
    sidebar.classList.add('translate-x-0');
    sidebarBackdrop.classList.remove('hidden');
}

function closeSidebar() {
    sidebar.classList.add('-translate-x-full');
    sidebar.classList.remove('translate-x-0');
    sidebarBackdrop.classList.add('hidden');
}

document.getElementById('sidebar-toggle').addEventListener('click', () => {
    if (sidebar.classList.contains('-translate-x-full')) {
        openSidebar();
    } else {
        closeSidebar();
    }
});

sidebarBackdrop.addEventListener('click', closeSidebar);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSidebar(); });

// -- Model picker ------------------------------------------------------------

modelSelect.addEventListener('change', async () => {
    try {
        await fetch(`${cfg.basePath}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_model: modelSelect.value }),
        });
    } catch (error) {
        console.error('Error changing model:', error);
    }
});

// -- Inject book_id into chatkit metadata via ck-before-send -----------------

ckApp.addEventListener('ck-before-send', (e) => {
    if (bookId) {
        e.detail.metadata.book_id = bookId;
    }
});

// -- Sidebar thread management -----------------------------------------------

function setActiveThread(threadId) {
    document.querySelectorAll('.thread-item').forEach(item => {
        const isActive = item.dataset.threadId === String(threadId);
        if (isActive) {
            item.classList.add('bg-gray-200', 'dark:bg-gray-800', 'font-medium');
            item.classList.remove('hover:bg-gray-200', 'dark:hover:bg-gray-800');
        } else {
            item.classList.remove('bg-gray-200', 'dark:bg-gray-800', 'font-medium');
            item.classList.add('hover:bg-gray-200', 'dark:hover:bg-gray-800');
        }
    });
}

function addThreadItem(threadId, title, isCoaching = false) {
    if (document.querySelector(`.thread-item[data-thread-id="${threadId}"]`)) return;

    // Remove empty state if present
    const emptyEl = document.getElementById('thread-list-empty');
    if (emptyEl) emptyEl.remove();

    const item = document.createElement('div');
    item.className = 'thread-item group flex items-center gap-1 px-3 py-2 text-sm rounded-lg cursor-pointer text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800 transition';
    item.dataset.threadId = String(threadId);
    item.dataset.coaching = isCoaching ? 'true' : 'false';
    item.title = title;

    if (isCoaching) {
        const icon = document.createElement('span');
        icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 shrink-0 text-amber-500" viewBox="0 0 20 20" fill="currentColor"><path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z"/></svg>';
        icon.className = 'flex shrink-0';
        item.appendChild(icon);
    }

    const span = document.createElement('span');
    span.className = 'flex-1 truncate';
    span.textContent = title;

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-btn opacity-0 group-hover:opacity-100 shrink-0 p-1 rounded hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition';
    deleteBtn.title = 'Delete thread';
    deleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>';
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteThread(threadId);
    });

    item.appendChild(span);
    item.appendChild(deleteBtn);
    item.addEventListener('click', () => loadThread(item.dataset.threadId));

    threadList.prepend(item);
}

async function deleteThread(threadId) {
    if (!confirm('Delete this thread?')) return;

    try {
        const response = await fetch(`${cfg.basePath}/api/chat/conversations/${threadId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete thread');

        const item = document.querySelector(`.thread-item[data-thread-id="${threadId}"]`);
        if (item) item.remove();

        if (ckApp.threadId === String(threadId)) {
            currentCoachingCardId = null;
            ckApp.newChat();
            updateChatHeader(false);
            coachingBanner.innerHTML = '';
        }
    } catch (error) {
        console.error('Error deleting thread:', error);
    }
}

// -- Coaching UI helpers -----------------------------------------------------

function updateChatHeader(isCoaching) {
    if (isCoaching) {
        chatHeaderTitle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-amber-500" viewBox="0 0 20 20" fill="currentColor"><path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z"/></svg><span>Coaching Session</span><span class="px-1.5 py-0.5 text-xs font-medium rounded-full bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300">coaching</span>';
    } else {
        chatHeaderTitle.textContent = 'Chat with Your Highlights';
    }
}

function renderCoachingBanner(title, body) {
    coachingBanner.innerHTML = '';
    const block = document.createElement('div');
    block.className = 'mx-4 mt-3 rounded-xl border-2 border-amber-300 dark:border-amber-700 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-950/30 dark:to-orange-950/30 p-4';

    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-1.5';
    header.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-amber-500" viewBox="0 0 20 20" fill="currentColor"><path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z"/></svg>';
    const label = document.createElement('span');
    label.className = 'text-xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400';
    label.textContent = 'Reading Coach';
    header.appendChild(label);
    block.appendChild(header);

    const titleEl = document.createElement('h3');
    titleEl.className = 'text-sm font-bold text-gray-900 dark:text-white mb-1';
    titleEl.textContent = title;
    block.appendChild(titleEl);

    const bodyEl = document.createElement('p');
    bodyEl.className = 'text-xs text-gray-700 dark:text-gray-300 leading-relaxed';
    bodyEl.textContent = body;
    block.appendChild(bodyEl);

    coachingBanner.appendChild(block);
}

// -- Coaching auto-trigger via chatkit's SSE client --------------------------

async function streamCoachingResponse(threadId) {
    const messages = ckApp.querySelector('ck-messages');
    const input = ckApp.querySelector('ck-input');
    if (!messages) return;

    if (input) input.streaming = true;

    let currentMsg = null;

    try {
        const connection = connectSSE(
            `${cfg.basePath}/api/chat/threads/${threadId}/generate`,
            { body: {}, signal: AbortSignal.timeout(120000) }
        );

        for await (const event of connection) {
            switch (event.event) {
                case EventType.INIT:
                    break;
                case EventType.TEXT:
                    if (!currentMsg) {
                        currentMsg = document.createElement('ck-message');
                        currentMsg.role = 'assistant';
                        currentMsg.startStreaming();
                        messages.addTurnPhase(currentMsg);
                    }
                    currentMsg.appendText(event.data);
                    break;
                case EventType.TOOL_USE: {
                    const parsed = JSON.parse(event.data);
                    const card = document.createElement('ck-tool-card');
                    card.toolName = parsed.tool_name || 'Tool';
                    card.status = 'running';
                    if (parsed.tool_id) card.dataset.toolId = parsed.tool_id;
                    messages.addTurnPhase(card);
                    break;
                }
                case EventType.TOOL_DONE: {
                    const parsed = JSON.parse(event.data);
                    if (parsed.tool_id) {
                        const card = messages.querySelector(`ck-tool-card[data-tool-id="${CSS.escape(parsed.tool_id)}"]`);
                        if (card) {
                            card.status = 'done';
                            if (parsed.summary) card.summary = parsed.summary;
                        }
                    }
                    break;
                }
                case EventType.ERROR: {
                    const errorMsg = document.createElement('ck-message');
                    errorMsg.role = 'error';
                    errorMsg.setContent(event.data);
                    messages.addTurnPhase(errorMsg);
                    break;
                }
                case EventType.DONE:
                    if (currentMsg) currentMsg.endStreaming();
                    currentMsg = null;
                    messages.hideStatus();
                    messages.resetTurn();
                    break;
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error('Coaching stream error:', error);
        }
    } finally {
        if (input) input.streaming = false;
    }
}

// -- Thread loading (with coaching support) ----------------------------------

async function loadThread(threadId) {
    try {
        // Fetch thread detail for coaching info
        const detailRes = await fetch(`${cfg.basePath}/api/chat/threads/${threadId}/detail`);
        if (!detailRes.ok) throw new Error('Failed to load thread detail');
        const detail = await detailRes.json();

        // Clear coaching state
        currentCoachingCardId = detail.coaching_card_id || null;
        updateChatHeader(!!currentCoachingCardId);

        // Render coaching banner if applicable
        coachingBanner.innerHTML = '';
        if (detail.coaching_card_title && detail.coaching_card_body) {
            renderCoachingBanner(detail.coaching_card_title, detail.coaching_card_body);
        }

        // Load thread messages via chatkit
        await ckApp.loadThread(String(threadId));
        setActiveThread(threadId);

        if (window.innerWidth < 768) closeSidebar();

        // Auto-trigger AI response for coaching threads with no assistant reply yet
        if (currentCoachingCardId) {
            const convRes = await fetch(`${cfg.basePath}/api/chat/conversations/${threadId}`);
            if (convRes.ok) {
                const convData = await convRes.json();
                const msgs = convData.messages || [];
                if (msgs.length > 0 && msgs[msgs.length - 1].role === 'user') {
                    await streamCoachingResponse(threadId);
                }
            }
        }
    } catch (error) {
        console.error('Error loading thread:', error);
    }
}

// -- Refresh sidebar on stream end (new thread was created) ------------------

ckApp.addEventListener('ck-stream-end', async () => {
    // Refresh thread list from server
    const res = await fetch(`${cfg.basePath}/api/chat/conversations${bookId ? '?book_id=' + bookId : ''}`);
    if (!res.ok) return;
    const threads = await res.json();

    // Rebuild thread list
    threadList.innerHTML = '';
    if (threads.length === 0) {
        threadList.innerHTML = '<div id="thread-list-empty" class="px-3 py-4 text-center text-sm text-gray-500 dark:text-gray-400"><p>No conversations yet.</p><p class="mt-1 text-xs">Click "New Chat" to start one.</p></div>';
        return;
    }
    for (const t of threads) {
        addThreadItem(t.id, t.title, !!t.coaching_card_id);
    }
    // Highlight the current thread
    if (ckApp.threadId) {
        setActiveThread(ckApp.threadId);
    }
});

// -- Thread item click handlers ----------------------------------------------

document.querySelectorAll('.thread-item').forEach(item => {
    item.addEventListener('click', () => loadThread(item.dataset.threadId));
});
document.querySelectorAll('[data-delete-thread]').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteThread(btn.dataset.deleteThread);
    });
});

// -- New chat button ---------------------------------------------------------

document.getElementById('new-chat-btn').addEventListener('click', () => {
    currentCoachingCardId = null;
    coachingBanner.innerHTML = '';
    ckApp.newChat();
    setActiveThread(null);
    updateChatHeader(false);
    if (window.innerWidth < 768) closeSidebar();
});

// -- Auto-select thread from URL parameter -----------------------------------

const urlParams = new URLSearchParams(window.location.search);
const threadParam = urlParams.get('thread');
if (threadParam) {
    loadThread(threadParam);
}

// -- Book search -------------------------------------------------------------

const bookSearchInput = document.getElementById('book-search-input');
const bookSearchResults = document.getElementById('book-search-results');
let searchDebounceTimer = null;

function showBookResults(books) {
    bookSearchResults.innerHTML = '';
    if (books.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'px-3 py-2 text-xs text-gray-500 dark:text-gray-400';
        empty.textContent = 'No books found';
        bookSearchResults.appendChild(empty);
    } else {
        const allItem = document.createElement('a');
        allItem.href = `${cfg.basePath}/chat`;
        allItem.className = 'flex items-center gap-2 px-3 py-2 text-xs hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 text-primary-600 dark:text-primary-400 font-medium';
        allItem.textContent = 'All books (global chat)';
        bookSearchResults.appendChild(allItem);

        for (const book of books) {
            const item = document.createElement('a');
            item.href = `${cfg.basePath}/books/${book.id}/chat`;
            item.className = 'flex flex-col px-3 py-2 text-xs hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer';
            const titleRow = document.createElement('span');
            titleRow.className = 'font-medium text-gray-900 dark:text-white truncate';
            titleRow.textContent = book.title;
            const metaRow = document.createElement('span');
            metaRow.className = 'text-gray-500 dark:text-gray-400 truncate';
            metaRow.textContent = `${book.author} · ${book.highlight_count} highlight${book.highlight_count !== 1 ? 's' : ''}`;
            item.appendChild(titleRow);
            item.appendChild(metaRow);
            bookSearchResults.appendChild(item);
        }
    }
    bookSearchResults.classList.remove('hidden');
}

function hideBookResults() {
    bookSearchResults.classList.add('hidden');
}

async function searchBooks(query) {
    try {
        const params = new URLSearchParams();
        if (query) params.set('q', query);
        const response = await fetch(`${cfg.basePath}/api/chat/books?${params}`);
        if (!response.ok) return;
        const data = await response.json();
        showBookResults(data.books);
    } catch (error) {
        console.error('Book search error:', error);
    }
}

bookSearchInput.addEventListener('input', () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        searchBooks(bookSearchInput.value.trim());
    }, 300);
});

bookSearchInput.addEventListener('focus', () => {
    searchBooks(bookSearchInput.value.trim());
});

document.addEventListener('click', (e) => {
    if (!bookSearchInput.contains(e.target) && !bookSearchResults.contains(e.target)) {
        hideBookResults();
    }
});

// -- Sync Tailwind dark mode with chatkit theme ------------------------------
// Tailwind: dark mode = <html class="dark">, light = no class
// Chatkit: dark mode = no class, light = <html class="light">
function syncCkTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    if (isDark) {
        document.documentElement.classList.remove('light');
    } else {
        document.documentElement.classList.add('light');
    }
}
syncCkTheme();

// Observe class changes on <html> to keep in sync when theme toggles
new MutationObserver(syncCkTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class'],
});
