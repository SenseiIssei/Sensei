(function () {
  const vscode = acquireVsCodeApi();
  const log = document.getElementById("log");
  const input = document.getElementById("input");
  const modelSel = document.getElementById("model");
  const warn = document.getElementById("warn");
  const sendBtn = document.getElementById("send");

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  const KW = {};
  [
    "def", "class", "function", "const", "let", "var", "return", "if", "else", "elif",
    "for", "while", "import", "from", "export", "public", "private", "protected", "fn",
    "func", "impl", "struct", "enum", "async", "await", "new", "try", "catch", "except",
    "finally", "with", "as", "in", "of", "true", "false", "null", "None", "True", "False",
    "self", "this", "print", "interface", "type", "match", "case",
  ].forEach((k) => (KW[k] = 1));

  function highlight(code) {
    const re = /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g;
    let out = "", last = 0, m;
    while ((m = re.exec(code))) {
      out += esc(code.slice(last, m.index));
      if (m[1]) out += '<span class="c">' + esc(m[1]) + "</span>";
      else if (m[2]) out += '<span class="s">' + esc(m[2]) + "</span>";
      else if (m[3]) out += '<span class="n">' + esc(m[3]) + "</span>";
      else if (m[4]) out += KW[m[4]] ? '<span class="k">' + esc(m[4]) + "</span>" : esc(m[4]);
      last = re.lastIndex;
    }
    out += esc(code.slice(last));
    return out;
  }

  function renderMarkdown(md) {
    const blocks = [];
    md = String(md).replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      const i = blocks.length;
      code = code.replace(/\n$/, "");
      blocks.push(
        '<div class="cb"><div class="cbh"><span>' + esc(lang || "code") +
        '</span><button class="copy" data-code="' + encodeURIComponent(code) +
        '">copy</button></div><pre><code>' + highlight(code) + "</code></pre></div>"
      );
      return "%%CB" + i + "%%";
    });
    let html = esc(md);
    html = html.replace(/`([^`]+)`/g, (_, c) => '<code class="ic">' + c + "</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    html = html
      .replace(/^### (.*)$/gm, "<h3>$1</h3>")
      .replace(/^## (.*)$/gm, "<h2>$1</h2>")
      .replace(/^# (.*)$/gm, "<h1>$1</h1>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2">$1</a>');
    html = html.replace(/^(?:- |\* )(.*)$/gm, "<li>$1</li>");
    html = html.replace(/\n/g, "<br>");
    html = html.replace(/%%CB(\d+)%%(?:<br>)?/g, (_, i) => blocks[+i]);
    return html;
  }

  function add(text, cls, meta) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    if (cls === "bot") d.innerHTML = renderMarkdown(text);
    else d.textContent = text;
    if (meta) {
      const mm = document.createElement("div");
      mm.className = "meta";
      mm.textContent = meta;
      d.appendChild(mm);
    }
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  // ─── streaming state ───
  let streaming = false;
  let streamBuf = "";
  let streamDiv = null;

  function setStreaming(on) {
    streaming = on;
    sendBtn.textContent = on ? "Stop" : "Send";
  }

  function send() {
    if (streaming) return;
    const text = input.value.trim();
    if (!text) return;
    add(text, "user");
    input.value = "";
    vscode.postMessage({ type: "send", text, model: modelSel.value || undefined });
  }

  sendBtn.addEventListener("click", () => {
    if (streaming) vscode.postMessage({ type: "cancel" });
    else send();
  });
  document.getElementById("new").addEventListener("click", () => {
    log.innerHTML = "";
    vscode.postMessage({ type: "newChat" });
  });
  document.getElementById("history").addEventListener("click", () => vscode.postMessage({ type: "history" }));
  document.getElementById("key").addEventListener("click", () => vscode.postMessage({ type: "setKey" }));
  modelSel.addEventListener("change", () => vscode.postMessage({ type: "setModel", model: modelSel.value }));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  log.addEventListener("click", (e) => {
    const t = e.target;
    if (t && t.classList && t.classList.contains("copy")) {
      vscode.postMessage({ type: "copy", text: decodeURIComponent(t.getAttribute("data-code") || "") });
    }
  });

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (m.type === "init") {
      modelSel.innerHTML = (m.models || [])
        .map((x) => "<option" + (x === m.model ? " selected" : "") + ">" + x + "</option>")
        .join("");
      warn.style.display = m.keySet ? "none" : "block";
    } else if (m.type === "streamStart") {
      streamBuf = "";
      setStreaming(true);
      streamDiv = document.createElement("div");
      streamDiv.className = "msg bot";
      log.appendChild(streamDiv);
      log.scrollTop = log.scrollHeight;
    } else if (m.type === "streamToken") {
      streamBuf += m.t;
      if (streamDiv) {
        streamDiv.textContent = streamBuf;
        log.scrollTop = log.scrollHeight;
      }
    } else if (m.type === "streamDone") {
      if (streamDiv) {
        streamDiv.innerHTML = renderMarkdown(streamBuf || (m.cancelled ? "_(stopped)_" : ""));
        if (m.tokensSaved) {
          const mm = document.createElement("div");
          mm.className = "meta";
          mm.textContent = "saved " + m.tokensSaved + " tokens" + (m.cancelled ? " · stopped" : "");
          streamDiv.appendChild(mm);
        }
      }
      streamDiv = null;
      setStreaming(false);
    } else if (m.type === "streamError") {
      if (streamDiv) {
        streamDiv.innerHTML = renderMarkdown(streamBuf);
        const er = document.createElement("div");
        er.textContent = "⚠ " + m.text;
        streamDiv.appendChild(er);
      } else {
        add("⚠ " + m.text, "bot");
      }
      streamDiv = null;
      setStreaming(false);
    } else if (m.type === "load") {
      log.innerHTML = "";
      (m.messages || []).forEach((x) => add(x.content, x.role === "user" ? "user" : "bot"));
    }
  });

  vscode.postMessage({ type: "ready" });
})();
