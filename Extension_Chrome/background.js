// =============================
// MCP ComfyUI Controller - background.js (MV3) - Version Corrigée
// =============================

// ---------- Configuration par défaut ----------
let MCP_WEBSOCKET_URL = "ws://127.0.0.1:8000/ws";
let WEBSOCKET_TOKEN = "";
let BROWSER_CONTROL_ENABLED = true;

// ---------- État WS ----------
let ws = null;
let reconnectTimeout = null;
let isConnecting = false;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// ---------- Journal partagé (popup <-> bg) ----------
const LOG_BUFFER = [];
const LOG_MAX = 200;

function pushLog(entry) {
  const stamp = new Date().toISOString().slice(11, 19); // HH:MM:SS
  const row = { t: stamp, level: "info", ...entry };
  LOG_BUFFER.push(row);
  if (LOG_BUFFER.length > LOG_MAX) LOG_BUFFER.shift();

  chrome.runtime.sendMessage({ action: "log_update", rows: [row] }, () => {
    if (chrome.runtime.lastError) { /* Popup fermé, c'est normal */ }
  });
}

// ---------- Chargement config depuis storage ----------
let CONFIG_READY = false;
const waitConfig = new Promise((resolve) => {
  chrome.storage.sync.get(
    ["mcpServerUrl", "mcpWebSocketToken", "mcpBrowserControlEnabled"],
    (result) => {
      if (result.mcpServerUrl) MCP_WEBSOCKET_URL = result.mcpServerUrl;
      if (result.mcpWebSocketToken) WEBSOCKET_TOKEN = result.mcpWebSocketToken;
      if (typeof result.mcpBrowserControlEnabled === "boolean") {
        BROWSER_CONTROL_ENABLED = result.mcpBrowserControlEnabled;
      }
      pushLog({ level: "info", msg: "Config chargée" });
      CONFIG_READY = true;
      resolve();

      if (BROWSER_CONTROL_ENABLED) {
        pushLog({ level: "info", msg: "Connexion auto dans 3s…" });
        setTimeout(connect, 3000);
      } else {
        pushLog({ level: "info", msg: "Contrôle navigateur désactivé" });
      }
    }
  );
});

// ---------- Handlers messages (popup -> bg) ----------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // ... (Le reste de ce listener est parfait, pas de changement nécessaire) ...
  if (message.action === "updateConfig") {
    MCP_WEBSOCKET_URL = message.url ?? MCP_WEBSOCKET_URL;
    WEBSOCKET_TOKEN = message.token ?? WEBSOCKET_TOKEN;
    pushLog({ level: "info", msg: "Config mise à jour depuis popup" });
    disconnect();
    if (BROWSER_CONTROL_ENABLED) {
      reconnectAttempts = 0;
      connect();
    }
    sendResponse({ success: true });
    return true;
  }
  if (message.action === "toggleBrowserControl") {
    BROWSER_CONTROL_ENABLED = !!message.enabled;
    pushLog({ level: "info", msg: `Contrôle ${BROWSER_CONTROL_ENABLED ? "activé" : "désactivé"}` });
    if (BROWSER_CONTROL_ENABLED) {
      reconnectAttempts = 0;
      connect();
    } else {
      disconnect();
    }
    sendResponse({ success: true });
    return true;
  }
  if (message.action === "reconnect") {
    if (BROWSER_CONTROL_ENABLED) {
      disconnect();
      reconnectAttempts = 0;
      connect();
    }
    sendResponse({ success: true });
    return true;
  }
  if (message.action === "getConnectionStatus") {
    sendResponse({
      connected: ws && ws.readyState === WebSocket.OPEN,
      connecting: isConnecting,
      enabled: BROWSER_CONTROL_ENABLED,
    });
    return true;
  }
  if (message.action === "getLog") {
    sendResponse({ rows: LOG_BUFFER });
    return true;
  }
  if (message.action === "execAndReturn" && message.cmd) {
    executeCommandAndReturn(message.cmd)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  // Action non reconnue (implicite)
});

// ---------- Connexion WebSocket sécurisée ----------
async function connect() {
  // ... (Cette fonction est parfaite, pas de changement nécessaire) ...
  if (!CONFIG_READY) await waitConfig;
  if (!BROWSER_CONTROL_ENABLED) {
    pushLog({ level: "info", msg: "Connexion annulée (contrôle désactivé)" });
    return;
  }
  if (!WEBSOCKET_TOKEN) {
    pushLog({ level: "warn", msg: "Token absent → pas de tentative WS (évite 403)" });
    return;
  }
  if (isConnecting || (ws && ws.readyState === WebSocket.OPEN)) return;
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    pushLog({ level: "error", msg: "Max reconnexions atteint" });
    reconnectAttempts = 0;
    return;
  }
  isConnecting = true;
  reconnectAttempts++;
  const urlWithToken = `${MCP_WEBSOCKET_URL}?token=${encodeURIComponent(WEBSOCKET_TOKEN)}`;
  pushLog({ level: "info", msg: `Connexion WS (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})` });
  try {
    ws = new WebSocket(urlWithToken);
    ws.onopen = () => {
      isConnecting = false;
      reconnectAttempts = 0;
      pushLog({ level: "info", msg: "WS connecté" });
      const pingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        else clearInterval(pingInterval);
      }, 30000);
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "pong") return;
        if (data.error) {
          pushLog({ level: "error", msg: `Erreur serveur: ${data.error}` });
          if (data.message) pushLog({ level: "error", msg: data.message });
          return;
        }
        pushLog({ level: "debug", msg: `Commande reçue: ${data.action || data.type || "—"}` });
        executeCommand(data);
      } catch (e) {
        pushLog({ level: "error", msg: `JSON parse error: ${String(e)}` });
      }
    };
    ws.onclose = (event) => {
      isConnecting = false;
      if (event.code === 1008) {
        pushLog({ level: "error", msg: "Auth refusée (token invalide/manquant)" });
        reconnectAttempts = MAX_RECONNECT_ATTEMPTS;
        return;
      }
      pushLog({ level: "warn", msg: `WS fermé (${event.code})` });
      if (BROWSER_CONTROL_ENABLED && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        const delay = Math.min(5000 * reconnectAttempts, 30000);
        pushLog({ level: "info", msg: `Reconnexion dans ${delay / 1000}s…` });
        reconnectTimeout = setTimeout(connect, delay);
      }
    };
    ws.onerror = () => {
      isConnecting = false;
      pushLog({ level: "warn", msg: "WS error (handshake/403 ?)" });
    };
  } catch (error) {
    isConnecting = false;
    pushLog({ level: "error", msg: `Création WS: ${String(error)}` });
    if (BROWSER_CONTROL_ENABLED && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      reconnectTimeout = setTimeout(connect, 5000);
    }
  }
}

function disconnect() {
  // ... (Cette fonction est parfaite, pas de changement nécessaire) ...
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
  }
  if (ws) {
    try { ws.close(); } catch {}
    ws = null;
  }
  isConnecting = false;
  pushLog({ level: "info", msg: "WS déconnecté" });
}

// ---------- Utilitaires ----------
function isValidSelector(selector) { /* ... parfait, pas de changement ... */ return true; }
async function getComfyTab() { /* ... parfait, pas de changement ... */ const tabs = await chrome.tabs.query({url: ["http://127.0.0.1:8188/*", "http://localhost:8188/*"]}); return tabs[0];}

// ---------- Exécution des commandes (reçues du WS) ----------
async function executeCommand(command) {
  try {
    const data = await executeCommandAndReturn(command);
    if (ws && ws.readyState === WebSocket.OPEN) {
      // CORRECTION : On construit la réponse pour le serveur MCP ici
      // Le type de la réponse est dérivé de l'action de la commande
      const responseType = {
        "dump_dom": "dom_dump",
        "get_nodes_map": "nodes_map",
        "get_workflow": "workflow"
      }[command.action];

      if (responseType) {
        // On envoie directement les données, sans le wrapper {ok: true}
        ws.send(JSON.stringify({ type: responseType, data: data }));
        pushLog({ level: "info", msg: `Réponse '${responseType}' envoyée au serveur` });
      }
    }
  } catch (err) {
    pushLog({ level: "error", msg: `Erreur exécution commande: ${String(err)}` });
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "error", message: `Erreur côté extension: ${String(err)}` }));
    }
  }
}


// ---------- Exécution de commande avec RETOUR de données (pour popup et WS) ----------
async function executeCommandAndReturn(command) {
  const comfyTab = await getComfyTab();
  if (!comfyTab) throw new Error("Aucun onglet ComfyUI (8188) trouvé");

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: comfyTab.id },
    world: 'MAIN',
    func: injectedLogic, // AMÉLIORATION: On utilise une seule fonction d'injection
    args: [command]
  });

  if (res && res.result) {
    if (res.result.error) {
      throw new Error(res.result.error + (res.result.message ? `: ${res.result.message}` : ''));
    }
    return res.result; // Retourne directement les données (ex: {count: ..., items: ...})
  }
  throw new Error("Aucun résultat du script injecté.");
}


// ========== Fonctions injectées dans la page ComfyUI ==========
// AMÉLIORATION: Toute la logique est maintenant dans une seule fonction pour la propreté.
function injectedLogic(command) {
  
  // -- Fonctions utilitaires dans la page --
  const waitForGraph = (ms = 5000) => new Promise((resolve) => {
    const start = performance.now();
    const tick = () => {
      const g = (window.app && window.app.graph) || null;
      if (g && (g._nodes || g.nodes) && typeof g.serialize === 'function') return resolve(g);
      if (performance.now() - start > ms) return resolve(null);
      requestAnimationFrame(tick);
    };
    tick();
  });

  // -- Logique principale --
  switch (command.action) {
    case "click": {
      const el = document.querySelector(command.selector);
      if (el) el.click();
      return { ok: true };
    }
    case "fill": {
      const el = document.querySelector(command.selector);
      if (el) {
        el.value = command.text ?? "";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return { ok: true };
    }
    case "dump_dom": {
      // ... la fonction runInPageDump est déplacée ici ...
      const maxItems = command.maxItems || 100;
      const uniquePath = el => { /* ... (code de uniquePath inchangé) ... */ if(!el)return"";let path=[],n=5;while(el&&el.nodeType===1&&n-->0){let t=(e=>{if(!e)return"";if(e.id)return`#${e.id}`;let l=(e.className||"").toString().split(/\s+/).filter(Boolean).slice(0,3).join("."),r=(e.tagName||"div").toLowerCase();return l?`${r}.${l}`:r})(el);const o=el.parentElement;o&&Array.from(o.children).filter(t=>t.tagName===el.tagName).length>1&&(t+=`:nth-of-type(${Array.from(o.children).filter(t=>t.tagName===el.tagName).indexOf(el)+1})`),path.unshift(t),el=o}return path.join(" > ")};
      const pick = (selector) => Array.from(document.querySelectorAll(selector));
      const buttons = pick("button, [role='button'], .btn, .comfy-btn");
      const inputs = pick("input, textarea, [contenteditable='true']");
      const serialize = (el) => ({
        tag: (el.tagName || "").toLowerCase(), id: el.id || null, classes: (el.className || "").toString().trim() || null,
        selector: uniquePath(el), text: (el.innerText || el.value || "").trim().replace(/\s+/g, " ").slice(0, 120),
      });
      const items = [...buttons, ...inputs].slice(0, maxItems).map(serialize);
      return { url: location.href, count: items.length, items };
    }
    case "get_nodes_map": {
      return waitForGraph().then(g => {
        if (!g) return { error: "graph_not_ready" };
        const list = (g._nodes || g.nodes || []);
        const nodes = Array.from(list).map(n => ({
          id: n.id, type: n.type || n.constructor?.name || "Unknown",
          title: n.title || n.type || `Node ${n.id}`, pos: n.pos || null
        }));
        return { url: location.href, count: nodes.length, nodes };
      });
    }
    case "get_workflow": {
      return waitForGraph().then(g => {
        if (!g) return { error: "graph_not_ready" };
        try {
          const wf = g.serialize();
          return { url: location.href, node_count: (wf.nodes || []).length, workflow: wf };
        } catch (e) {
          return { error: "serialize_failed", message: String(e) };
        }
      });
    }
    default:
      return { error: `Action inconnue: ${command.action}` };
  }
}