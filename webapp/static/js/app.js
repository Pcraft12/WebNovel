// Common JavaScript utilities for Novel Reader

// Utility function to debounce API calls
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Format chapter title
function formatChapterTitle(title) {
    if (!title) return 'Unknown Chapter';
    return title;
}

// Extract novel ID from URL
function extractNovelId(url) {
    const match = url.match(/book\/(\d+)/);
    return match ? match[1] : null;
}

// Safe HTML escape
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Local storage helpers
const storage = {
    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (e) {
            console.error('Storage error:', e);
            return defaultValue;
        }
    },
    
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            console.error('Storage error:', e);
        }
    },
    
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.error('Storage error:', e);
        }
    }
};

// Reading progress tracker
const readingProgress = {
    save(novelUrl, chapterIndex, timestamp = Date.now()) {
        const key = `reading_${btoa(novelUrl)}`;
        storage.set(key, { chapterIndex, timestamp });
    },
    
    load(novelUrl) {
        const key = `reading_${btoa(novelUrl)}`;
        return storage.get(key);
    },
    
    clear(novelUrl) {
        const key = `reading_${btoa(novelUrl)}`;
        storage.remove(key);
    }
};

// Bookmarks manager
const bookmarks = {
    add(novelUrl, novelTitle, chapterIndex, chapterTitle) {
        const all = storage.get('bookmarks', []);
        all.unshift({
            novelUrl,
            novelTitle,
            chapterIndex,
            chapterTitle,
            addedAt: Date.now()
        });
        // Keep only last 50 bookmarks
        storage.set('bookmarks', all.slice(0, 50));
    },
    
    remove(novelUrl) {
        const all = storage.get('bookmarks', []);
        const filtered = all.filter(b => b.novelUrl !== novelUrl);
        storage.set('bookmarks', filtered);
    },
    
    getAll() {
        return storage.get('bookmarks', []);
    },
    
    exists(novelUrl) {
        const all = storage.get('bookmarks', []);
        return all.some(b => b.novelUrl === novelUrl);
    }
};

// Search history
const searchHistory = {
    add(query) {
        if (!query.trim()) return;
        const all = storage.get('searchHistory', []);
        const filtered = all.filter(q => q !== query);
        filtered.unshift(query);
        storage.set('searchHistory', filtered.slice(0, 20));
    },
    
    getAll() {
        return storage.get('searchHistory', []);
    },
    
    clear() {
        storage.set('searchHistory', []);
    }
};

// Notification system
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 2rem;
        background: ${type === 'error' ? '#ef4444' : type === 'success' ? '#10b981' : '#6366f1'};
        color: white;
        border-radius: 8px;
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Add CSS animation for notifications
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// Export functions for use in other scripts
window.novelReaderUtils = {
    debounce,
    formatChapterTitle,
    extractNovelId,
    escapeHtml,
    storage,
    readingProgress,
    bookmarks,
    searchHistory,
    showNotification
};
