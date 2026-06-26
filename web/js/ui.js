import { api } from './api.js?v=20260626-home-v2';
import { Toast, cleanMessageContent, generateSessionId, escapeHtml } from './utils.js?v=20260626-home-v2';
import { CONFIG } from './config.js?v=20260626-home-v2';

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

function platformEmpty(title, tip) {
    return `
        <div class="platform-empty">
            <div class="platform-empty-title">${escapeHtml(title)}</div>
            <div class="platform-empty-tip">${escapeHtml(tip)}</div>
        </div>`;
}

function badge(text, tone = '') {
    return `<span class="status-badge ${tone}">${escapeHtml(text)}</span>`;
}

function prettyJson(value) {
    try {
        return JSON.stringify(value || {}, null, 2);
    } catch {
        return String(value || '');
    }
}

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
        document.getElementById('chatBox').innerHTML = `
            <div class="welcome-landing" id="welcomeLanding">
                <div class="welcome-hero">
                    <div class="welcome-logo">K</div>
                    <h1 class="welcome-title">你好，我是 Kita</h1>
                    <p class="welcome-subtitle">具备逻辑推理与知识检索能力的智能 AI 助手。选择下方操作快速开始，或直接输入你的问题。</p>
                </div>
                <div class="welcome-grid">
                    <div class="welcome-card" data-welcome-action="new-chat">
                        <div class="welcome-card-icon">💬</div>
                        <div class="welcome-card-title">开始新对话</div>
                        <div class="welcome-card-desc">直接在下方输入框提问，Kita 会为你推理与解答</div>
                    </div>
                    <div class="welcome-card" data-welcome-action="upload">
                        <div class="welcome-card-icon">📂</div>
                        <div class="welcome-card-title">上传知识库</div>
                        <div class="welcome-card-desc">导入文本内容，让 Kita 基于你的数据回答问题</div>
                    </div>
                    <div class="welcome-card" data-welcome-action="git">
                        <div class="welcome-card-icon">🐈</div>
                        <div class="welcome-card-title">Git 导入</div>
                        <div class="welcome-card-desc">从 GitHub 仓库自动解析代码与文档作为知识源</div>
                    </div>
                    <div class="welcome-card" data-welcome-action="prompt">
                        <div class="welcome-card-icon">🌟</div>
                        <div class="welcome-card-title">修改提示词</div>
                        <div class="welcome-card-desc">自定义 AI 的角色身份与回答风格</div>
                    </div>
                </div>
                <div class="welcome-tags">
                    <span class="welcome-tag">🧠 逻辑推理</span>
                    <span class="welcome-tag">📚 知识检索</span>
                    <span class="welcome-tag">🔧 工具调用</span>
                    <span class="welcome-tag">🧭 意图路由</span>
                    <span class="welcome-tag">📊 Trace 追踪</span>
                </div>
            </div>`;
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
        this.loadPlatformOverview();
        this.loadKnowledgeStats();
        this.loadRedisData();
        this.loadPlatformConsole();
    },

    async loadPlatformOverview() {
        const container = document.getElementById('platformOverview');
        if (!container) return;
        container.innerHTML = '加载中...';
        try {
            const [knowledge, sessions, intents, jobs, trace, modelHealth] = await Promise.all([
                api.getKnowledgeStats(),
                api.getRedisStats(),
                api.listIntents(),
                api.listIngestionJobs(),
                api.getTraceSummary(),
                api.listModelHealth()
            ]);
            const succeeded = jobs.filter(job => job.status === 'succeeded').length;
            const healthyModels = modelHealth.filter(item => item.state === 'healthy').length;
            container.innerHTML = `
                <div class="overview-tile">
                    <div class="overview-icon">📚</div>
                    <div class="overview-value">${knowledge.total_docs || 0}</div>
                    <div class="overview-label">知识 Chunk</div>
                    <span class="overview-status-dot"></span>
                </div>
                <div class="overview-tile">
                    <div class="overview-icon">🧭</div>
                    <div class="overview-value">${intents.length}</div>
                    <div class="overview-label">路由意图</div>
                    <span class="overview-status-dot"></span>
                </div>
                <div class="overview-tile">
                    <div class="overview-icon">🧩</div>
                    <div class="overview-value">${succeeded}/${jobs.length}</div>
                    <div class="overview-label">摄取任务成功</div>
                    <span class="overview-status-dot"></span>
                </div>
                <div class="overview-tile">
                    <div class="overview-icon">🧾</div>
                    <div class="overview-value">${trace.bad_cases || 0}</div>
                    <div class="overview-label">Bad Cases</div>
                    <span class="overview-status-dot"></span>
                </div>
                <div class="overview-tile">
                    <div class="overview-icon">🧠</div>
                    <div class="overview-value">${healthyModels}</div>
                    <div class="overview-label">健康模型</div>
                    <span class="overview-status-dot"></span>
                </div>
                <div class="overview-tile">
                    <div class="overview-icon">💬</div>
                    <div class="overview-value">${sessions.length}</div>
                    <div class="overview-label">活跃会话</div>
                    <span class="overview-status-dot"></span>
                </div>`;
        } catch {
            container.innerHTML = platformEmpty('概览加载失败', '基础接口暂时不可用，请稍后刷新。');
        }
    },

    async loadKnowledgeStats() {
        const container = document.getElementById('knowledgeStats');
        container.innerHTML = '加载中...';
        try {
            const data = await api.getKnowledgeStats();
            const tags = data.tag_stats || [];
            container.innerHTML = `
                <div class="platform-list-grid">
                    <div class="platform-mini-card">
                        <div class="platform-mini-head">
                            <div class="platform-mini-title">总 Chunk</div>
                            ${badge(`${data.total_docs || 0}`, 'success')}
                        </div>
                        <div class="platform-meta">来自 pgvector 当前集合</div>
                    </div>
                    ${tags.length ? tags.map(stat => {
                        const tagName = stat.tag || 'N/A';
                        const deleteAction = tagName !== 'N/A'
                            ? `<button class="delete-btn" data-action="delete-tag" data-tag="${escapeHtml(tagName)}" title="删除此标签的所有文档">&times;</button>`
                            : '';
                        return `
                            <div class="platform-mini-card">
                                <div class="platform-mini-head">
                                    <div class="platform-mini-title">${escapeHtml(tagName)}</div>
                                    ${deleteAction}
                                </div>
                                <div class="platform-kv"><span>${escapeHtml(stat.count)} 个 chunk</span></div>
                            </div>`;
                    }).join('') : platformEmpty('暂无知识数据', '上传知识或 Git 导入后，这里会出现标签卡片。')}
                </div>`;
        } catch (error) {
            container.innerHTML = platformEmpty('知识统计加载失败', '请检查 pgvector 连接。');
        }
    },

    async loadRedisData() {
        const container = document.getElementById('redisData');
        container.innerHTML = '加载中...';
        try {
            const sessions = await api.getRedisStats();
            if (sessions.length > 0) {
                container.innerHTML = `
                    <div class="platform-list-grid">
                        ${sessions.map(session => {
                    const hours = Math.floor(session.ttl / 3600);
                    const minutes = Math.floor((session.ttl % 3600) / 60);
                            return `
                                <div class="platform-mini-card">
                                    <div class="platform-mini-head">
                                        <div class="platform-mini-title">${escapeHtml(session.user_id || 'anonymous')}</div>
                                        ${badge(`${session.message_count} 条`, 'success')}
                                    </div>
                                    <div class="platform-meta">Session：<code>${escapeHtml(session.session_id)}</code></div>
                                    <div class="platform-kv"><span>TTL ${hours}h ${minutes}m</span></div>
                                </div>`;
                        }).join('')}
                    </div>`;
            } else {
                container.innerHTML = platformEmpty('暂无活跃会话', '当前 Redis 中没有正在保存的会话状态。');
            }
        } catch (error) {
            container.innerHTML = platformEmpty('Redis 会话加载失败', '请检查 Redis 服务是否运行。');
        }
    },

    async loadPlatformConsole() {
        await Promise.allSettled([
            this.loadPlatformIntents(),
            this.loadPlatformKnowledgeCatalog(),
            this.loadPlatformIngestionJobs(),
            this.loadPlatformTraceData(),
            this.loadPlatformModelRouting()
        ]);
    },

    async loadPlatformIntents() {
        const container = document.getElementById('platformIntents');
        if (!container) return;
        container.innerHTML = '加载中...';
        try {
            const intents = await api.listIntents();
            if (!intents.length) {
                container.innerHTML = platformEmpty(
                    '还没有路由节点',
                    '点击「新建路由节点」，创建第一个 KB / MCP / SYSTEM 路由。'
                );
                return;
            }
            container.innerHTML = `
                <div class="platform-list-grid">
                    ${intents.map(item => {
                        const target = item.kind === 'KB'
                            ? `tag=${item.knowledge_tag || '-'} / dir=${item.knowledge_dir || '-'}`
                            : item.kind === 'MCP'
                                ? `${item.mcp_server || '-'} / ${item.mcp_tool || '-'}`
                                : (item.prompt_template || '系统提示片段');
                        return `
                            <div class="platform-mini-card">
                                <div class="platform-mini-head">
                                    <div class="platform-mini-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
                                    ${badge(item.kind, item.enabled ? 'success' : 'muted')}
                                </div>
                                <div class="platform-meta">目标：<code>${escapeHtml(target)}</code></div>
                                <div class="platform-meta">优先级：${escapeHtml(item.priority ?? 0)} · ${item.enabled ? '已启用' : '已禁用'}</div>
                                <div class="platform-kv">
                                    ${(item.keywords || []).length
                                        ? item.keywords.map(keyword => `<span>${escapeHtml(keyword)}</span>`).join('')
                                        : '<span>未设置关键词</span>'}
                                </div>
                            </div>`;
                    }).join('')}
                </div>`;
        } catch {
            container.innerHTML = platformEmpty('意图加载失败', '请检查后端服务和 /api/v1/platform/intents 接口。');
        }
    },

    async saveIntentFromConsole() {
        const name = document.getElementById('intentName').value.trim();
        if (!name) { Toast.error('请填写意图名称'); return; }
        const keywords = document.getElementById('intentKeywords').value
            .split(/[，,]/)
            .map(item => item.trim())
            .filter(Boolean);
        const payload = {
            name,
            kind: document.getElementById('intentKind').value,
            keywords,
            knowledge_tag: document.getElementById('intentKnowledgeTag').value.trim() || null,
            knowledge_dir: document.getElementById('intentKnowledgeDir').value.trim() || null,
            mcp_server: document.getElementById('intentMcpServer').value.trim() || null,
            mcp_tool: document.getElementById('intentMcpTool').value.trim() || null,
            priority: 10
        };
        await api.saveIntent(payload);
        Toast.success('意图已保存');
        await this.loadPlatformIntents();
        await this.loadPlatformOverview();
    },

    async classifyIntentFromConsole() {
        const query = document.getElementById('intentClassifyQuery').value.trim();
        if (!query) { Toast.error('请输入测试问题'); return; }
        const result = await api.classifyIntent(query);
        const routeEl = document.getElementById('intentRouteResult');
        const matchText = (result.matches || [])
            .map(item => `${item.name}(${item.kind}, ${item.score})`)
            .join('、') || '未命中';
        routeEl.innerHTML = `
            <div class="platform-meta">改写查询：<code>${escapeHtml(result.rewritten_query || query)}</code></div>
            <div class="platform-meta">命中意图：${escapeHtml(matchText)}</div>
            <div class="platform-meta">KB：<code>${escapeHtml(result.knowledge_tag || '-')}</code> / <code>${escapeHtml(result.knowledge_dir || '-')}</code></div>
            <div class="platform-meta">MCP：<code>${escapeHtml((result.mcp_tools || []).map(t => `${t.server_name}/${t.tool_name}`).join(', ') || '-')}</code></div>
        `;
    },

    async loadPlatformKnowledgeCatalog() {
        const container = document.getElementById('platformKnowledgeCatalog');
        if (!container) return;
        container.innerHTML = '加载中...';
        try {
            const [bases, stats] = await Promise.all([
                api.listKnowledgeBases(),
                api.getKnowledgeStats()
            ]);
            if (!bases.length) {
                const legacyTags = stats.tag_stats || [];
                if (legacyTags.length) {
                    container.innerHTML = `
                        <div class="platform-legacy-note">
                            旧知识兼容视图：这些标签来自 pgvector。新上传或 Git 导入后，会自动进入平台目录。
                        </div>
                        <div class="platform-list-grid">
                            ${legacyTags.map(item => `
                                <div class="platform-mini-card">
                                    <div class="platform-mini-head">
                                        <div class="platform-mini-title">${escapeHtml(item.tag || 'N/A')}</div>
                                        ${badge('legacy', 'warn')}
                                    </div>
                                    <div class="platform-meta">来源：pgvector 旧数据</div>
                                    <div class="platform-kv">
                                        <span>${escapeHtml(item.count)} 个 chunk</span>
                                        <span>未回填平台目录</span>
                                    </div>
                                </div>
                            `).join('')}
                        </div>`;
                    return;
                }
                container.innerHTML = platformEmpty(
                    '暂无知识库目录',
                    '上传知识或 Git 导入后，这里会生成 KB / Document / Chunk 目录。'
                );
                return;
            }
            const rows = await Promise.all(bases.map(async kb => {
                const docs = await api.listKnowledgeDocuments(kb.kb_id);
                return `
                    <div class="platform-mini-card">
                        <div class="platform-mini-head">
                            <div class="platform-mini-title">${escapeHtml(kb.name || kb.tag)}</div>
                            ${badge(kb.visibility || 'public', kb.visibility === 'private' ? 'warn' : 'success')}
                        </div>
                        <div class="platform-meta">Tag：<code>${escapeHtml(kb.tag)}</code></div>
                        <div class="platform-meta">目录：<code>${escapeHtml(kb.knowledge_dir || '/')}</code></div>
                        <div class="platform-kv">
                            <span>${docs.length} 个文档</span>
                            <span>Owner ${escapeHtml(kb.owner_user_id)}</span>
                        </div>
                    </div>`;
            }));
            container.innerHTML = `
                <div class="platform-list-grid">${rows.join('')}</div>`;
        } catch {
            container.innerHTML = platformEmpty('知识目录加载失败', '请检查 pgvector 连接和平台目录接口。');
        }
    },

    async loadPlatformIngestionJobs() {
        const container = document.getElementById('platformIngestionJobs');
        if (!container) return;
        container.innerHTML = '加载中...';
        try {
            const jobs = await api.listIngestionJobs();
            if (!jobs.length) {
                container.innerHTML = platformEmpty(
                    '暂无摄取任务',
                    '通过“上传知识库”或“Git 导入”提交后，这里会显示任务状态，并可查看每个节点的执行日志。'
                );
                return;
            }
            container.innerHTML = `
                <div class="platform-list-grid">
                    ${jobs.slice(0, 12).map(job => {
                        const status = job.status || 'unknown';
                        const tone = status === 'succeeded' ? 'success' : status === 'failed' ? 'warn' : '';
                        return `
                            <div class="platform-mini-card">
                                <div class="platform-mini-head">
                                    <button class="delete-btn platform-job-btn" data-action="fill-node-job" data-id="${escapeHtml(job.job_id)}" title="查看节点日志">
                                        ${escapeHtml(job.job_id.slice(0, 8))}
                                    </button>
                                    ${badge(status, tone)}
                                </div>
                                <div class="platform-meta">类型：${escapeHtml(job.kind)} · 阶段：${escapeHtml((job.stats || {}).stage || '-')}</div>
                                <div class="platform-meta">Tag：<code>${escapeHtml(job.tag || '-')}</code></div>
                                <div class="platform-meta">来源：${escapeHtml(job.source_name || '-')}</div>
                            </div>`;
                    }).join('')}
                </div>`;
        } catch {
            container.innerHTML = platformEmpty('摄取任务加载失败', '请检查 /api/v1/ingestion/jobs 接口。');
        }
    },

    async loadNodeLogsFromConsole() {
        const jobId = document.getElementById('nodeLogJobId').value.trim();
        if (!jobId) { Toast.error('请输入 job_id'); return; }
        const container = document.getElementById('platformNodeLogs');
        container.innerHTML = '加载中...';
        try {
            const logs = await api.listIngestionNodeLogs(jobId);
            if (!logs.length) {
                container.innerHTML = platformEmpty('暂无节点日志', '这个任务还没有写入节点日志，或任务 ID 不正确。');
                return;
            }
            container.innerHTML = `
                <div class="platform-list-grid">
                    ${logs.map(log => {
                        const tone = log.status === 'succeeded' ? 'success' : log.status === 'failed' ? 'warn' : '';
                        return `
                            <div class="platform-mini-card">
                                <div class="platform-mini-head">
                                    <div class="platform-mini-title">${escapeHtml(log.node_name)}</div>
                                    ${badge(log.status, tone)}
                                </div>
                                <div class="platform-meta">耗时：${escapeHtml(log.duration_ms ?? '-')} ms</div>
                                <div class="platform-meta">输出：</div>
                                <pre class="platform-json">${escapeHtml(prettyJson(log.output)).slice(0, 500)}</pre>
                            </div>`;
                    }).join('')}
                </div>`;
        } catch {
            container.innerHTML = platformEmpty('节点日志加载失败', '请确认 job_id 是否存在，且当前用户有权限查看。');
        }
    },

    async loadPlatformTraceData() {
        const summaryEl = document.getElementById('platformTraceSummary');
        const feedbackEl = document.getElementById('platformTraceFeedback');
        if (!summaryEl || !feedbackEl) return;
        summaryEl.innerHTML = '加载中...';
        feedbackEl.innerHTML = '加载中...';
        try {
            const [summary, feedback] = await Promise.all([
                api.getTraceSummary(),
                api.listTraceFeedback()
            ]);
            summaryEl.innerHTML = `
                <div class="platform-list-grid">
                    <div class="platform-mini-card">
                        <div class="platform-mini-title">Trace 事件</div>
                        <div class="stat-value">${summary.trace_events || 0}</div>
                    </div>
                    <div class="platform-mini-card">
                        <div class="platform-mini-title">Bad Cases</div>
                        <div class="stat-value">${summary.bad_cases || 0}</div>
                    </div>
                    <div class="platform-mini-card">
                        <div class="platform-mini-title">Feedback</div>
                        <div class="stat-value">${summary.feedback || 0}</div>
                    </div>
                </div>`;
            feedbackEl.innerHTML = feedback.length
                ? `<div class="platform-list-grid">
                    ${feedback.slice(-10).reverse().map(item => `
                        <div class="platform-mini-card">
                            <div class="platform-mini-head">
                                <div class="platform-mini-title">${escapeHtml(item.category || '未分类')}</div>
                                ${badge(item.rating ? `${item.rating} 分` : '未评分', item.rating >= 4 ? 'success' : item.rating ? 'warn' : 'muted')}
                            </div>
                            <div class="platform-meta">Trace：<code>${escapeHtml(item.trace_id || '-')}</code></div>
                            <div class="platform-meta">Session：<code>${escapeHtml(item.session_id || '-')}</code></div>
                            <div class="platform-meta">${escapeHtml(item.comment || '暂无备注')}</div>
                        </div>
                    `).join('')}
                </div>`
                : platformEmpty('暂无反馈', '提交一次评分或 bad case 备注后，这里会显示最近反馈。');
        } catch {
            summaryEl.innerHTML = platformEmpty('Trace 摘要加载失败', '请检查 observability/platform store。');
            feedbackEl.innerHTML = platformEmpty('Feedback 加载失败', '请检查反馈接口。');
        }
    },

    async saveFeedbackFromConsole() {
        const payload = {
            trace_id: document.getElementById('feedbackTraceId').value.trim() || null,
            session_id: document.getElementById('feedbackSessionId').value.trim() || null,
            rating: Number(document.getElementById('feedbackRating').value) || null,
            category: document.getElementById('feedbackCategory').value.trim() || null,
            comment: document.getElementById('feedbackComment').value.trim() || null
        };
        await api.addTraceFeedback(payload);
        Toast.success('反馈已提交');
        await this.loadPlatformTraceData();
        await this.loadPlatformOverview();
    },

    async loadPlatformModelRouting() {
        const container = document.getElementById('platformModelRouting');
        if (!container) return;
        container.innerHTML = '加载中...';
        try {
            const [configs, health] = await Promise.all([
                api.listModelConfigs(),
                api.listModelHealth()
            ]);
            const healthMap = new Map(health.map(item => [item.model_name, item]));
            if (!configs.length && !health.length) {
                container.innerHTML = platformEmpty(
                    '暂无模型配置/健康数据',
                    '系统会继续使用环境变量里的默认模型。保存模型配置后，路由器会按优先级尝试并记录健康状态。'
                );
                return;
            }
            const names = Array.from(new Set([...configs.map(x => x.model_name), ...health.map(x => x.model_name)]));
            container.innerHTML = `
                <div class="platform-list-grid">
                    ${names.map(name => {
                        const cfg = configs.find(item => item.model_name === name) || {};
                        const h = healthMap.get(name) || {};
                        const state = h.state || 'unseen';
                        const tone = state === 'healthy' ? 'success' : state === 'open' || state === 'degraded' ? 'warn' : 'muted';
                        return `
                            <div class="platform-mini-card">
                                <div class="platform-mini-head">
                                    <div class="platform-mini-title">${escapeHtml(name)}</div>
                                    ${badge(state, tone)}
                                </div>
                                <div class="platform-meta">启用：${cfg.enabled === undefined ? '环境默认/健康记录' : (cfg.enabled ? '是' : '否')} · 优先级：${escapeHtml(cfg.priority ?? '-')}</div>
                                <div class="platform-meta">Provider：${escapeHtml(cfg.provider || '-')}</div>
                                <div class="platform-meta">最近错误：${escapeHtml(h.last_error || '-')}</div>
                            </div>`;
                    }).join('')}
                </div>`;
        } catch {
            container.innerHTML = platformEmpty('模型路由加载失败', '请检查 /api/v1/platform/llm/models 和 /health 接口。');
        }
    },

    async saveModelFromConsole() {
        const modelName = document.getElementById('modelName').value.trim();
        if (!modelName) { Toast.error('请填写模型名'); return; }
        await api.saveModelConfig({
            model_name: modelName,
            provider: document.getElementById('modelProvider').value.trim() || null,
            priority: Number(document.getElementById('modelPriority').value) || 0,
            enabled: document.getElementById('modelEnabled').checked
        });
        Toast.success('模型配置已保存');
        await this.loadPlatformModelRouting();
        await this.loadPlatformOverview();
    }
};
