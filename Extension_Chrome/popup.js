// =============================
// MCP ComfyUI Controller - popup.js
// =============================

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const statusText = $("statusText");
const enableToggle = $("enableToggle");
const configPanel = $("configPanel");
const serverUrl = $("serverUrl");
const authToken = $("authToken");
const jsonOutput = $("jsonOutput");

function setStatus({ connected, connecting }) {
  statusEl.classList.remove("connected", "connecting", "disconnected");
  if (connected) {
    statusEl.classList.add("connected");
    statusText.textContent = "Connecté au serveur MCP";
  } else if (connecting) {
    statusEl.classList.add("connecting");
    statusText.textContent = "Connexion au serveur MCP…";
  } else {
    statusEl.classList.add("disconnected");
    statusText.textContent = "Déconnecté du serveur MCP";
  }
}

function setToggle(enabled) {
  enableToggle.classList.toggle("active", enabled);
  configPanel.style.display = enabled ? "block" : "none";
}

function initPopup() {
  chrome.storage.sync.get(
    ["mcpServerUrl", "mcpWebSocketToken", "mcpBrowserControlEnabled"],
    (res) => {
      serverUrl.value = res.mcpServerUrl || "ws://127.0.0.1:8000/ws";
      authToken.value = res.mcpWebSocketToken || "";
      const enabled = typeof res.mcpBrowserControlEnabled === "boolean" ? res.mcpBrowserControlEnabled : true;
      setToggle(enabled);
      
      chrome.runtime.sendMessage({ action: "getConnectionStatus" }, (st) => {
        if (!chrome.runtime.lastError) {
          setStatus(st || { connected: false, connecting: false });
        }
      });
    }
  );

  // Toggle activation
  enableToggle.addEventListener("click", () => {
    const enabled = !enableToggle.classList.contains("active");
    setToggle(enabled);
    chrome.storage.sync.set({ mcpBrowserControlEnabled: enabled }, () => {
      chrome.runtime.sendMessage({ action: "toggleBrowserControl", enabled });
    });
  });

  // Sauvegarder la configuration
  $("saveBtn").addEventListener("click", () => {
    const url = serverUrl.value.trim();
    const token = authToken.value.trim();
    chrome.storage.sync.set({ mcpServerUrl: url, mcpWebSocketToken: token }, () => {
      chrome.runtime.sendMessage({ action: "updateConfig", url, token });
    });
  });

  // Test de connexion
  $("testBtn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ action: "getConnectionStatus" }, (st) => {
      if (!chrome.runtime.lastError) {
        setStatus(st || { connected: false, connecting: false });
      }
    });
  });

  // Inspecter DOM
  $("dumpDomBtn").addEventListener("click", () => {
    chrome.runtime.sendMessage(
      { action: "execAndReturn", cmd: { action: "dump_dom", maxItems: 200 } },
      (resp) => {
        if (chrome.runtime.lastError) {
          jsonOutput.value = `Erreur: ${chrome.runtime.lastError.message}`;
          return;
        }
        jsonOutput.value = resp?.ok ? JSON.stringify(resp.data, null, 2) : `Erreur: ${resp?.error || "inconnue"}`;
        jsonOutput.scrollTop = 0;
      }
    );
  });

  // Nodes Map
  $("nodesMapBtn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ action: "execAndReturn", cmd: { action: "get_nodes_map" } }, (resp) => {
      if (chrome.runtime.lastError) {
        jsonOutput.value = `Erreur: ${chrome.runtime.lastError.message}`;
        return;
      }
      jsonOutput.value = resp?.ok ? JSON.stringify(resp.data, null, 2) : `Erreur: ${resp?.error || "inconnue"}`;
      jsonOutput.scrollTop = 0;
    });
  });

  // Workflow JSON
  $("workflowBtn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ action: "execAndReturn", cmd: { action: "get_workflow" } }, (resp) => {
      if (chrome.runtime.lastError) {
        jsonOutput.value = `Erreur: ${chrome.runtime.lastError.message}`;
        return;
      }
      jsonOutput.value = resp?.ok ? JSON.stringify(resp.data, null, 2) : `Erreur: ${resp?.error || "inconnue"}`;
      jsonOutput.scrollTop = 0;
    });
  });

  // Télécharger JSON
  $("downloadJsonBtn").addEventListener("click", () => {
    const txt = jsonOutput.value || "";
    if (!txt.trim()) return;
    const blob = new Blob([txt], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const now = new Date().toISOString().replace(/[:.]/g, "-");
    a.download = `mcp-comfyui-${now}.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  });

  // Rafraîchissement du statut de connexion toutes les 5 secondes
  setInterval(() => {
    chrome.runtime.sendMessage({ action: "getConnectionStatus" }, (st) => {
      if (!chrome.runtime.lastError && st) {
        setStatus(st);
      }
    });
  }, 5000);
}

// Initialisation
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPopup);
} else {
  initPopup();
}
