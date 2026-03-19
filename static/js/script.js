// Central Memory Hub - Client-side JavaScript

// DOM elements
const unstructuredForm = document.getElementById('unstructuredForm');
const searchForm = document.getElementById('searchForm');
const structuredForm = document.getElementById('structuredForm');
const contextForm = document.getElementById('contextForm');

// Result containers
const unstructuredResult = document.getElementById('unstructuredResult');
const unstructuredId = document.getElementById('unstructuredId');
const pineconeId = document.getElementById('pineconeId');
const searchResults = document.getElementById('searchResults');
const resultsList = document.getElementById('resultsList');
const structuredResult = document.getElementById('structuredResult');
const structuredId = document.getElementById('structuredId');
const contextResult = document.getElementById('contextResult');
const contextId = document.getElementById('contextId');

// Error toast elements
const errorToast = document.getElementById('errorToast');
const errorToastBody = document.getElementById('errorToastBody');

// Create a Bootstrap toast instance
const toast = errorToast ? new bootstrap.Toast(errorToast) : null;

function showError(message) {
    if (toast && errorToastBody) {
        errorToastBody.textContent = message;
        toast.show();
    } else {
        console.error(message);
    }
}

// Make API requests using session auth (no API key needed for logged-in users)
async function makeApiRequest(endpoint, method, data = null) {
    try {
        const options = {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin'
        };

        if (data && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(data);
        }

        const response = await fetch(endpoint, options);

        if (response.status === 401 || response.status === 302) {
            showError('Session expired. Please log in again.');
            setTimeout(() => { window.location.href = '/login'; }, 1500);
            return null;
        }

        if (response.status === 403) {
            showError('You do not have permission to perform this action.');
            return null;
        }

        const responseData = await response.json();

        if (!response.ok) {
            throw new Error(responseData.error || 'Request failed');
        }

        return responseData;
    } catch (error) {
        showError(`Error: ${error.message}`);
        console.error('API Request Error:', error);
        return null;
    }
}

function generatePlaceholderEmbedding() {
    const embedding = [];
    for (let i = 0; i < 10; i++) embedding.push(Math.random());
    return embedding;
}

// Unstructured data form
if (unstructuredForm) {
    unstructuredForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const content = document.getElementById('content').value.trim();
        if (!content) { showError('Content is required'); return; }

        const result = await makeApiRequest('/memory/unstructured', 'POST', { content });
        if (result) {
            unstructuredId.textContent = result.id;
            pineconeId.textContent = result.pinecone_id;
            unstructuredResult.classList.remove('d-none');
            unstructuredForm.reset();
        }
    });
}

// Search form
if (searchForm) {
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = document.getElementById('searchQuery').value.trim();
        if (!query) { showError('Search query is required'); return; }

        const result = await makeApiRequest('/search', 'POST', { query });
        if (result) {
            resultsList.innerHTML = '';
            if (result.results.length === 0) {
                resultsList.innerHTML = '<div class="list-group-item">No results found</div>';
            } else {
                result.results.forEach(item => {
                    const score = (item.similarity_score * 100).toFixed(2);
                    const preview = item.content.length > 150
                        ? item.content.substring(0, 150) + '...'
                        : item.content;
                    const el = document.createElement('div');
                    el.className = 'list-group-item';
                    el.innerHTML = `
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h6>ID: ${item.id}</h6>
                                <p class="mb-1">${preview}</p>
                            </div>
                            <span class="badge bg-primary">${score}%</span>
                        </div>`;
                    resultsList.appendChild(el);
                });
            }
            searchResults.classList.remove('d-none');
        }
    });
}

// Structured data form
if (structuredForm) {
    structuredForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const gptRole = document.getElementById('gptRole').value.trim();
        const decisionText = document.getElementById('decisionText').value.trim();
        const relatedDocuments = document.getElementById('relatedDocuments').value
            .split(',').map(d => d.trim()).filter(d => d);

        if (!gptRole || !decisionText) {
            showError('GPT Role and Decision Text are required');
            return;
        }

        const result = await makeApiRequest('/memory/structured', 'POST', {
            gpt_role: gptRole,
            decision_text: decisionText,
            context_embedding: generatePlaceholderEmbedding(),
            related_documents: relatedDocuments
        });
        if (result) {
            structuredId.textContent = result.id;
            structuredResult.classList.remove('d-none');
            structuredForm.reset();
        }
    });
}

// Context form
if (contextForm) {
    contextForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const sender = document.getElementById('sender').value.trim();
        const recipients = document.getElementById('recipients').value
            .split(',').map(r => r.trim()).filter(r => r);
        const contextTag = document.getElementById('contextTag').value.trim();
        const memoryRefs = document.getElementById('memoryRefs').value
            .split(',').map(m => m.trim()).filter(m => m);

        if (!sender || !contextTag || recipients.length === 0) {
            showError('Sender, Context Tag, and at least one Recipient are required');
            return;
        }

        const result = await makeApiRequest('/context', 'POST', {
            sender, recipients, context_tag: contextTag, memory_refs: memoryRefs
        });
        if (result) {
            contextId.textContent = result.id;
            contextResult.classList.remove('d-none');
            contextForm.reset();
        }
    });
}

// Initialize Feather icons
document.addEventListener('DOMContentLoaded', () => {
    if (typeof feather !== 'undefined') feather.replace();
});
