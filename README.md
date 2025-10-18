# 🧠 Serveur MCP pour ComfyUI

Ce projet expose **ComfyUI** via un serveur compatible **MCP (Model Context Protocol)**.
Il permet :
- d’utiliser ComfyUI depuis ChatGPT via un connecteur (mode dev)
- de piloter l’interface ComfyUI dans Chrome via une extension WebSocket,
- et de gérer workflows, nodes et échanges locaux.

## 📁 Structure du projet

```
serveur_mcp-comfyui/
├── server.py               # Serveur MCP principal (FastMCP / Uvicorn)
├── comfyui_client.py       # Client HTTP vers ComfyUI
├── browser_controller.py   # Contrôle WebSocket vers extension Chrome
├── generate_key.py         # Générateur de clés (.env + sécurité)
└── .env(à parametrer)    # Configuration locale et template
```

## ⚙️ Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/ton-compte/serveur_mcp-comfyui.git](https://github.com/orion4d/ComfyUI_mcp.git
cd serveur_mcp-comfyui
```

### 2. Créer l’environnement virtuel

```bash
python -m venv venv
source venv/bin/activate       # sous Linux/Mac
venv\Scripts\activate        # sous Windows
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

## 🧩 Fichier requirements.txt

```
## 🔐 Génération des clés et configuration

```bash
python generate_key.py
```

Ce script :
- génère **MCP_API_KEY** (pour ChatGPT),
- génère **WEBSOCKET_TOKEN** (pour l’extension Chrome),
- crée automatiquement `.env` et `.env.example`.

## 🚀 Démarrage du serveur

```bash
python server.py
```

Par défaut, le serveur démarre sur :
```
http://127.0.0.1:8000
```

## 🌐 Points d’accès

### MCP Tools exposés
- `list_workflows`, `save_workflow`, `load_workflow`
- `read_custom_node`, `write_custom_node`
- `queue_prompt`, `get_history`
- `create_custom_node_template`, `list_custom_subdir`
- `ui_click_element`, `ui_fill_input`, `ui_get_current_workflow`

### Routes Debug
- `/debug/health` → infos système, versions, outils
- `/ws` → WebSocket pour l’extension Chrome

## 🧱 Exemple d’usage

### Depuis ChatGPT (Custom GPT)
- Authentification : `X-API-Key` → ta clé `MCP_API_KEY`
- Appels possibles : `list_workflows`, `queue_prompt`, `read_custom_node`, etc.

### Depuis Chrome (Extension MCP)
- URL WebSocket : `ws://127.0.0.1:8000/ws`
- Token : `WEBSOCKET_TOKEN`

## 🧠 Intégration ComfyUI

Le client (`ComfyUIClient`) communique via HTTP avec ton ComfyUI local :
- URL : `http://127.0.0.1:8188`
- Support des workflows UI et API
- Auto-conversion via `_convert_ui_to_api()`

## 🧩 Développement local

### Recharger automatiquement le serveur
```bash
uvicorn server:mcp.http_app --reload
```

### Tester
```bash
curl http://127.0.0.1:8000/debug/health
```

## 🧰 Outils

- `create_custom_node_template()` → crée un squelette de node
- `generate_key.py` → régénère un .env et des clés
- `list_custom_subdir()` → liste les scripts d’un dossier custom node

## 🏁 Licence

MIT © 2025 — Projet personnel d’intégration **ComfyUI ↔ ChatGPT MCP**
Non affilié à Stability AI ou OpenAI.
