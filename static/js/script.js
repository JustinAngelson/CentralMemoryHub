// Central Memory Hub - Client-side JavaScript

// DOM elements
const apiKeyInput = document.getElementById('apiKeyInput');
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
const toast = new bootstrap.Toast(errorToast);

// Retrieve API key from local storage or prompt user
let apiKey = localStorage.getItem('memoryHubApiKey');

// Function to show error message
function showError(message) {
    errorToastBody.textContent = message;
    toast.show();
}

// Function to make API requests
async function makeApiRequest(endpoint, method, data = null) {
    try {
        // Ensure we have an API key
        if (!apiKey) {
            apiKey = prompt('Please enter your API key:');
            if (apiKey) {
                localStorage.setItem('memoryHubApiKey', apiKey);
            } else {
                showError('API key is required');
                return null;
            }
        }

        // Prepare request options
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-API-KEY': apiKey
            }
        };

        if (data && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(data);
        }

        // Make the request
        const response = await fetch(endpoint, options);
        
        // Handle API key errors
        if (response.status === 401) {
            localStorage.removeItem('memoryHubApiKey');
            apiKey = null;
            showError('Invalid API key. Please try again.');
            return null;
        }
        
        // Parse and return the JSON response
        const responseData = await response.json();
        
        // Check for API errors
        if (!response.ok) {
            throw new Error(responseData.error || 'API request failed');
        }
        
        return responseData;
    } catch (error) {
        showError(`Error: ${error.message}`);
        console.error('API Request Error:', error);
        return null;
    }
}

// Generate placeholder embeddings for structured data
// (In a real app, this would be handled by the server)
function generatePlaceholderEmbedding() {
    const embedding = [];
    for (let i = 0; i < 10; i++) {
        embedding.push(Math.random());
    }
    return embedding;
}

// Handle unstructured data form submission
if (unstructuredForm) {
    unstructuredForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const content = document.getElementById('content').value.trim();
        
        if (!content) {
            showError('Content is required');
            return;
        }
        
        const data = { content };
        const result = await makeApiRequest('/memory/unstructured', 'POST', data);
        
        if (result) {
            unstructuredId.textContent = result.id;
            pineconeId.textContent = result.pinecone_id;
            unstructuredResult.classList.remove('d-none');
            unstructuredForm.reset();
        }
    });
}

// Handle search form submission
if (searchForm) {
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = document.getElementById('searchQuery').value.trim();
        
        if (!query) {
            showError('Search query is required');
            return;
        }
        
        const data = { query };
        const result = await makeApiRequest('/search', 'POST', data);
        
        if (result) {
            // Clear previous results
            resultsList.innerHTML = '';
            
            if (result.results.length === 0) {
                resultsList.innerHTML = '<div class="list-group-item">No results found</div>';
            } else {
                // Display search results
                result.results.forEach(item => {
                    const score = (item.similarity_score * 100).toFixed(2);
                    const contentPreview = item.content.length > 150 
                        ? item.content.substring(0, 150) + '...' 
                        : item.content;
                    
                    const resultItem = document.createElement('div');
                    resultItem.className = 'list-group-item';
                    resultItem.innerHTML = `
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h6>ID: ${item.id}</h6>
                                <p class="mb-1">${contentPreview}</p>
                            </div>
                            <span class="badge bg-primary similarity-score">${score}%</span>
                        </div>
                    `;
                    resultsList.appendChild(resultItem);
                });
            }
            
            searchResults.classList.remove('d-none');
        }
    });
}

// Handle structured data form submission
if (structuredForm) {
    structuredForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const gptRole = document.getElementById('gptRole').value.trim();
        const decisionText = document.getElementById('decisionText').value.trim();
        const relatedDocuments = document.getElementById('relatedDocuments').value
            .split(',')
            .map(doc => doc.trim())
            .filter(doc => doc);
        
        if (!gptRole || !decisionText) {
            showError('GPT Role and Decision Text are required');
            return;
        }
        
        // Generate placeholder embedding
        const contextEmbedding = generatePlaceholderEmbedding();
        
        const data = {
            gpt_role: gptRole,
            decision_text: decisionText,
            context_embedding: contextEmbedding,
            related_documents: relatedDocuments
        };
        
        const result = await makeApiRequest('/memory/structured', 'POST', data);
        
        if (result) {
            structuredId.textContent = result.id;
            structuredResult.classList.remove('d-none');
            structuredForm.reset();
        }
    });
}

// Handle context form submission
if (contextForm) {
    contextForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const sender = document.getElementById('sender').value.trim();
        const recipients = document.getElementById('recipients').value
            .split(',')
            .map(r => r.trim())
            .filter(r => r);
        const contextTag = document.getElementById('contextTag').value.trim();
        const memoryRefs = document.getElementById('memoryRefs').value
            .split(',')
            .map(m => m.trim())
            .filter(m => m);
        
        if (!sender || !contextTag || recipients.length === 0) {
            showError('Sender, Context Tag, and at least one Recipient are required');
            return;
        }
        
        const data = {
            sender: sender,
            recipients: recipients,
            context_tag: contextTag,
            memory_refs: memoryRefs
        };
        
        const result = await makeApiRequest('/context', 'POST', data);
        
        if (result) {
            contextId.textContent = result.id;
            contextResult.classList.remove('d-none');
            contextForm.reset();
        }
    });
}

// Initialize Feather icons
document.addEventListener('DOMContentLoaded', () => {
    feather.replace();
});
