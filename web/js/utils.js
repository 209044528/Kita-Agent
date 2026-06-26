// Clean LLM ReAct message content
export function cleanMessageContent(content, role) {
    if (role === 'user') {
        const userQuestionMatch = content.match(/\[User Question\]\s*(.+?)$/s);
        if (userQuestionMatch) return userQuestionMatch[1].trim();
        return content;
    } else if (role === 'assistant') {
        const finishMatch = content.match(/Action:\s*Finish\[([\s\S]*)\]$/);
        if (finishMatch) return finishMatch[1].trim();
        return content;
    }
    return content;
}

// Generate a random session ID
export function generateSessionId() {
    return "session-" + Math.random().toString(36).substring(2, 9);
}

export function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

// Toast notification system
export const Toast = {
    show(message, type = 'info', duration = 3000) {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const msgSpan = document.createElement('span');
        msgSpan.innerText = message;
        
        const closeBtn = document.createElement('span');
        closeBtn.className = 'toast-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.onclick = () => this.remove(toast);
        
        toast.appendChild(msgSpan);
        toast.appendChild(closeBtn);
        container.appendChild(toast);

        setTimeout(() => {
            if (toast.parentElement) {
                this.remove(toast);
            }
        }, duration);
    },

    remove(toast) {
        toast.style.animation = 'toast-fade-out 0.3s forwards';
        setTimeout(() => {
            if (toast.parentElement) {
                toast.parentElement.removeChild(toast);
            }
        }, 300);
    },

    info(msg, dur) { this.show(msg, 'info', dur); },
    success(msg, dur) { this.show(msg, 'success', dur); },
    error(msg, dur) { this.show(msg, 'error', dur); }
};
