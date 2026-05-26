import { api } from './api.js';
import { Toast, cleanMessageContent, generateSessionId } from './utils.js';
import { CONFIG } from './config.js';

let sessionId = "";
let currentSystemPrompt = CONFIG.DEFAULT_SYSTEM_PROMPT;

// State management
export const state = {
    getSessionId: () => sessionId,
    setSessionId: (id) => {
        sessionId = id;
        localStorage.setItem('currentSessionId', id);
    },
    getSystemPrompt: () => currentSystemPrompt,
    setSystemPrompt: (prompt) => { currentSystemPrompt = prompt; }
};

// UI Rendering Functions
export const ui = {
    async loadHistorySessions() {
        const container = document.getElementById('sessionList');
        try {
            const data = await api.getSessions();
            if (data && data.length > 0) {
                container.innerHTML = data.map(sess => {
                    const isActive = sess.id === state.getSessionId() ? 'active' : '';
                    const title = sess.title || "未归档对话";
                    return `
                    <div class="history-item-container ${isActive}">
                        <button class="history-item" data-action="switch" data-id="${sess.id}" title="${title}">
                            ${title}
                        </button>
                        <div class="dropdown">
                            <span class="menu-dots" data-action="toggle-menu" data-id="${sess.id}">⋮</span>
                            <div class="dropdown-content" id="menu-${sess.id}" style="bottom: auto; top: 100%; left: auto; right: 0;">
                                <button data-action="rename-prompt" data-id="${sess.id}" data-title="${title}">✏️ 重命名</button>
                                <button data-action="delete-prompt" data-id="${sess.id}" style="color:#ff4d4f">🗑️ 删除</button>
                            </div>
                        </div>
                    </div>
                    `;
                }).join('');
            } else {
                container.innerHTML = '<div class="empty-state" style="padding: 10px; font-size: 0.85rem;">暂无历史会话</div>';
            }
        } catch (error) {
            container.innerHTML = '<div class="empty-state" style="padding: 10px; font-size: 0.85rem;">加载失败</div>';
        }
    },

    appendMessage(role, text) {
        const chatBox = document.getElementById('chatBox');
        const msgDiv = document.createElement('div');
        msgDiv.className = `message msg-${role}`;
        
        if (role === 'agent') {
            msgDiv.innerHTML = this.renderMarkdown(text);
        } else {
            msgDiv.innerText = text;
        }
        
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
        return msgDiv;
    },

    renderMarkdown(text) {
        let mathFormatted = text
            .replace(/\\\\?\(\s*/g, ' $')
            .replace(/\s*\\\\?\)/g, '$ ')
            .replace(/\\\\?\[\s*/g, '\n$$\n')
            .replace(/\s*\\\\?\]/g, '\n$$\n');
        return marked.parse(mathFormatted);
    },

    updateMessage(msgDiv, text) {
        msgDiv.innerHTML = this.renderMarkdown(text);
        const chatBox = document.getElementById('chatBox');
        chatBox.scrollTop = chatBox.scrollHeight;
    },

    async switchSession(id, isInitialLoad = false) {
        state.setSessionId(id);
        
        if (!isInitialLoad) {
            history.pushState({}, "", "/chat/" + id);
        }

        const chatBox = document.getElementById('chatBox');
        chatBox.innerHTML = `<div class="message msg-agent">正在加载历史会话...</div>`;

        try {
            const data = await api.getSessionHistory(id);
            if (data) {
                chatBox.innerHTML = '';
                const messages = data.messages || [];

                messages.forEach(msg => {
                    if (msg.role !== 'system' && !msg.content.startsWith('Observation:')) {
                        const cleanedContent = cleanMessageContent(msg.content, msg.role);
                        const roleClass = msg.role === 'assistant' ? 'agent' : msg.role;
                        this.appendMessage(roleClass, cleanedContent);
                    }
                });

                if (messages.filter(m => m.role !== 'system').length === 0) {
                    chatBox.innerHTML = `<div class="message msg-agent">已切换至历史会话（暂无对话记录）</div>`;
                }
            }
        } catch (error) {
            chatBox.innerHTML = `<div class="message msg-agent">加载失败：${error.message}</div>`;
        }
        
        chatBox.scrollTop = chatBox.scrollHeight;
        this.loadHistorySessions();
    },

    startNewChat() {
        state.setSessionId(generateSessionId());
        history.pushState({}, "", "/");
        document.getElementById('chatBox').innerHTML = '<div class="message msg-agent">你好！我是 Kita，是一个具备逻辑思考能力的智能 AI 助手。有什么我可以帮你的吗？</div>';
        this.loadHistorySessions();
    },

    async sendMessage() {
        const inputEle = document.getElementById('userInput');
        const text = inputEle.value.trim();
        if (!text) return;

        state.setSystemPrompt(document.getElementById('systemPromptInput').value.trim() || CONFIG.DEFAULT_SYSTEM_PROMPT);

        this.appendMessage('user', text);
        inputEle.value = '';

        const loadingTip = document.getElementById('loadingTip');
        loadingTip.style.display = 'block';

        // 创建一个空的 Agent 消息框用于流式填充
        const agentMsgDiv = this.appendMessage('agent', '');
        agentMsgDiv.classList.add('streaming-cursor');
        let fullReply = "";

        try {
            console.log("开始流式请求...");
            const response = await api.doStreamChat(state.getSessionId(), text, state.getSystemPrompt());
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.info || '网络请求失败');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            
            loadingTip.style.display = 'none';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                
                // 留下最后一个可能不完整的行在 buffer 中
                buffer = lines.pop();
                
                for (const line of lines) {
                    const trimmedLine = line.trim();
                    if (trimmedLine.startsWith('data: ')) {
                        const dataStr = trimmedLine.slice(6).trim();
                        if (dataStr === '[DONE]') {
                            console.log("流式请求完成");
                            break;
                        }
                        
                        try {
                            const data = JSON.parse(dataStr);
                            if (data.content) {
                                fullReply += data.content;
                                this.updateMessage(agentMsgDiv, fullReply);
                            }
                        } catch (e) {
                            console.error("解析 SSE JSON 失败:", e, "原始数据:", dataStr);
                        }
                    }
                }
            }
            
            this.loadHistorySessions();
        } catch (error) {
            console.error("流式对话出错:", error);
            agentMsgDiv.innerText = `系统错误: ${error.message}`;
            Toast.error(`对话失败: ${error.message}`);
        } finally {
            loadingTip.style.display = 'none';
            agentMsgDiv.classList.remove('streaming-cursor');
        }
    },

    // Modal Toggles
    modals: {
        open(id) { 
            const el = document.getElementById(id);
            if (el) el.style.display = 'flex'; 
        },
        close(id) { 
            const el = document.getElementById(id);
            if (el) el.style.display = 'none'; 
        },
        closeAll() {
            document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
        }
    },

    // Maintenance Data Rendering
    async refreshMaintenanceData() {
        this.loadKnowledgeStats();
        this.loadRedisData();
    },

    async loadKnowledgeStats() {
        const container = document.getElementById('knowledgeStats');
        container.innerHTML = '加载中...';
        try {
            const data = await api.getKnowledgeStats();
            let html = `<div class="stat-card"><h4>总文档数</h4><div class="stat-value">${data.total_docs}</div></div>`;
            if (data.tag_stats && data.tag_stats.length > 0) {
                html += '<table class="data-table"><thead><tr><th>标签</th><th>文档数</th><th>操作</th></tr></thead><tbody>';
                data.tag_stats.forEach(stat => {
                    const tagName = stat.tag || 'N/A';
                    const deleteAction = tagName !== 'N/A' ? `<button class="delete-btn" data-action="delete-tag" data-tag="${tagName}" title="删除此标签的所有文档">&times;</button>` : '';
                    html += `<tr><td>${tagName}</td><td>${stat.count}</td><td>${deleteAction}</td></tr>`;
                });
                html += '</tbody></table>';
            }
            container.innerHTML = html || '<div class="empty-state">暂无数据</div>';
        } catch (error) {
            container.innerHTML = `<div class="empty-state">加载失败</div>`;
        }
    },

    async loadRedisData() {
        const container = document.getElementById('redisData');
        container.innerHTML = '加载中...';
        try {
            const sessions = await api.getRedisStats();
            let html = '';
            if (sessions.length > 0) {
                html += `<div class="stat-card"><h4>活跃会话数</h4><div class="stat-value">${sessions.length}</div></div>`;
                html += '<table class="data-table"><thead><tr><th>Session ID</th><th>消息数</th><th>TTL</th></tr></thead><tbody>';
                sessions.forEach(session => {
                    const hours = Math.floor(session.ttl / 3600);
                    const minutes = Math.floor((session.ttl % 3600) / 60);
                    html += `<tr><td>${session.session_id}</td><td>${session.message_count}</td><td>${hours}h ${minutes}m</td></tr>`;
                });
                html += '</tbody></table>';
            } else { html = '<div class="empty-state">暂无活跃会话</div>'; }
            container.innerHTML = html;
        } catch (error) {
            container.innerHTML = `<div class="empty-state">加载失败</div>`;
        }
    }
};
