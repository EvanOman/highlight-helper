/**
 * Shared application JavaScript for Highlight Helper.
 * Uses window.APP_BASE_PATH set by layouts/base.html.
 */

/**
 * Sync a single highlight to Readwise.
 * @param {number} highlightId
 */
async function syncHighlightToReadwise(highlightId) {
    var basePath = window.APP_BASE_PATH || '';
    var btn = document.getElementById('sync-btn-' + highlightId);
    var btnText = document.getElementById('sync-btn-text-' + highlightId);

    btn.disabled = true;
    btnText.textContent = 'Syncing...';

    try {
        var response = await fetch(basePath + '/api/readwise/sync/' + highlightId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        var data = await response.json();

        if (response.ok && data.success) {
            // Replace button with synced indicator (with dark mode support)
            btn.outerHTML =
                '<span class="inline-flex items-center gap-1 text-green-600 dark:text-green-400 px-2 py-1 bg-green-50 dark:bg-green-900/30 rounded" title="Synced to Readwise">' +
                    '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">' +
                        '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />' +
                    '</svg>' +
                    ' Synced' +
                '</span>';
        } else {
            alert(data.detail || data.error || 'Failed to sync. Please configure your Readwise API token.');
            btnText.textContent = 'Sync';
            btn.disabled = false;
        }
    } catch (error) {
        alert('Network error. Please try again.');
        btnText.textContent = 'Sync';
        btn.disabled = false;
    }
}

/**
 * Toggle star status on a book.
 * @param {number} bookId
 * @param {HTMLElement} btn - The star button element
 * @param {Event|null} event - Optional click event (for stopping propagation on card links)
 * @param {string} iconSize - Tailwind size classes, e.g. 'h-5 w-5' or 'h-6 w-6'
 */
async function toggleStar(bookId, btn, event, iconSize) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    iconSize = iconSize || 'h-5 w-5';
    var basePath = window.APP_BASE_PATH || '';
    try {
        var response = await fetch(basePath + '/api/books/' + bookId + '/star', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) return;
        var data = await response.json();
        var starred = data.starred;
        btn.dataset.starred = starred ? 'true' : 'false';
        btn.title = starred ? 'Unstar this book' : 'Star this book';
        if (starred) {
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="' + iconSize + ' text-amber-400" viewBox="0 0 20 20" fill="currentColor">' +
                '<path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />' +
                '</svg>';
        } else {
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="' + iconSize + ' text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">' +
                '<path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />' +
                '</svg>';
        }
    } catch (error) {
        console.error('Failed to toggle star:', error);
    }
}
