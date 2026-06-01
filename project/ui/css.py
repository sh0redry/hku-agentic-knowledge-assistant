custom_css = """
:root {
    --app-bg: #f6f7fb;
    --panel-bg: #ffffff;
    --text-main: #111827;
    --text-muted: #5b6475;
    --border: #d9deea;
    --border-strong: #c4cbda;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --danger: #dc2626;
    --user-bg: #2563eb;
    --assistant-bg: #ffffff;
    --thinking-bg: #eef2ff;
    --shadow: 0 14px 38px rgba(17, 24, 39, 0.08);
}

.progress-text,
footer {
    display: none !important;
}

body,
.gradio-container {
    background: var(--app-bg) !important;
    color: var(--text-main) !important;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}

.gradio-container {
    max-width: 1180px !important;
    min-height: 100vh !important;
    margin: 0 auto !important;
    padding: 24px 18px !important;
}

.tabs {
    background: var(--panel-bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    box-shadow: var(--shadow) !important;
    overflow: hidden !important;
}

.tab-nav {
    background: #f9fafc !important;
    border-bottom: 1px solid var(--border) !important;
    padding: 8px 10px 0 !important;
    gap: 6px !important;
}

button[role="tab"] {
    min-height: 42px !important;
    padding: 10px 16px !important;
    color: var(--text-muted) !important;
    border: 1px solid transparent !important;
    border-bottom: none !important;
    border-radius: 10px 10px 0 0 !important;
    background: transparent !important;
    font-weight: 650 !important;
}

button[role="tab"][aria-selected="true"] {
    color: var(--text-main) !important;
    background: var(--panel-bg) !important;
    border-color: var(--border) !important;
}

button {
    border-radius: 10px !important;
    font-weight: 650 !important;
    min-height: 40px !important;
    box-shadow: none !important;
}

button.primary,
.primary {
    background: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    color: #ffffff !important;
}

button.primary:hover,
.primary:hover {
    background: var(--accent-hover) !important;
    border-color: var(--accent-hover) !important;
}

button.stop,
.stop {
    background: #fff1f2 !important;
    color: var(--danger) !important;
    border: 1px solid #fecdd3 !important;
}

button.stop:hover,
.stop:hover {
    background: #ffe4e6 !important;
}

#doc-management-tab {
    max-width: 760px !important;
    margin: 0 auto !important;
    padding: 30px 20px !important;
}

h1, h2, h3, h4, h5, h6,
.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
    color: var(--text-main) !important;
    letter-spacing: 0 !important;
}

p, label, span, .markdown-body, .prose {
    color: var(--text-muted) !important;
}

input,
textarea,
[data-testid="textbox"] textarea {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    color: var(--text-main) !important;
    font-size: 15px !important;
    line-height: 1.55 !important;
}

input:focus,
textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14) !important;
    outline: none !important;
}

.file-preview,
[data-testid="file-upload"] {
    background: #fbfcff !important;
    border: 1.5px dashed var(--border-strong) !important;
    border-radius: 12px !important;
    color: var(--text-main) !important;
    min-height: 180px !important;
}

.file-preview:hover,
[data-testid="file-upload"]:hover {
    border-color: var(--accent) !important;
    background: #f8fbff !important;
}

.file-preview *,
[data-testid="file-upload"] * {
    color: var(--text-main) !important;
}

#file-list-box {
    background: #fbfcff !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}

#file-list-box textarea {
    color: var(--text-main) !important;
    background: transparent !important;
    border: none !important;
}

.chatbot {
    height: calc(100vh - 210px) !important;
    min-height: 620px !important;
    background: #f8f9fc !important;
    border: none !important;
    border-radius: 0 !important;
}

.chatbot .message-wrap,
.chatbot > div {
    padding: 18px !important;
}

.message {
    border-radius: 16px !important;
    padding: 12px 15px !important;
    font-size: 15px !important;
    line-height: 1.65 !important;
    box-shadow: 0 3px 14px rgba(17, 24, 39, 0.05) !important;
}

.message.user {
    background: var(--user-bg) !important;
    color: #ffffff !important;
    border: 1px solid var(--user-bg) !important;
}

.message.user * {
    color: #ffffff !important;
}

.message.bot {
    background: var(--assistant-bg) !important;
    color: var(--text-main) !important;
    border: 1px solid var(--border) !important;
    max-width: min(780px, 88%) !important;
}

.message.bot * {
    color: var(--text-main) !important;
}

.message.bot details,
.message.bot[data-testid*="bot"] details {
    background: var(--thinking-bg) !important;
    border: 1px solid #dbe4ff !important;
    border-radius: 12px !important;
    padding: 10px 12px !important;
}

.message.bot summary {
    color: #334155 !important;
    font-weight: 650 !important;
}

.avatar-container img,
.message-row img {
    border-radius: 999px !important;
    padding: 0 !important;
}

form:has(textarea[placeholder="Type a message..."]) {
    background: var(--panel-bg) !important;
    border-top: 1px solid var(--border) !important;
    padding: 14px 18px 18px !important;
    gap: 10px !important;
}

form:has(textarea[placeholder="Type a message..."]) textarea {
    min-height: 48px !important;
    max-height: 180px !important;
    border-radius: 16px !important;
    padding: 12px 14px !important;
}

form:has(textarea[placeholder="Type a message..."]) button {
    border-radius: 14px !important;
    min-width: 48px !important;
    height: 48px !important;
    background: var(--accent) !important;
    color: #ffffff !important;
    border: 1px solid var(--accent) !important;
}

code,
pre {
    background: #f1f5f9 !important;
    color: #0f172a !important;
    border-radius: 8px !important;
}

@media (max-width: 720px) {
    .gradio-container {
        padding: 8px !important;
    }

    .tabs {
        border-radius: 0 !important;
        min-height: 100vh !important;
    }

    .chatbot {
        min-height: calc(100vh - 180px) !important;
    }

    .message.bot,
    .message.user {
        max-width: 94% !important;
    }
}
"""
