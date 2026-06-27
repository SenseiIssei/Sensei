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
interface CatalogEntry {
  id: string;
  name: string;
  free: boolean;
  models: string[];
}
interface SettingsSnapshot {
  provider: string;
  model: string;
  api_key_set: boolean;
  log_file: string;
  catalog: CatalogEntry[];
}
interface Conversation {
  id: string;
  title: string;
}

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as T;
}
async function putJson<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
async function getSettings(): Promise<SettingsSnapshot | null> {
  try {
    return await getJson<SettingsSnapshot>(`${backendUrl()}/api/settings`);
  } catch {
    return null;
  }
}
async function putSettings(body: Record<string, unknown>): Promise<SettingsSnapshot> {
  return putJson<SettingsSnapshot>(`${backendUrl()}/api/settings`, body);
}
async function listConversations(): Promise<Conversation[]> {
  try {
    return await getJson<Conversation[]>(`${backendUrl()}/api/conversations`);
  } catch {
    return [];
  }
}
async function getConversation(id: string): Promise<{ messages: { role: string; content: string }[] }> {
  return getJson(`${backendUrl()}/api/conversations/${id}`);
}
function parseSSE(frame: string): { event: string; data: any } {
  let event = "message";
  let dataStr = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
  }
  let data: any = {};
  try {
    data = JSON.parse(dataStr);
  } catch {
    /* ignore */
  }
  return { event, data };
}

// ─── status bar ──────────────────────────────────────────────────────────────

let statusItem: vscode.StatusBarItem;
let pollTimer: NodeJS.Timeout | undefined;

async function refreshStatus(): Promise<void> {
  const s = await fetchSavings();
  if (!s) {
    statusItem.text = "$(zap) Sensei: offline";
    statusItem.tooltip = "Sensei backend not reachable.";
    return;
  }
  const usd = s.estimated_cost_saved_usd.toFixed(2);
  statusItem.text = `$(zap) ${s.percent_saved}% · $${usd}`;
  statusItem.tooltip = `Sensei saved ${s.tokens_saved.toLocaleString()} tokens (~$${usd}) across ${s.requests} requests.`;
}
function startPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  const secs = Math.max(5, cfg().get<number>("pollSeconds", 15));
  refreshStatus();
  pollTimer = setInterval(refreshStatus, secs * 1000);
}

// ─── set provider / model / key ──────────────────────────────────────────────

async function setApiKeyFlow(): Promise<SettingsSnapshot | null> {
  const settings = await getSettings();
  if (!settings) {
    vscode.window.showWarningMessage("Sensei backend is not reachable.");
    return null;
  }
  const provider = await vscode.window.showQuickPick(
    settings.catalog.map((c) => ({
      label: c.name,
      description: c.free ? "free tier available" : "",
      id: c.id,
      models: c.models,
    })),
    { placeHolder: "Choose a model provider" }
  );
  if (!provider) return null;

  const key = await vscode.window.showInputBox({
    prompt: `API key for ${provider.label}${provider.id === "ollama" ? " (leave blank for local Ollama)" : ""}`,
    password: true,
    ignoreFocusOut: true,
  });
  if (key === undefined) return null;

  const model = await vscode.window.showQuickPick(provider.models, { placeHolder: "Choose a model" });
  if (!model) return null;

  const updated = await putSettings({ provider: provider.id, api_key: key, model });
  vscode.window.showInformationMessage(`Sensei: now using ${provider.label} · ${model}`);
  return updated;
}

// ─── multi-model comparison ──────────────────────────────────────────────────

function renderCompareMarkdown(prompt: string, data: { tokens_saved: number; results: any[] }): string {
  let md = `# Sensei — model comparison\n\n**Prompt:** ${prompt}\n\n`;
  md += `_Tokens saved by compression (shared across all models): ${data.tokens_saved}_\n\n---\n\n`;
  for (const r of data.results) {
    md += `## ${r.model}\n\n`;
    if (r.error) {
      md += `> ⚠ error: ${r.error}\n\n`;
    } else {
      md += `${r.content}\n\n`;
      md += `_latency ${r.latency_ms} ms · prompt ${r.prompt_tokens} tok · completion ${r.completion_tokens} tok_\n\n`;
    }
    md += `---\n\n`;
  }
  return md;
}

async function compareModelsFlow(): Promise<void> {
  const settings = await getSettings();
  if (!settings) {
    vscode.window.showWarningMessage("Sensei backend is not reachable.");
    return;
  }
  const message = await vscode.window.showInputBox({
    prompt: "Prompt to send to every selected model",
    ignoreFocusOut: true,
  });
  if (!message) return;

  const allModels = Array.from(new Set(settings.catalog.flatMap((c) => c.models)));
  const picks = await vscode.window.showQuickPick(allModels, {
    canPickMany: true,
    placeHolder: "Pick models to compare (up to 6)",
  });
  if (!picks || picks.length === 0) return;

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Sensei: comparing models…" },
    async () => {
      try {
        const resp = await fetch(`${backendUrl()}/api/chat/compare`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, models: picks.slice(0, 6) }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = (await resp.json()) as { tokens_saved: number; results: any[] };
        const doc = await vscode.workspace.openTextDocument({
          language: "markdown",
          content: renderCompareMarkdown(message, data),
        });
        await vscode.window.showTextDocument(doc);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Compare failed: ${e?.message ?? e}`);
      }
    }
  );
}

// ─── RAG: knowledge base ─────────────────────────────────────────────────────

async function addToKnowledgeFlow(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open a file to add it to the knowledge base.");
    return;
  }
  const name = editor.document.fileName.split(/[\\/]/).pop() || "document";
  try {
    const resp = await fetch(`${backendUrl()}/api/rag/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content: editor.document.getText() }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as { document: string; chunks: number };
    vscode.window.showInformationMessage(`Sensei: indexed "${data.document}" (${data.chunks} chunks).`);
  } catch (e: any) {
    vscode.window.showErrorMessage(`Add failed: ${e?.message ?? e}`);
  }
}

async function askDocsFlow(): Promise<void> {
  const question = await vscode.window.showInputBox({
    prompt: "Ask a question about your indexed documents",
    ignoreFocusOut: true,
  });
  if (!question) return;
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Sensei: searching your docs…" },
    async () => {
      try {
        const resp = await fetch(`${backendUrl()}/api/rag/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: question, k: 4 }),
        });
        if (resp.status === 404) {
          vscode.window.showWarningMessage(
            "No documents indexed yet — run 'Sensei: Add current file to knowledge base' first."
          );
          return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = (await resp.json()) as { answer: string; sources: { doc: string }[]; tokens_saved: number };
        const sources = Array.from(new Set(data.sources.map((s) => s.doc))).join(", ");
        const md = `# ${question}\n\n${data.answer}\n\n---\n\n**Sources:** ${sources}\n\n_tokens saved by compression: ${data.tokens_saved}_\n`;
        const doc = await vscode.workspace.openTextDocument({ language: "markdown", content: md });
        await vscode.window.showTextDocument(doc);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Ask failed: ${e?.message ?? e}`);
      }
    }
  );
}

// ─── chat webview ────────────────────────────────────────────────────────────

class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "sensei.chatView";
  private conversationId: string | undefined;
  private view?: vscode.WebviewView;
  private abort?: AbortController;

  constructor(private readonly extensionUri: vscode.Uri) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")],
    };
    view.webview.html = this.html(view.webview);

    view.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "ready":
          await this.sendInit();
          break;
        case "send":
          await this.handleSend(msg.text, msg.model);
          break;
        case "cancel":
          this.abort?.abort();
          break;
        case "setModel":
          try {
            await putSettings({ model: msg.model });
          } catch {
            /* ignore */
          }
          break;
        case "newChat":
          this.conversationId = undefined;
          break;
        case "history":
          await this.openHistory();
          break;
        case "setKey":
          await setApiKeyFlow();
          await this.sendInit();
          break;
        case "copy":
          await vscode.env.clipboard.writeText(msg.text ?? "");
          vscode.window.setStatusBarMessage("Sensei: copied to clipboard", 1500);
          break;
      }
    });
  }

  private post(msg: unknown): void {
    this.view?.webview.postMessage(msg);
  }

  async sendInit(): Promise<void> {
    const s = await getSettings();
    const entry = s?.catalog.find((c) => c.id === s.provider);
    this.post({
      type: "init",
      provider: s?.provider ?? "",
      model: s?.model ?? "",
      models: entry?.models ?? [],
      keySet: s?.api_key_set ?? false,
    });
  }

  private async handleSend(text: string, model?: string): Promise<void> {
    this.abort = new AbortController();
    this.post({ type: "streamStart" });
    let tokensSaved = 0;
    try {
      const resp = await fetch(`${backendUrl()}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, model, conversation_id: this.conversationId }),
        signal: this.abort.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`Sensei backend HTTP ${resp.status}`);
      const reader = (resp.body as any).getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const ev = parseSSE(buf.slice(0, idx));
          buf = buf.slice(idx + 2);
          if (ev.event === "meta") {
            if (ev.data.conversation_id) this.conversationId = ev.data.conversation_id;
            tokensSaved = ev.data.tokens_saved ?? 0;
          } else if (ev.event === "token") {
            this.post({ type: "streamToken", t: ev.data.t });
          } else if (ev.event === "error") {
            this.post({ type: "streamError", text: ev.data.message });
          } else if (ev.event === "done") {
            tokensSaved = ev.data.tokens_saved ?? tokensSaved;
          }
        }
      }
      this.post({ type: "streamDone", tokensSaved });
    } catch (e: any) {
      if (e?.name === "AbortError") this.post({ type: "streamDone", tokensSaved, cancelled: true });
      else this.post({ type: "streamError", text: String(e?.message ?? e) });
    } finally {
      this.abort = undefined;
    }
  }

  private async openHistory(): Promise<void> {
    const convs = await listConversations();
    if (convs.length === 0) {
      vscode.window.showInformationMessage("No saved conversations yet.");
      return;
    }
    const pick = await vscode.window.showQuickPick(
      convs.map((c) => ({ label: c.title || "(untitled)", id: c.id })),
      { placeHolder: "Open a past conversation" }
    );
    if (!pick) return;
    try {
      const conv = await getConversation(pick.id);
      this.conversationId = pick.id;
      this.post({ type: "load", messages: conv.messages });
    } catch (e: any) {
      vscode.window.showWarningMessage(`Couldn't load conversation: ${e?.message ?? e}`);
    }
  }

  private html(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "chat.js")
    );
    const csp =
      `default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource};`;
    return /* html */ `<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); margin:0; padding:8px;
         display:flex; flex-direction:column; height:100vh; box-sizing:border-box; }
  #bar { display:flex; gap:6px; align-items:center; margin-bottom:6px; }
  #log { flex:1; overflow-y:auto; font-size:13px; line-height:1.45; }
  .msg { margin:6px 0; padding:6px 10px; border-radius:6px; word-wrap:break-word; }
  .msg.user { white-space:pre-wrap; background: var(--vscode-input-background); }
  .msg.bot  { background: var(--vscode-editorWidget-background); }
  .meta { font-size:10px; opacity:0.6; margin-top:3px; }
  .row { display:flex; gap:6px; margin-top:6px; }
  textarea { flex:1; resize:none; background:var(--vscode-input-background); color:var(--vscode-input-foreground);
             border:1px solid var(--vscode-input-border); border-radius:4px; padding:6px; font-family:inherit; }
  select, button { background:var(--vscode-button-background); color:var(--vscode-button-foreground);
                   border:none; border-radius:4px; padding:4px 8px; cursor:pointer; font-size:12px; }
  select { background:var(--vscode-dropdown-background); color:var(--vscode-dropdown-foreground); flex:1; }
  #warn { font-size:11px; color:var(--vscode-editorWarning-foreground); margin-bottom:4px; display:none; }
  .cb { margin:6px 0; border:1px solid var(--vscode-panel-border); border-radius:6px; overflow:hidden; }
  .cbh { display:flex; justify-content:space-between; align-items:center; padding:2px 8px;
         background:var(--vscode-editorGroupHeader-tabsBackground); font-size:10px; opacity:0.85; }
  .cbh button { padding:1px 6px; font-size:10px; }
  .cb pre { margin:0; padding:8px; overflow-x:auto; background:var(--vscode-textCodeBlock-background); }
  code { font-family: var(--vscode-editor-font-family, monospace); font-size:12px; }
  .ic { background:var(--vscode-textCodeBlock-background); padding:1px 4px; border-radius:3px; }
  h1,h2,h3 { margin:6px 0 4px; } h1{font-size:16px;} h2{font-size:15px;} h3{font-size:14px;}
  li { margin-left:16px; }
  a { color: var(--vscode-textLink-foreground); }
  .k { color: var(--vscode-symbolIcon-keywordForeground, #c586c0); }
  .s { color: var(--vscode-debugTokenExpression-string, #ce9178); }
  .c { color: var(--vscode-descriptionForeground, #6a9955); font-style:italic; }
  .n { color: var(--vscode-debugTokenExpression-number, #b5cea8); }
</style></head><body>
  <div id="bar">
    <select id="model" title="Model"></select>
    <button id="history" title="Open a past conversation">History</button>
    <button id="key" title="Set provider / model / API key">Key</button>
    <button id="new" title="New chat">New</button>
  </div>
  <div id="warn">No API key set — click <b>Key</b> to configure a model.</div>
  <div id="log"></div>
  <div class="row">
    <textarea id="input" rows="2" placeholder="Ask Sensei…  (prompts are compressed before sending)"></textarea>
    <button id="send">Send</button>
  </div>
  <script src="${scriptUri}"></script>
</body></html>`;
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
    vscode.commands.registerCommand("sensei.setApiKey", () => setApiKeyFlow()),
    vscode.commands.registerCommand("sensei.compareModels", () => compareModelsFlow()),
    vscode.commands.registerCommand("sensei.addToKnowledge", () => addToKnowledgeFlow()),
    vscode.commands.registerCommand("sensei.askDocs", () => askDocsFlow()),
    vscode.commands.registerCommand("sensei.showLogs", async () => {
      const s = await getSettings();
      if (s?.log_file) {
        try {
          const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(s.log_file));
          await vscode.window.showTextDocument(doc);
        } catch (e: any) {
          vscode.window.showWarningMessage(`Couldn't open log file ${s.log_file}: ${e?.message ?? e}`);
        }
      } else {
        vscode.window.showWarningMessage(
          "No server log file configured. Set SENSEI_LOG_FILE in .env and restart the backend."
        );
      }
    }),
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
