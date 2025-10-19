# 🧠 Serveur MCP pour ComfyUI (Attention actuellement en construction)

Ce projet expose **ComfyUI** via un serveur compatible **MCP (Model Context Protocol)**.
Il permet 
- de piloter ComfyUI depuis ChatGPT via un connecteur (mode dev)
- de piloter l’interface ComfyUI dans Chrome via une extension WebSocket (en cours)

## ⚙️ Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/orion4d/ComfyUI_mcp.git
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

### Tester
```bash
curl http://127.0.0.1:8000/debug/health
```
# 📘 Commandes MCP–ComfyUI

## 🧠 Exécution & File
- **/queue_prompt** → exécuter un workflow
- **/get_queue_status** → état de la file
- **/get_history** → historique d’un prompt
- **/cancel_prompt** → annuler un prompt
- **/interrupt_execution** → stopper tout en cours

## ⚙️ Système & Modèles
- **/get_system_stats** → infos GPU, RAM, versions
- **/list_models** → lister les modèles disponibles
- **/model_info** → détails d’un modèle

## 🧩 Workflows
- **/save_workflow** → enregistrer un workflow
- **/load_workflow** → charger un workflow
- **/list_workflows** → lister tous les workflows
- **/inspect_workflow** → analyser la structure

## 🖼️ Images & Fichiers
- **/list_output_images** → voir les images produites
- **/get_image** → récupérer une image
- **/upload_image** → envoyer une image d’entrée

## 🔧 Custom Nodes
- **/create_custom_node_template** → créer un squelette de node
- **/write_custom_node** → écrire un fichier node
- **/read_custom_node** → lire le code d’un node
- **/list_custom_subdir** → explorer un dossier custom
- **/autodoc_nodes** → générer la doc de tous les custom nodes

## 📂 MCP Exchange
- **/list_exchange** → lister les fichiers partagés
- **/read_exchange** → lire un fichier (texte ou image)
- **/write_exchange** → écrire un fichier
- **/delete_exchange** → supprimer un fichier

## 🖥️ Interface (Chrome UI)
- **/ui_click_element** → simuler un clic
- **/ui_fill_input** → remplir un champ texte
- **/ui_get_current_workflow** → récupérer le workflow affiché
