const API = '';
let conversationId = null;
let currentUserEmail = null;

// ── Auth Helpers ──────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem('jwt_token'); }
function setToken(token, email) {
    localStorage.setItem('jwt_token', token);
    localStorage.setItem('user_email', email);
    currentUserEmail = email;
}
function clearToken() {
    localStorage.removeItem('jwt_token');
    localStorage.removeItem('user_email');
    currentUserEmail = null;
}

// Wrapper around fetch that automatically adds Authorization header
async function authFetch(url, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401) {
        clearToken();
        showAuthModal();
        throw new Error('Session expired. Please log in again.');
    }
    return resp;
}

function showAuthModal() {
    document.getElementById('auth-overlay').style.display = 'flex';
}
function hideAuthModal() {
    document.getElementById('auth-overlay').style.display = 'none';
}
function switchTab(tab) {
    document.getElementById('login-form').style.display = tab === 'login' ? '' : 'none';
    document.getElementById('register-form').style.display = tab === 'register' ? '' : 'none';
    document.getElementById('tab-login').classList.toggle('active', tab === 'login');
    document.getElementById('tab-register').classList.toggle('active', tab === 'register');
}

async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');
    errEl.textContent = ''; btn.textContent = 'Logging in...';
    try {
        const resp = await fetch(`${API}/api/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await resp.json();
        if (resp.ok) {
            setToken(data.access_token, data.email);
            hideAuthModal();
            initApp();
        } else {
            errEl.textContent = data.detail || 'Login failed.';
        }
    } catch (err) { errEl.textContent = err.message; }
    btn.textContent = 'Login';
}

async function handleRegister(e) {
    e.preventDefault();
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value;
    const confirm = document.getElementById('reg-confirm').value;
    const errEl = document.getElementById('reg-error');
    const btn = document.getElementById('reg-btn');
    errEl.textContent = '';
    if (password !== confirm) { errEl.textContent = 'Passwords do not match.'; return; }
    btn.textContent = 'Creating account...';
    try {
        const resp = await fetch(`${API}/api/auth/register`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await resp.json();
        if (resp.ok) {
            setToken(data.access_token, data.email);
            hideAuthModal();
            initApp();
        } else {
            errEl.textContent = data.detail || 'Registration failed.';
        }
    } catch (err) { errEl.textContent = err.message; }
    btn.textContent = 'Create Account';
}

function handleLogout() {
    clearToken();
    conversationId = null;
    document.getElementById('user-email').textContent = '';
    goHome();
    showAuthModal();
}

function goHome() {
    conversationId = null;
    messagesContainer.innerHTML = '';
    if (welcomeScreen) {
        messagesContainer.appendChild(welcomeScreen);
        welcomeScreen.style.display = '';
    }
    document.getElementById('back-btn').style.display = 'none';
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    checkExistingDocument();
}

function startNewChat() {
    conversationId = null;
    messagesContainer.innerHTML = '';
    if (welcomeScreen) {
        messagesContainer.appendChild(welcomeScreen);
        welcomeScreen.style.display = '';
    }
    document.getElementById('back-btn').style.display = 'none';
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    checkExistingDocument();
}

function initApp() {
    const email = localStorage.getItem('user_email') || '';
    document.getElementById('user-email').textContent = email;
    currentUserEmail = email;
    loadModels();
    fetchCommands();
    updateBadge();
    loadConversations();
    checkExistingDocument();
}

// ── Conversation History ───────────────────────────────────────────────────

async function loadConversations() {
    try {
        const resp = await authFetch(`${API}/api/conversations`);
        if (!resp.ok) return;
        const convs = await resp.json();
        renderConversations(convs);
    } catch (e) {}
}

function renderConversations(convs) {
    const list = document.getElementById('conv-list');
    const empty = document.getElementById('conv-empty');
    // Remove old conversation items (keep the empty placeholder)
    list.querySelectorAll('.conv-item').forEach(el => el.remove());

    if (!convs || convs.length === 0) {
        empty.style.display = '';
        return;
    }
    empty.style.display = 'none';

    convs.forEach(conv => {
        const item = document.createElement('button');
        item.className = 'conv-item' + (conv.id === conversationId ? ' active' : '');
        item.dataset.id = conv.id;

        const date = new Date(conv.updated_at);
        const timeStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

        item.innerHTML = `
            <div class="conv-item-left">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                <span class="conv-title">${conv.title || 'Chat'}</span>
            </div>
            <div class="conv-item-right">
                <span class="conv-date">${timeStr}</span>
                <button class="conv-delete-btn" title="Delete Chat" onclick="event.stopPropagation(); deleteConversation(${conv.id})">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                </button>
            </div>
        `;
        item.addEventListener('click', () => loadConversationMessages(conv.id, item));
        list.appendChild(item);
    });
}

async function loadConversationMessages(convId, itemEl) {
    try {
        const resp = await authFetch(`${API}/api/conversations/${convId}/messages`);
        if (!resp.ok) return;
        const messages = await resp.json();

        // Set active conversation
        conversationId = convId;
        document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
        if (itemEl) itemEl.classList.add('active');

        // Clear chat and hide welcome screen
        messagesContainer.innerHTML = '';
        if (welcomeScreen) welcomeScreen.style.display = 'none';
        // Show back button
        document.getElementById('back-btn').style.display = 'flex';

        // Render each message
        messages.forEach(msg => {
            if (msg.role === 'user') {
                addMessage('user', msg.content);
            } else if (msg.role === 'assistant') {
                addMessage('assistant', msg.content, msg.agent_type, msg.provider, msg.model);
            }
        });

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        checkExistingDocument();
    } catch (e) {}
}

async function deleteConversation(convId) {
    if (!confirm('Are you sure you want to delete this chat?')) return;
    try {
        const resp = await authFetch(`${API}/api/conversations/${convId}`, { method: 'DELETE' });
        if (resp.ok) {
            if (conversationId === convId) goHome();
            loadConversations();
        } else {
            alert('Failed to delete conversation.');
        }
    } catch (e) {
        alert('Error deleting conversation.');
    }
}

// DOM Elements
const sidebar = document.getElementById('sidebar');
const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');
const providerSelect = document.getElementById('provider-select');
const modelInput = document.getElementById('model-input');
const modelSelect = document.getElementById('model-select');
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const uploadStatus = document.getElementById('upload-status');
const uploadProgress = document.getElementById('upload-bar');
const messagesContainer = document.getElementById('messages-container');
const welcomeScreen = document.getElementById('welcome-screen');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const badgeText = document.getElementById('badge-text');
const newChatBtn = document.getElementById('new-chat-btn');
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const closeSettingsBtn = document.getElementById('close-settings-btn');
const docPane = document.getElementById('doc-pane');
const commandAutocomplete = document.getElementById('command-autocomplete');
const docContent = document.getElementById('doc-content');

// Init
document.addEventListener('DOMContentLoaded', () => {
    if (window.marked && window.hljs) {
        marked.setOptions({
            highlight: function(code, lang) {
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            }
        });
    }

    setupEventListeners();

    // Check if user is already logged in
    if (getToken()) {
        hideAuthModal();
        initApp();
    } else {
        showAuthModal();
    }
});

// ── Slash Command Autocomplete ─────────────────────────────────────────
let _commands = {};
let _acActiveIndex = -1;
let _acFilteredCommands = [];

async function fetchCommands() {
    try {
        const resp = await authFetch(`${API}/api/commands`);
        if (resp.ok) _commands = await resp.json();
    } catch (e) {
        // Fallback static commands
        _commands = {
            '/help':    { description: 'Show command reference', icon: '?', agent: 'system' },
            '/status':  { description: 'Document & index status', icon: 'i', agent: 'system' },
            '/clear':   { description: 'Clear conversation', icon: '×', agent: 'system' },
            '/chat':    { description: 'General conversation (no doc needed)', icon: '›', agent: 'general' },
            '/summary': { description: 'Route to Summary Agent', icon: 'Σ', agent: 'summary' },
            '/suggest': { description: 'Route to Suggestion Agent', icon: '*', agent: 'suggestion' },
            '/modify':  { description: 'Route to Modification Agent', icon: '/', agent: 'modification' },
        };
    }
}

function showCommandAutocomplete(filter = '') {
    const keys = Object.keys(_commands);
    _acFilteredCommands = filter
        ? keys.filter(k => k.startsWith('/' + filter))
        : keys;
    if (_acFilteredCommands.length === 0) {
        hideCommandAutocomplete();
        return;
    }
    _acActiveIndex = 0;
    commandAutocomplete.innerHTML =
        '<div class="command-autocomplete-header">Command Activation</div>' +
        _acFilteredCommands.map((cmd, i) => {
            const c = _commands[cmd];
            return `<button class="command-item${i === 0 ? ' active' : ''}" data-cmd="${cmd}">
                <span class="command-icon">${c.icon}</span>
                <div class="command-info">
                    <span class="command-name">${cmd}</span>
                    <span class="command-desc">${c.description}</span>
                </div>
                <span class="command-agent-pill ${c.agent}">${c.agent}</span>
            </button>`;
        }).join('');
    commandAutocomplete.style.display = 'block';

    // Click handlers on items
    commandAutocomplete.querySelectorAll('.command-item').forEach(item => {
        item.addEventListener('click', () => {
            selectCommand(item.dataset.cmd);
        });
    });
}

function hideCommandAutocomplete() {
    commandAutocomplete.style.display = 'none';
    _acActiveIndex = -1;
    _acFilteredCommands = [];
}

function selectCommand(cmd) {
    // For system commands that don't take args, set and send immediately
    const noArgCmds = ['/help', '/status', '/clear'];
    if (noArgCmds.includes(cmd)) {
        messageInput.value = cmd;
        hideCommandAutocomplete();
        messageInput.focus();
        sendMessage();
    } else {
        messageInput.value = cmd + ' ';
        hideCommandAutocomplete();
        messageInput.focus();
    }
}

function handleAutocompleteKeydown(e) {
    if (commandAutocomplete.style.display === 'none') return false;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        _acActiveIndex = Math.min(_acActiveIndex + 1, _acFilteredCommands.length - 1);
        updateAutocompleteActive();
        return true;
    }
    if (e.key === 'ArrowUp') {
        e.preventDefault();
        _acActiveIndex = Math.max(_acActiveIndex - 1, 0);
        updateAutocompleteActive();
        return true;
    }
    if (e.key === 'Tab' || e.key === 'Enter') {
        if (_acActiveIndex >= 0 && _acActiveIndex < _acFilteredCommands.length) {
            e.preventDefault();
            selectCommand(_acFilteredCommands[_acActiveIndex]);
            return true;
        }
    }
    if (e.key === 'Escape') {
        hideCommandAutocomplete();
        return true;
    }
    return false;
}

function updateAutocompleteActive() {
    const items = commandAutocomplete.querySelectorAll('.command-item');
    items.forEach((item, i) => item.classList.toggle('active', i === _acActiveIndex));
    // Scroll active into view
    if (items[_acActiveIndex]) items[_acActiveIndex].scrollIntoView({ block: 'nearest' });
}

function onMessageInputForAutocomplete() {
    const val = messageInput.value;
    // Show autocomplete when the text is exactly "/" or "/" followed by word characters at the start
    const match = val.match(/^\/(\w*)$/);
    if (match) {
        showCommandAutocomplete(match[1]);
    } else {
        hideCommandAutocomplete();
    }
}


function setupEventListeners() {
    if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggleSidebar);
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);

    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', (e) => {
        // Autocomplete navigation takes priority
        if (handleAutocompleteKeydown(e)) return;
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
        onMessageInputForAutocomplete();
    });

    providerSelect.addEventListener('change', onProviderChange);
    modelSelect.addEventListener('change', () => { modelInput.value = modelSelect.value; updateBadge(); });

    uploadZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileUpload);
    uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
    uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault(); uploadZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; handleFileUpload(); }
    });

    document.getElementById('logout-topbar-btn').addEventListener('click', handleLogout);
    newChatBtn.addEventListener('click', startNewChat);
    settingsBtn.addEventListener('click', () => settingsModal.showModal());
    closeSettingsBtn.addEventListener('click', () => settingsModal.close());
    document.getElementById('cancel-settings-btn2').addEventListener('click', () => settingsModal.close());

    // Back button — returns to welcome screen
    document.getElementById('back-btn').addEventListener('click', goHome);
    // Doc pane toggle
    document.getElementById('close-doc-btn').addEventListener('click', hideDocumentPane);
    document.getElementById('toggle-doc-btn').addEventListener('click', toggleDocumentPane);

    document.querySelectorAll('.prompt-card').forEach(card => {
        card.addEventListener('click', () => {
            messageInput.value = card.getAttribute('data-prompt');
            sendMessage();
        });
    });

    // Close autocomplete on outside click
    document.addEventListener('click', (e) => {
        if (!messageInput.contains(e.target) && !commandAutocomplete.contains(e.target)) {
            hideCommandAutocomplete();
        }
    });
}

function toggleSidebar() {
    if (sidebar) sidebar.classList.toggle('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.toggle('visible');
}

function closeSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('visible');
}

function getSelectedModel() {
    // Prefer dropdown value if visible, otherwise fall back to text input
    if (modelSelect.style.display !== 'none' && modelSelect.value) return modelSelect.value;
    return modelInput.value.trim() || 'llama3';
}
function updateBadge() { badgeText.textContent = `${providerSelect.value} / ${getSelectedModel()}`; }

// Cache for /api/models response
let _modelsCache = null;

async function loadModels() {
    try {
        const resp = await authFetch(`${API}/api/models`);
        _modelsCache = await resp.json();
    } catch (err) {
        console.error("Failed to fetch models, using fallback.", err);
        _modelsCache = {
            "ollama": [],
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            "gemini": ["gemini-2.0-flash", "gemini-2.5-flash-preview-05-20", "gemini-1.5-pro"],
            "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        };
    }
    populateModelDropdown();
}

function populateModelDropdown() {
    const provider = providerSelect.value;
    const models = _modelsCache ? (_modelsCache[provider] || []) : [];

    if (models.length > 0) {
        modelSelect.innerHTML = '';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            modelSelect.appendChild(opt);
        });
        // Preserve current selection if it exists in the list
        const current = modelInput.value.trim();
        if (models.includes(current)) {
            modelSelect.value = current;
        } else {
            modelSelect.value = models[0];
            modelInput.value = models[0];
        }
        modelSelect.style.display = '';
        modelInput.style.display = 'none';
    } else {
        // No known models for this provider — show text input
        modelSelect.style.display = 'none';
        modelInput.value = '';
        modelInput.style.display = '';
    }
    updateBadge();
}

function onProviderChange() {
    const provider = providerSelect.value;
    const defaults = { ollama: 'llama3', openai: 'gpt-4o', gemini: 'gemini-2.0-flash', groq: 'llama-3.3-70b-versatile' };
    modelInput.value = defaults[provider] || 'llama3';
    if (_modelsCache) {
        populateModelDropdown();
    } else {
        loadModels();
    }
}

async function checkExistingDocument() {
    if (!conversationId) {
        uploadZone.classList.remove('uploaded');
        document.getElementById('upload-label').textContent = 'Upload File';
        hideDocumentPane();
        return;
    }
    
    try {
        const resp = await authFetch(`${API}/api/status?conversation_id=${conversationId}`);
        const data = await resp.json();
        if (data.document_loaded) {
            uploadZone.classList.add('uploaded');
            document.getElementById('upload-label').textContent = data.document_loaded;
            
            const docResp = await authFetch(`${API}/api/document?conversation_id=${conversationId}`);
            if (docResp.ok) {
                const docData = await docResp.json();
                showDocumentPane(docData.text);
            }
        } else {
            uploadZone.classList.remove('uploaded');
            document.getElementById('upload-label').textContent = 'Upload File';
            hideDocumentPane();
        }
    } catch (e) {
        uploadZone.classList.remove('uploaded');
        document.getElementById('upload-label').textContent = 'Upload File';
        hideDocumentPane();
    }
}

async function handleFileUpload() {
    const file = fileInput.files[0];
    if (!file) return;

    setUploadStatus('Processing...', 'loading');
    if (uploadProgress) uploadProgress.style.width = '30%';

    const formData = new FormData();
    formData.append('file', file);
    if (conversationId) {
        formData.append('conversation_id', conversationId);
    }

    try {
        if (uploadProgress) uploadProgress.style.width = '60%';
        const resp = await authFetch(`${API}/api/upload`, {
            method: 'POST',
            body: formData,
        });
        if (uploadProgress) uploadProgress.style.width = '100%';
        const data = await resp.json();

        if (resp.ok) {
            setUploadStatus(`${data.filename} loaded`, 'success');
            uploadZone.classList.add('uploaded');
            document.getElementById('upload-label').textContent = file.name;
            setTimeout(() => { if (uploadProgress) uploadProgress.style.width = '0%'; }, 500);
            
            if (data.conversation_id && data.conversation_id !== conversationId) {
                conversationId = data.conversation_id;
                loadConversations();
            }
            
            checkExistingDocument();
        } else {
            setUploadStatus(`Error: ${data.detail}`, 'error');
            if (uploadProgress) uploadProgress.style.width = '0%';
        }
    } catch (err) {
        setUploadStatus(`Failed: ${err.message}`, 'error');
        if (uploadProgress) uploadProgress.style.width = '0%';
    }
}

function setUploadStatus(text, type) {
    uploadStatus.textContent = text;
    uploadStatus.className = `upload-status ${type}`;
}

function showDocumentPane(text) {
    docPane.style.display = 'flex';
    docPane.style.flexDirection = 'column';
    if (!docPane.style.width || docPane.style.width === '0px') {
        docPane.style.width = '38%';
    }
    docContent.textContent = text;

    // Show resizer and toggle button
    const resizer = document.getElementById('pane-resizer');
    const toggleBtn = document.getElementById('toggle-doc-btn');
    if (resizer) resizer.style.display = '';
    if (toggleBtn) toggleBtn.style.display = '';
}

function hideDocumentPane() {
    docPane.style.display = 'none';
    const resizer = document.getElementById('pane-resizer');
    if (resizer) resizer.style.display = 'none';
}

function toggleDocumentPane() {
    if (docPane.style.display === 'none' || !docPane.style.display) {
        docPane.style.display = 'flex';
        docPane.style.flexDirection = 'column';
        if (!docPane.style.width || docPane.style.width === '0px') docPane.style.width = '38%';
        document.getElementById('pane-resizer').style.display = '';
    } else {
        hideDocumentPane();
    }
}

// ── Pane Resizer ──────────────────────────────────────────────────────────────
(function initResizer() {
    const resizer = document.getElementById('pane-resizer');
    const workspace = document.querySelector('.workspace');
    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = docPane.offsetWidth;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const dx = e.clientX - startX;
        const newWidth = Math.max(180, Math.min(startWidth + dx, workspace.offsetWidth - 300));
        docPane.style.width = newWidth + 'px';
        docPane.style.flex = 'none';
    });

    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
})();

async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;
    hideCommandAutocomplete();
    if (welcomeScreen) welcomeScreen.style.display = 'none';

    // ── /clear interception: handle entirely client-side ──────────────
    if (text.toLowerCase() === '/clear') {
        if (conversationId) {
            try {
                await authFetch(`${API}/api/conversations/${conversationId}`, { method: 'DELETE' });
            } catch (e) { /* ignore */ }
        }
        conversationId = null;
        messagesContainer.innerHTML = '';
        if (welcomeScreen) { messagesContainer.appendChild(welcomeScreen); welcomeScreen.style.display = ''; }
        messageInput.value = ''; messageInput.style.height = 'auto';
        document.getElementById('back-btn').style.display = 'none';
        loadConversations();
        messageInput.focus();
        return;
    }

    addMessage('user', text);
    messageInput.value = ''; messageInput.style.height = 'auto'; sendBtn.disabled = true;
    // Show back button when entering chat view
    document.getElementById('back-btn').style.display = 'flex';
    const typingEl = showTyping();

    try {
        const resp = await authFetch(`${API}/api/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                provider: providerSelect.value,
                model: getSelectedModel(),
                conversation_id: conversationId
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            typingEl.remove();
            addMessage('assistant', `Error: ${err.detail}`, 'error');
            sendBtn.disabled = false; messageInput.focus();
            return;
        }

        typingEl.remove();

        // Create streaming message bubble
        const msgEl = document.createElement('div');
        msgEl.className = 'message assistant';
        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar router';
        avatar.textContent = 'AI';
        const bubble = document.createElement('div');
        bubble.className = 'msg-body streaming';
        msgEl.appendChild(avatar);
        msgEl.appendChild(bubble);
        messagesContainer.appendChild(msgEl);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Read SSE stream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullText = '';
        let intent = 'unknown';
        let metaInfo = {};

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const rawChunk = decoder.decode(value, { stream: true });
            const lines = rawChunk.split('\n');

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const event = JSON.parse(line.slice(6));

                    if (event.type === 'intent') {
                        intent = event.intent;
                        conversationId = event.conversation_id;
                        // Update avatar icon based on intent
                        const icons = { summary: 'S', suggestion: 'G', modification: 'M' };
                        avatar.textContent = icons[intent] || 'AI';
                        avatar.className = `msg-avatar assistant ${intent}`;

                    } else if (event.type === 'token') {
                        fullText += event.token;
                        // Render markdown progressively
                        if (window.marked) {
                            bubble.innerHTML = marked.parse(fullText);
                        } else {
                            bubble.textContent = fullText;
                        }
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;

                    } else if (event.type === 'done') {
                        metaInfo = event;
                        bubble.classList.remove('streaming');
                        // Append metadata
                        const meta = document.createElement('div');
                        meta.className = 'msg-meta';
                        meta.innerHTML = `<span>${event.provider}/${event.model}</span><span class="metric">${(event.latency_ms / 1000).toFixed(1)}s</span><span class="intent-pill ${intent}">${intent}</span>`;
                        bubble.appendChild(meta);
                        // Refresh conversation list so new chat appears in sidebar
                        loadConversations();
                        // Update document pane visibility in case conversation ID changed
                        checkExistingDocument();

                    } else if (event.type === 'error') {
                        bubble.textContent = `Error: ${event.detail}`;
                    }
                } catch (e) { /* skip malformed events */ }
            }
        }
    } catch (err) {
        typingEl.remove();
        addMessage('assistant', `Error: ${err.message}`, 'error');
    }
    sendBtn.disabled = false; messageInput.focus();
}

function addMessage(role, content, intent, provider, model, latency_ms) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    
    const avatar = document.createElement('div');
    
    let aiClass = 'msg-avatar assistant';
    let aiIcon = 'AI';
    
    if (intent === 'summary') {
        aiClass += ' summary';
        aiIcon = 'S';
    } else if (intent === 'suggestion') {
        aiClass += ' suggestion';
        aiIcon = 'G';
    } else if (intent === 'modification') {
        aiClass += ' modification';
        aiIcon = 'M';
    }

    avatar.className = role === 'user' ? 'msg-avatar' : aiClass;
    avatar.textContent = role === 'user' ? 'U' : aiIcon;

    const bubble = document.createElement('div');
    bubble.className = 'msg-body';
    
    if (role === 'assistant' && window.marked) {
        bubble.innerHTML = marked.parse(content);
    } else {
        bubble.textContent = content;
    }

    msg.appendChild(avatar); msg.appendChild(bubble);

    if (role === 'assistant' && intent && intent !== 'error') {
        const meta = document.createElement('div');
        meta.className = 'msg-meta';
        let metaHtml = `<span>${provider}/${model}</span>`;
        if (latency_ms) metaHtml += `<span class="metric">${(latency_ms / 1000).toFixed(1)}s</span>`;
        metaHtml += `<span class="intent-pill ${intent}">${intent}</span>`;
        meta.innerHTML = metaHtml;
        bubble.appendChild(meta);
    }

    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTyping() {
    const msg = document.createElement('div'); 
    msg.className = 'message assistant';
    
    msg.innerHTML = `
        <div class="msg-avatar router">AI</div>
        <div class="msg-body">
            <div class="routing-container" id="routing-container">
                <div class="routing-step">
                    <span class="routing-spinner"></span>
                    <span>Router analyzing intent...</span>
                </div>
            </div>
        </div>
    `;
    
    messagesContainer.appendChild(msg); 
    messagesContainer.scrollTop = messagesContainer.scrollHeight; 
    
    setTimeout(() => {
        const container = msg.querySelector('#routing-container');
        if(container) {
            container.innerHTML += `
                <div class="routing-step mt-2" style="color: var(--blue);">
                    <span class="routing-spinner"></span>
                    <span>Routing to Specialist Agent...</span>
                </div>
            `;
            messagesContainer.scrollTop = messagesContainer.scrollHeight; 
        }
    }, 1500);

    return msg;
}
