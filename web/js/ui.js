import { api } from './api.js';
import { Toast, cleanMessageContent, generateSessionId } from './utils.js';
import { CONFIG } from './config.js';

let sessionId = "";
let currentSystemPrompt = CONFIG.DEFAULT_SYSTEM_PROMPT;
let activeTaskId = null;
let isStreaming = false;

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
        if (isStreaming) {
            if (activeTaskId) {
                await api.cancelTask(activeTaskId);
            }
            return;
        }
        const inputEle = document.getElementById('userInput');
        const text = inputEle.value.trim();
        if (!text) return;

        state.setSystemPrompt(document.getElementById('systemPromptInput').value.trim() || CONFIG.DEFAULT_SYSTEM_PROMPT);

        this.appendMessage('user', text);
        inputEle.value = '';

        const loadingTip = document.getElementById('loadingTip');
        const showThinking = (step = 1) => {
            loadingTip.innerText = step && step > 1
                ? `正在进行第 ${step} 步推理...`
                : '💡 正在思考...';
            loadingTip.style.display = 'block';
        };
        const hideThinking = () => {
            loadingTip.style.display = 'none';
        };
        showThinking();

        // 创建一个空的 Agent 消息框用于流式填充
        const agentMsgDiv = this.appendMessage('agent', '');
        agentMsgDiv.classList.add('streaming-cursor');
        let fullReply = "";
        let displayedReply = "";
        let pendingReply = "";
        let typewriterTimer = null;
        let typewriterResolve = null;
        let typewriterIdle = Promise.resolve();
        const stopTypewriter = () => {
            if (typewriterTimer) {
                clearInterval(typewriterTimer);
                typewriterTimer = null;
            }
            if (typewriterResolve) {
                typewriterResolve();
                typewriterResolve = null;
            }
        };
        const ensureTypewriter = () => {
            if (typewriterTimer) return;
            typewriterIdle = new Promise(resolve => {
                typewriterResolve = resolve;
                typewriterTimer = setInterval(() => {
                    if (!pendingReply) {
                        stopTypewriter();
                        return;
                    }
                    const step = pendingReply.length > 120 ? 6 : pendingReply.length > 40 ? 3 : 1;
                    displayedReply += pendingReply.slice(0, step);
                    pendingReply = pendingReply.slice(step);
                    this.updateMessage(agentMsgDiv, displayedReply);
                }, 18);
            });
        };
        const enqueueReply = (content) => {
            if (!content) return;
            hideThinking();
            fullReply += content;
            pendingReply += content;
            ensureTypewriter();
        };
        const flushTypewriter = async () => {
            while (typewriterTimer) {
                await typewriterIdle;
            }
        };
        isStreaming = true;
        activeTaskId = null;
        const sendButton = document.getElementById('btnSend');
        sendButton.textContent = '停止';

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

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const blocks = buffer.split('\n\n');
                buffer = blocks.pop();

                for (const block of blocks) {
                    let eventName = 'message';
                    let dataStr = '';
                    for (const line of block.split('\n')) {
                        if (line.startsWith('event:')) eventName = line.slice(6).trim();
                        if (line.startsWith('data:')) dataStr += line.slice(5).trim();
                    }
                    if (!dataStr || dataStr === '[DONE]' || eventName === 'done') continue;
                    try {
                        const data = JSON.parse(dataStr);
                        if (eventName === 'meta') {
                            activeTaskId = data.task_id;
                        } else if (eventName === 'progress') {
                            showThinking(data.step);
                        } else if (eventName === 'error') {
                            hideThinking();
                            throw new Error(data.message || '生成失败');
                        } else if (eventName === 'cancel') {
                            enqueueReply('\n\n（已停止生成）');
                        } else if (eventName === 'tool_end') {
                            enqueueReply('\n✓ 已完成工具调用\n');
                        } else if (eventName === 'tool_start') {
                            // Keep tool progress out of the final assistant message body.
                        } else if (data.content) {
                            enqueueReply(data.content);
                        }
                    } catch (e) {
                        if (eventName === 'error') throw e;
                        console.error("解析 SSE JSON 失败:", e, "原始数据:", dataStr);
                    }
                }
            }
            await flushTypewriter();
            
            this.loadHistorySessions();
        } catch (error) {
            pendingReply = "";
            stopTypewriter();
            console.error("流式对话出错:", error);
            agentMsgDiv.innerText = `系统错误: ${error.message}`;
            Toast.error(`对话失败: ${error.message}`);
        } finally {
            isStreaming = false;
            activeTaskId = null;
            sendButton.textContent = '发送';
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
                html += '<table class="data-table"><thead><tr><th>用户</th><th>Session ID</th><th>消息数</th><th>TTL</th></tr></thead><tbody>';
                sessions.forEach(session => {
                    const hours = Math.floor(session.ttl / 3600);
                    const minutes = Math.floor((session.ttl % 3600) / 60);
                    html += `<tr><td>${session.user_id || 'anonymous'}</td><td>${session.session_id}</td><td>${session.message_count}</td><td>${hours}h ${minutes}m</td></tr>`;
                });
                html += '</tbody></table>';
            } else { html = '<div class="empty-state">暂无活跃会话</div>'; }
            container.innerHTML = html;
        } catch (error) {
            container.innerHTML = `<div class="empty-state">加载失败</div>`;
        }
    }
};
