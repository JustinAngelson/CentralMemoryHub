/* Shared HTML-text/quoted-attribute escaping. Never use this for JS or URLs. */
function escapeHtml(value) {
    const entities = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    return String(value ?? '').replace(/[&<>"']/g, char => entities[char]);
}

function renderSessionMessages(messages) {
    return messages.map(message => {
        let badge = 'bg-secondary';
        if (message.message_type === 'instruction') badge = 'bg-primary';
        if (message.message_type === 'handoff') badge = 'bg-warning text-dark';
        if (message.message_type === 'question') badge = 'bg-info text-dark';
        return `<div class="card mb-2"><div class="card-body py-2 px-3">
            <div class="d-flex justify-content-between align-items-center mb-1">
                <span class="small"><strong>${escapeHtml(message.sender_agent)}</strong>
                → <strong>${escapeHtml(message.receiver_agent || 'broadcast')}</strong></span>
                <span class="badge ${badge}">${escapeHtml(message.message_type)}</span>
            </div>
            <p class="mb-1 small">${escapeHtml(message.content)}</p>
            <span class="text-muted" style="font-size:.75rem;">${escapeHtml(new Date(message.timestamp).toLocaleString())}</span>
        </div></div>`;
    }).join('');
}

if (typeof document !== 'undefined') {
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-agent-action]');
        if (button) {
            const action = button.dataset.agentAction;
            if (action === 'view') window.handleViewAgent(button.dataset.agentId);
            if (action === 'edit') window.handleEditAgent(button.dataset.agentId);
            if (action === 'delete') window.handleDeleteAgent(button.dataset.agentId);
        }
        const copy = event.target.closest('[data-copy-url]');
        if (copy) {
            navigator.clipboard.writeText(copy.dataset.copyUrl)
                .then(() => { copy.textContent = 'Copied!'; });
        }
    });
    document.addEventListener('submit', event => {
        const form = event.target.closest('form[data-confirm]');
        if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
    });
}
