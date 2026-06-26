import * as vscode from "vscode";

// ─── config helpers ──────────────────────────────────────────────────────────

function cfg() {
  return vscode.workspace.getConfiguration("sensei");
}
function gatewayUrl(): string {
  return cfg().get<string>("gatewayUrl", "http://localhost:7000").replace(/\/$/, "");
}
function backendUrl(): string {
  return cfg().get<string>("backendUrl", "http://localhost:7000").replace(/\/$/, "");
}

function platformEnvKey(): string {
  switch (process.platform) {
    case "win32":
      return "terminal.integrated.env.windows";
    case "darwin":
      return "terminal.integrated.env.osx";
    default:
      return "terminal.integrated.env.linux";
  }
}

/** Add or remove env vars on the integrated-terminal environment so CLI agents
 *  (Claude Code, Codex) launched there automatically route through Sensei. */
async function setTerminalEnv(updates: Record<string, string | undefined>): Promise<void> {
  const key = platformEnvKey();
  const conf = vscode.workspace.getConfiguration();
  const current = { ...(conf.get<Record<string, string>>(key) ?? {}) };
  for (const [k, v] of Object.entries(updates)) {
    if (v === undefined) delete current[k];
    else current[k] = v;
  }
  await conf.update(key, current, vscode.ConfigurationTarget.Global);
}

// ─── Sensei backend client ───────────────────────────────────────────────────

interface Savings {
  tokens_saved: number;
  percent_saved: number;
  estimated_cost_saved_usd: number;
  requests: number;
}

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as T;
}

async function fetchSavings(): Promise<Savings | null> {
  try {
    const data = await getJson<{ savings?: Savings }>(`${backendUrl()}/api/stats`);
    return data.savings ?? null;
  } catch {
    return null;
  }
}

async function fetchModels(): Promise<{ id: string; name: string }[]> {
  try {
    const data = await getJson<{ models: { id: string; name: string }[] }>(
      `${backendUrl()}/api/models`
    );
    return data.models ?? [];
  } catch {
    return [];
  }
}

async function sendChat(
  message: string,
  model?: string,
  conversationId?: string
): Promise<{ message: string; tokens_saved: number; conversation_id: string }> {
  const resp = await fetch(`${backendUrl()}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, model, conversation_id: conversationId }),
  });
  if (!resp.ok) throw new Error(`Sensei backend HTTP ${resp.status}`);
  return (await resp.json()) as any;
}

// ─── status bar ──────────────────────────────────────────────────────────────

let statusItem: vscode.StatusBarItem;
let pollTimer: NodeJS.Timeout | undefined;

async function refreshStatus(): Promise<void> {
  const s = await fetchSavings();
  if (!s) {
    statusItem.text = "$(zap) Sensei: offline";
    statusItem.tooltip = "Sensei backend not reachable. Start it with `uvicorn sensei.main:app`.";
    return;
  }
  const usd = s.estimated_cost_saved_usd.toFixed(2);
  statusItem.text = `$(zap) ${s.percent_saved}% · $${usd}`;
  statusItem.tooltip =
    `Sensei saved ${s.tokens_saved.toLocaleString()} tokens ` +
    `(~$${usd}) across ${s.requests} requests.`;
}

function startPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  const secs = Math.max(5, cfg().get<number>("pollSeconds", 15));
  refreshStatus();
  pollTimer = setInterval(refreshStatus, secs * 1000);
}

// ─── chat webview ────────────────────────────────────────────────────────────

class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "sensei.chatView";
  private conversationId: string | undefined;

  constructor(private readonly extensionUri: vscode.Uri) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    view.webview.options = { enableScripts: true };
    view.webview.html = this.html(view.webview);

    view.webview.onDidReceiveMessage(async (msg) => {
      if (msg.type === "ready") {
        view.webview.postMessage({ type: "models", models: await fetchModels() });
      } else if (msg.type === "send") {
        try {
          const reply = await sendChat(msg.text, msg.model, this.conversationId);
          this.conversationId = reply.conversation_id;
          view.webview.postMessage({
            type: "reply",
            text: reply.message,
            tokensSaved: reply.tokens_saved,
          });
        } catch (e: any) {
          view.webview.postMessage({ type: "error", text: String(e?.message ?? e) });
        }
      } else if (msg.type === "newChat") {
        this.conversationId = undefined;
      }
    });
  }

  private html(webview: vscode.Webview): string {
    const nonce = Math.random().toString(36).slice(2);
    const csp =
      `default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; ` +
      `script-src 'nonce-${nonce}';`;
    return /* html */ `<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground);
         margin: 0; padding: 8px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
  #log { flex: 1; overflow-y: auto; font-size: 13px; }
  .msg { margin: 6px 0; padding: 6px 8px; border-radius: 6px; white-space: pre-wrap; }
  .user { background: var(--vscode-input-background); }
  .bot { background: var(--vscode-editorWidget-background); }
  .meta { font-size: 10px; opacity: 0.6; }
  .row { display: flex; gap: 6px; margin-top: 6px; }
  textarea { flex: 1; resize: none; background: var(--vscode-input-background);
             color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border);
             border-radius: 4px; padding: 6px; font-family: inherit; }
  select, button { background: var(--vscode-button-background); color: var(--vscode-button-foreground);
                   border: none; border-radius: 4px; padding: 4px 8px; cursor: pointer; }
  #bar { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
</style></head><body>
  <div id="bar">
    <select id="model"></select>
    <button id="new">New</button>
  </div>
  <div id="log"></div>
  <div class="row">
    <textarea id="input" rows="2" placeholder="Ask Sensei… (prompts are compressed before sending)"></textarea>
    <button id="send">Send</button>
  </div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const modelSel = document.getElementById('model');
  function add(text, cls, meta) {
    const d = document.createElement('div'); d.className = 'msg ' + cls; d.textContent = text;
    if (meta) { const m = document.createElement('div'); m.className = 'meta'; m.textContent = meta; d.appendChild(m); }
    log.appendChild(d); log.scrollTop = log.scrollHeight;
  }
  function send() {
    const text = input.value.trim(); if (!text) return;
    add(text, 'user'); input.value = '';
    vscode.postMessage({ type: 'send', text, model: modelSel.value || undefined });
  }
  document.getElementById('send').addEventListener('click', send);
  document.getElementById('new').addEventListener('click', () => { log.innerHTML=''; vscode.postMessage({type:'newChat'}); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  window.addEventListener('message', (e) => {
    const m = e.data;
    if (m.type === 'models') { modelSel.innerHTML = m.models.map(x => '<option value="'+x.id+'">'+x.name+'</option>').join(''); }
    else if (m.type === 'reply') { add(m.text, 'bot', m.tokensSaved ? ('saved ' + m.tokensSaved + ' tokens') : ''); }
    else if (m.type === 'error') { add('⚠ ' + m.text, 'bot'); }
  });
  vscode.postMessage({ type: 'ready' });
</script></body></html>`;
  }
}

// ─── activation ──────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "sensei.showSavings";
  statusItem.show();
  context.subscriptions.push(statusItem);

  const provider = new ChatViewProvider(context.extensionUri);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, provider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("sensei.openChat", () =>
      vscode.commands.executeCommand("sensei.chatView.focus")
    ),
    vscode.commands.registerCommand("sensei.routeClaudeCode", async () => {
      await setTerminalEnv({ ANTHROPIC_BASE_URL: gatewayUrl() });
      vscode.window.showInformationMessage(
        `Claude Code now routes through Sensei (${gatewayUrl()}). Open a new integrated terminal to apply.`
      );
    }),
    vscode.commands.registerCommand("sensei.routeCodex", async () => {
      await setTerminalEnv({ OPENAI_BASE_URL: `${gatewayUrl()}/v1` });
      vscode.window.showInformationMessage(
        `OpenAI Codex/CLI now routes through Sensei (${gatewayUrl()}/v1). Open a new integrated terminal to apply.`
      );
    }),
    vscode.commands.registerCommand("sensei.unroute", async () => {
      await setTerminalEnv({ ANTHROPIC_BASE_URL: undefined, OPENAI_BASE_URL: undefined });
      vscode.window.showInformationMessage("Stopped routing tools through Sensei.");
    }),
    vscode.commands.registerCommand("sensei.showSavings", async () => {
      const s = await fetchSavings();
      if (!s) {
        vscode.window.showWarningMessage("Sensei backend is not reachable.");
        return;
      }
      vscode.window.showInformationMessage(
        `Sensei: ${s.percent_saved}% fewer tokens — ${s.tokens_saved.toLocaleString()} saved ` +
          `(~$${s.estimated_cost_saved_usd.toFixed(2)}) over ${s.requests} requests.`
      );
    })
  );

  vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration("sensei")) startPolling();
  });

  startPolling();
}

export function deactivate(): void {
  if (pollTimer) clearInterval(pollTimer);
}
