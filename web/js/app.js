import { ui, state } from './ui.js?v=20260626-typewriter';
import { api } from './api.js?v=20260626-typewriter';
import { Toast, generateSessionId } from './utils.js?v=20260626-typewriter';

// Setup marked.js configurations
if (window.marked && window.markedKatex) {
    marked.use(window.markedKatex({ throwOnError: false }));
    marked.setOptions({ breaks: true, gfm: true });
}

let pendingDeleteSessionId = null;
let pendingRenameSessionId = null;

// Initialize Event Listeners
function initEvents() {
    // Top-level buttons
    document.getElementById('btnNewChat').addEventListener('click', () => ui.startNewChat());
    document.getElementById('btnMaintenance').addEventListener('click', async () => {
        ui.modals.open('maintenanceModal');
        await ui.refreshMaintenanceData();
    });

    // Chat Input
    document.getElementById('btnSend').addEventListener('click', () => ui.sendMessage());
    document.getElementById('userInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') ui.sendMessage();
    });

    // Dropdowns
    document.getElementById('btnMoreOptions').addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById("plusDropdown").classList.toggle("show");
    });

    document.getElementById('btnOpenUploadModal').addEventListener('click', () => {
        document.getElementById("plusDropdown").classList.remove("show");
        ui.modals.open('uploadModal');
    });

    document.getElementById('btnOpenGitModal').addEventListener('click', () => {
        document.getElementById("plusDropdown").classList.remove("show");
        ui.modals.open('gitModal');
    });

    document.getElementById('btnOpenPromptModal').addEventListener('click', async () => {
        document.getElementById("plusDropdown").classList.remove("show");
        ui.modals.open('promptModal');
        const promptInput = document.getElementById('systemPromptInput');
        promptInput.value = '加载中...';
        const prompt = await api.getPrompt(state.getSessionId());
        promptInput.value = prompt || state.getSystemPrompt();
    });

    // Git URL Auto-detection
    const handleGitUrlInput = (e) => {
        const url = e.target.value.trim();
        const branchInput = document.getElementById('gitBranch');
        const tagInput = document.getElementById('gitKnowledgeTag');
        
        if (!url) {
            branchInput.value = 'main';
            return;
        }

        // 1. Extract branch (GitHub style: /tree/branch or /blob/branch)
        let detectedBranch = 'main'; // Default back to main if not found
        if (url.includes('/tree/')) {
            detectedBranch = url.split('/tree/')[1].split('/')[0].split('?')[0].split('#')[0];
        } else if (url.includes('/blob/')) {
            detectedBranch = url.split('/blob/')[1].split('/')[0].split('?')[0].split('#')[0];
        }
        branchInput.value = detectedBranch;

        // 2. Auto-fill tag (extract repo name)
        // Only auto-fill if the tag is empty or was previously auto-filled
        if (!tagInput.value.trim() || tagInput.dataset.autoFilled === 'true') {
            let cleanUrl = url.replace(/\/$/, '').replace('.git', '');
            if (url.includes('/tree/')) cleanUrl = cleanUrl.split('/tree/')[0];
            if (url.includes('/blob/')) cleanUrl = cleanUrl.split('/blob/')[0];
            
            const parts = cleanUrl.split('/');
            const repoName = parts[parts.length - 1];
            
            if (repoName && repoName !== 'github.com' && repoName.length > 1) {
                tagInput.value = repoName;
                tagInput.dataset.autoFilled = 'true';
            }
        }
    };

    const gitRepoInput = document.getElementById('gitRepoUrl');
    ['input', 'change', 'paste'].forEach(evt => {
        gitRepoInput.addEventListener(evt, handleGitUrlInput);
    });

    // Mark tag as not auto-filled if user manually edits it
    document.getElementById('gitKnowledgeTag').addEventListener('input', (e) => {
        e.target.dataset.autoFilled = 'false';
    });

    // Modals Close Buttons
    document.querySelectorAll('.btn-cancel').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal');
            if (modal) modal.style.display = 'none';
        });
    });

    // Action handlers for dynamic sidebar and maintenance content
    document.body.addEventListener('click', async (e) => {
        const target = e.target.closest('button, span');
        if (!target || !target.dataset.action) return;

        const action = target.dataset.action;
        const id = target.dataset.id;

        if (action === 'switch') {
            ui.switchSession(id);
        } 
        else if (action === 'toggle-menu') {
            e.stopPropagation();
            document.querySelectorAll('.dropdown-content').forEach(m => {
                if (m.id.startsWith('menu-')) m.style.display = 'none';
            });
            const menu = document.getElementById(`menu-${id}`);
            if (menu) menu.style.display = 'block';
        }
        else if (action === 'rename-prompt') {
            pendingRenameSessionId = id;
            document.getElementById('renameInput').value = target.dataset.title;
            ui.modals.open('renameModal');
            setTimeout(() => document.getElementById('renameInput').focus(), 100);
        }
        else if (action === 'delete-prompt') {
            pendingDeleteSessionId = id;
            ui.modals.open('deleteModal');
        }
        else if (action === 'delete-tag') {
            const tag = target.dataset.tag;
            if (confirm(`确定要删除标签为 "${tag}" 的所有知识文档吗？`)) {
                try {
                    await api.deleteKnowledgeTag(tag);
                    Toast.success(`标签 "${tag}" 已删除`);
                    ui.refreshMaintenanceData();
                } catch(e) {}
            }
        }
    });

    // Global Click Listener for Dropdowns
    window.addEventListener('click', (e) => {
        if (!e.target.closest('#plusDropdown')) {
            document.getElementById("plusDropdown").classList.remove('show');
        }
        if (!e.target.matches('.menu-dots')) {
            document.querySelectorAll('.dropdown-content').forEach(m => {
                if (m.id && m.id.startsWith('menu-')) m.style.display = 'none';
            });
        }
    });

    // Modals Confirm Buttons
    document.getElementById('btnConfirmUpload').addEventListener('click', async () => {
        const tag = document.getElementById('knowledgeTag').value.trim();
        const sourceName = document.getElementById('sourceName').value.trim();
        const text = document.getElementById('knowledgeText').value.trim();
        if (!tag || !text) { Toast.error('请填写知识标签和知识内容'); return; }

        try {
            await api.upsertKnowledge(tag, sourceName || '用户上传', text);
            Toast.success('知识库上传任务已提交后台处理');
            ui.modals.close('uploadModal');
        } catch(e) {}
    });

    document.getElementById('btnConfirmGit').addEventListener('click', async () => {
        const repoUrl = document.getElementById('gitRepoUrl').value.trim();
        const branch = document.getElementById('gitBranch').value.trim() || 'main';
        const tag = document.getElementById('gitKnowledgeTag').value.trim();
        if (!repoUrl) { Toast.error('请填写 Git 仓库链接'); return; }

        try {
            await api.gitIngestKnowledge(repoUrl, branch, tag);
            Toast.success('Git 仓库解析任务已提交后台执行');
            ui.modals.close('gitModal');
        } catch(e) {}
    });

    document.getElementById('btnConfirmPrompt').addEventListener('click', async () => {
        const promptText = document.getElementById('systemPromptInput').value.trim();
        if (!promptText) { Toast.error('提示词不能为空'); return; }
        
        try {
            await api.savePrompt(state.getSessionId(), promptText);
            Toast.success('提示词已保存');
            ui.modals.close('promptModal');
        } catch(e) {}
    });

    document.getElementById('btnConfirmRename').addEventListener('click', async () => {
        const newTitle = document.getElementById('renameInput').value.trim();
        if (!newTitle) { Toast.error('对话名称不能为空'); return; }
        if (!pendingRenameSessionId) return;
        
        try {
            await api.renameSession(pendingRenameSessionId, newTitle);
            Toast.success('重命名成功');
            ui.modals.close('renameModal');
            ui.loadHistorySessions();
        } catch(e) {}
    });

    document.getElementById('btnConfirmDelete').addEventListener('click', async () => {
        if (!pendingDeleteSessionId) return;
        try {
            await api.deleteSession(pendingDeleteSessionId);
            Toast.success('删除成功');
            if (pendingDeleteSessionId === state.getSessionId()) {
                ui.startNewChat();
            } else {
                ui.loadHistorySessions();
            }
            ui.modals.close('deleteModal');
        } catch(e) {}
    });

    document.getElementById('btnRefreshMaintenance').addEventListener('click', () => {
        ui.refreshMaintenanceData();
    });

    // History API integration
    window.addEventListener('popstate', async () => {
        const path = window.location.pathname;
        const match = path.match(/^\/chat\/(session-[a-zA-Z0-9\-]+)$/);
        if (match) {
            await ui.switchSession(match[1], true);
        } else {
            ui.startNewChat();
        }
    });
}

// App Initialization
async function initApp() {
    initEvents();
    
    await ui.loadHistorySessions();
    const path = window.location.pathname;
    const match = path.match(/^\/chat\/(session-[a-zA-Z0-9\-]+)$/);

    if (match) {
        await ui.switchSession(match[1], true);
    } else {
        ui.startNewChat();
    }
}

// Start application
window.addEventListener('DOMContentLoaded', initApp);
