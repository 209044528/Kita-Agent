import { CONFIG } from './config.js?v=20260626-platform-human';
import { Toast } from './utils.js?v=20260626-platform-human';

class ApiError extends Error {
    constructor(info, code) {
        super(info);
        this.code = code;
    }
}

function authHeaders() {
    const apiKey = localStorage.getItem('kitaApiKey');
    return apiKey ? { Authorization: `Bearer ${apiKey}` } : {};
}

async function requestWithAuth(url, options = {}, retryAuth = true) {
    const response = await fetch(url, {
        ...options,
        headers: {
            ...authHeaders(),
            ...options.headers
        }
    });
    if (response.status === 401 && retryAuth) {
        const apiKey = window.prompt('请输入 Kita-Agent API Key');
        if (apiKey) {
            localStorage.setItem('kitaApiKey', apiKey.trim());
            return requestWithAuth(url, options, false);
        }
    }
    return response;
}

async function fetchWithHandler(url, options = {}) {
    try {
        const response = await requestWithAuth(`${CONFIG.API_BASE}${url}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        
        const result = await response.json();
        
        // Unified response format checking
        if (result.code !== "0000") {
            throw new ApiError(result.info, result.code);
        }
        
        return result.data;
    } catch (error) {
        if (error instanceof ApiError) {
            Toast.error(`业务异常: ${error.message}`);
        } else {
            Toast.error(`网络错误: ${error.message}`);
        }
        throw error; // Re-throw for specific handling if needed
    }
}

export const api = {
    // Session APIs
    getSessions: () => fetchWithHandler('/sessions'),
    
    getSessionHistory: (sessionId) => fetchWithHandler(`/session/${sessionId}`),
    
    renameSession: (sessionId, title) => 
        fetchWithHandler('/session/rename', {
            method: 'POST',
            body: JSON.stringify({ session_id: sessionId, title })
        }),
        
    deleteSession: (sessionId) => 
        fetchWithHandler(`/session/${sessionId}`, { method: 'DELETE' }),

    // Chat APIs
    doStreamChat: (sessionId, userInput, systemPrompt) =>
        requestWithAuth(`${CONFIG.API_BASE}/chat/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                user_input: userInput,
                system_prompt: systemPrompt
            })
        }),

    cancelTask: (taskId) =>
        fetchWithHandler(`/chat/tasks/${encodeURIComponent(taskId)}/cancel`, {
            method: 'POST'
        }),
        
    savePrompt: (sessionId, systemPrompt) =>
        fetchWithHandler('/prompt', {
            method: 'POST',
            body: JSON.stringify({ session_id: sessionId, system_prompt: systemPrompt })
        }),
        
    getPrompt: async (sessionId) => {
        try {
            return await fetchWithHandler(`/prompt?session_id=${sessionId}`);
        } catch {
            return ""; // Fallback
        }
    },

    // Knowledge APIs
    upsertKnowledge: (tag, sourceName, rawText) =>
        fetchWithHandler('/knowledge/upsert', {
            method: 'POST',
            body: JSON.stringify({ tag, source_name: sourceName, raw_text: rawText })
        }),
        
    deleteKnowledgeTag: (tag) =>
        fetchWithHandler('/knowledge/delete', {
            method: 'DELETE',
            body: JSON.stringify({ tag })
        }),
        
    gitIngestKnowledge: (repoUrl, branch, knowledgeTag) =>
        fetchWithHandler('/knowledge/git', {
            method: 'POST',
            body: JSON.stringify({ repo_url: repoUrl, branch, knowledge_tag: knowledgeTag })
        }),

    // Maintenance APIs
    getKnowledgeStats: () => fetchWithHandler('/maintenance/knowledge'),
    getRedisStats: () => fetchWithHandler('/maintenance/redis'),

    // Platform APIs
    listIntents: () => fetchWithHandler('/platform/intents?include_disabled=true'),
    saveIntent: (payload) =>
        fetchWithHandler('/platform/intents', {
            method: 'POST',
            body: JSON.stringify(payload)
        }),
    classifyIntent: (query) =>
        fetchWithHandler('/platform/intents/classify', {
            method: 'POST',
            body: JSON.stringify({ query })
        }),
    listKnowledgeBases: () => fetchWithHandler('/platform/knowledge/bases'),
    listKnowledgeDocuments: (kbId = '') =>
        fetchWithHandler(`/platform/knowledge/documents${kbId ? `?kb_id=${encodeURIComponent(kbId)}` : ''}`),
    listIngestionJobs: () => fetchWithHandler('/ingestion/jobs'),
    listIngestionNodeLogs: (jobId) =>
        fetchWithHandler(`/platform/ingestion/jobs/${encodeURIComponent(jobId)}/nodes`),
    getTraceSummary: () => fetchWithHandler('/observability/trace-summary'),
    listTraceFeedback: () => fetchWithHandler('/platform/traces/feedback'),
    addTraceFeedback: (payload) =>
        fetchWithHandler('/platform/traces/feedback', {
            method: 'POST',
            body: JSON.stringify(payload)
        }),
    listModelConfigs: () => fetchWithHandler('/platform/llm/models'),
    saveModelConfig: (payload) =>
        fetchWithHandler('/platform/llm/models', {
            method: 'POST',
            body: JSON.stringify(payload)
        }),
    listModelHealth: () => fetchWithHandler('/platform/llm/health')
};
