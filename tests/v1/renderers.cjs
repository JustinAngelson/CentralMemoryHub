const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const attack = '<img src=x onerror=alert(1)>';
const quoteAttack = `"><img src=x onerror=alert(1)>`;
const escapeSource = fs.readFileSync(path.join(root, 'static/js/security.js'), 'utf8');

function setup(filename, status = 200) {
    class Modal {
        show() {}
        hide() {}
        static getOrCreateInstance() { return new Modal(); }
    }
    const nodes = new Map();
    function node(id) {
        if (!nodes.has(id)) nodes.set(id, {
            innerHTML: '', textContent: '', value: '', children: [], dataset: {}, callbacks: {},
            classList: {add() {}, remove() {}}, addEventListener(name, fn) {this.callbacks[name] = fn;},
            appendChild(child) {this.children.push(child);}, querySelectorAll() {return [];},
        });
        return nodes.get(id);
    }
    const context = vm.createContext({
        document: {
            addEventListener() {}, getElementById: node, createElement: () => node(Symbol()),
            querySelectorAll: () => [],
        },
        window: {addEventListener() {}},
        feather: {replace() {}},
        bootstrap: {Modal},
        navigator: {clipboard: {writeText: async () => {}}},
        console, fetch: async () => ({
            ok: status === 200, status, json: async () => ({ok: false, error: 'Check your input'}),
        }),
    });
    vm.runInContext(escapeSource, context);
    const template = fs.readFileSync(path.join(root, 'templates', filename), 'utf8');
    for (const match of template.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
        if (!match[1].trim()) continue;
        const js = match[1].replace(/\{\{[\s\S]*?\}\}/g, 'null').replace(/\{%[\s\S]*?%\}/g, '');
        vm.runInContext(js, context, {filename});
    }
    return {context, node};
}

const agent = {
    agent_id: quoteAttack, name: attack, role: attack, status: attack, agent_type: attack,
    seniority_level: attack, reports_to: attack, description: attack, capabilities: [attack], skills: [attack],
};
const agents = setup('agent_view.html');
agents.context.inputAgent = agent;
vm.runInContext('allAgents = [inputAgent]; renderAgentTable(allAgents); openViewAgentModal(inputAgent.agent_id);', agents.context);
const table = agents.node('agentTableBody').children.map(child => child.innerHTML).join('');
const modal = agents.node('viewAgentBody').innerHTML;
const hierarchy = vm.runInContext('createHierarchyNode(inputAgent).innerHTML', agents.context);
for (const fragment of [table, modal, hierarchy]) {
    assert(!fragment.includes(attack));
    assert(fragment.includes('&lt;img'));
}
assert(!table.includes('onclick='));
assert(table.includes('&quot;&gt;&lt;img'));

const keys = setup('api_keys.html');
keys.context.testKey = {key_id: quoteAttack, name: attack, rate_limit: attack, is_active: true};
keys.context.testLog = {
    api_key_id: attack, method: attack, endpoint: attack, status_code: attack, ip_address: attack,
};
vm.runInContext('apiKeys = [testKey]; apiLogs = [testLog]; populateApiKeysTable(); populateApiLogsTable();', keys.context);
for (const id of ['apiKeysTable', 'apiLogsTable']) {
    const fragment = keys.node(id).innerHTML;
    assert(!fragment.includes(attack));
    assert(fragment.includes('&lt;img'));
    assert(!fragment.includes('onclick='));
}

const searchScript = fs.readFileSync(path.join(root, 'static/js/script.js'), 'utf8');
new vm.Script(searchScript);
const searchExpression = searchScript.match(/el\.innerHTML = (`[\s\S]*?`);/)[1];
const search = vm.runInNewContext(escapeSource + `
    const item = {id: ${JSON.stringify(attack)}};
    const preview = ${JSON.stringify(attack)}, score = 100;
    ${searchExpression};`);
assert(!search.includes(attack));
assert(search.includes('&lt;img'));

(async () => {
    for (const status of [400, 429]) {
        const ui = setup('landing.html', status);
        ui.node('wlFirstName').value = 'owner';
        ui.node('wlEmail').value = 'owner@example.com';
        const button = ui.node('wlSubmitBtn');
        button.callbacks.click.call(button);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(ui.node('wlSubmitBtn').disabled, false);
        assert.equal(ui.node('wlError').textContent,
            status === 429 ? 'Too many submissions. Please try again later.' : 'Check your input');
    }
    console.log('safe renderers and 400/429 UI: PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
