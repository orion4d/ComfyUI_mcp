"""
ComfyUI MCP Server - Version propre et stable (avec outils admin)
- Outils ComfyUI (HTTP) via client synchrone
- Gestion workflows locaux
- Contrôle UI via WebSocket (optionnel)
- Middleware API Key
- Health check intégré
"""

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import re
import os
import sys
import json
import uuid
import logging
import atexit
import signal
from typing import Any, Dict
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import quote
from base64 import b64decode, b64encode

def _sha256_of_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------------------------------------------------------------------
# Configuration AVANT FastMCP
# ---------------------------------------------------------------------
load_dotenv()

COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
API_KEY = os.getenv("MCP_API_KEY")
WORKFLOWS_DIR = Path(__file__).parent / "workflows"
WORKFLOWS_DIR.mkdir(exist_ok=True)
ENABLE_BROWSER_CONTROL = os.getenv("ENABLE_BROWSER_CONTROL", "true").lower() == "true"
WEBSOCKET_TOKEN = os.getenv("WEBSOCKET_TOKEN")

# Chemins ComfyUI
COMFYUI_ROOT = Path(os.getenv("COMFYUI_ROOT", "")).resolve() if os.getenv("COMFYUI_ROOT") else None
CUSTOM_NODES_DIR = (COMFYUI_ROOT / "custom_nodes") if COMFYUI_ROOT else None
MCP_DROP_DIR = (CUSTOM_NODES_DIR / "mcp_drop") if CUSTOM_NODES_DIR else None
MODELS_DIR = (COMFYUI_ROOT / "models") if COMFYUI_ROOT else None

# LIGNES DE DEBUG
print("COMFYUI_ROOT =", COMFYUI_ROOT)
print("CUSTOM_NODES_DIR =", CUSTOM_NODES_DIR)

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComfyUIMCP")

# ---------------------------------------------------------------------
# Imports FastMCP APRÈS configuration
# ---------------------------------------------------------------------
from fastmcp import FastMCP
from fastapi import Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import WebSocketRoute

# ---------------------------------------------------------------------
# Helpers (AVANT les outils)
# ---------------------------------------------------------------------
def _require_root(root: Path, label: str):
    if not root or not root.exists():
        raise FileNotFoundError(f"{label} introuvable. Définis COMFYUI_ROOT dans .env (ex: D:\\ComfyUI).")

def _sanitize_filename(name: str, ext: str = ".py") -> str:
    base = name.strip()
    if re.search(r"[\\/]|\.\.", base):
        raise ValueError("Nom de fichier invalide.")
    if not base.endswith(ext):
        base += ext
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]{1,128}", base):
        raise ValueError("Nom de fichier non autorisé (A-Za-z0-9_-. uniquement, 128 chars max).")
    return base

def _safe_join(root: Path, *parts: str) -> Path:
    # Autorise les chemins enfants même si 'output' est un symlink/junction
    p_text = root.joinpath(*parts)        # chemin "logique" (sans resolve)
    p_real = p_text.resolve()             # chemin résolu (peut pointer hors du root si symlink)
    root_text = root
    root_real = root.resolve()

    # OK si:
    # 1) le chemin résolu est sous le root résolu (cas sans symlink), OU
    # 2) le chemin textuel est sous le root textuel (on accepte les junction/symlink enfants)
    p_text_str = str(p_text)
    root_text_str = str(root_text)
    p_real_str = str(p_real)
    root_real_str = str(root_real)

    if p_real_str.startswith(root_real_str) or p_text_str.startswith(root_text_str):
        return p_real

    raise PermissionError("Chemin hors de la zone autorisée.")

# ---------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests = {}

    def is_allowed(self, client_id: str) -> bool:
        now = datetime.now()
        entries = [t for t in self.requests.get(client_id, []) if now - t < self.window]
        if len(entries) >= self.max_requests:
            self.requests[client_id] = entries
            return False
        entries.append(now)
        self.requests[client_id] = entries
        return True

    def reset(self, client_id: str):
        self.requests.pop(client_id, None)

rate_limiter = RateLimiter()

# ---------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.authenticated_connections: dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket, client_info: dict):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.authenticated_connections[websocket] = client_info

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.authenticated_connections:
            del self.authenticated_connections[websocket]

    async def send_command(self, command: dict):
        if not ENABLE_BROWSER_CONTROL:
            return {"status": "disabled", "message": "Browser control is disabled"}
        if not self.active_connections:
            return {"status": "error", "message": "No browser extension connected"}
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(command)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)
        
        return {"status": "sent", "connections": len(self.active_connections)}

manager = ConnectionManager()

# ---------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------
from comfyui_client import ComfyUIClient
client = ComfyUIClient(base_url=COMFYUI_BASE_URL)

from browser_controller import BrowserController
browser = BrowserController(manager)

# =====================================================================
# FastMCP instance (UNE SEULE LIGNE)
# =====================================================================
mcp = FastMCP("ComfyUI MCP Server")

# ===========================================
# Zone d'échange fichiers (output/MCP_exchange)
# ===========================================
EXCHANGE_DIR = (COMFYUI_ROOT / "output" / "MCP_exchange") if COMFYUI_ROOT else None
TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm", ".json", ".js", ".py", ".css"}
IMG_EXTS  = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ALL_EXTS  = TEXT_EXTS | IMG_EXTS
MAX_WRITE_BYTES = 10 * 1024 * 1024  # 10 MB

def _sanitize_name_for_any(name: str, allowed_exts=ALL_EXTS) -> str:
    """Autorise un nom simple + extension white-listée. Pas de sous-dossiers."""
    base = name.strip()
    if re.search(r"[\\/]|\.\.", base):
        raise ValueError("Nom de fichier invalide.")
    ext = Path(base).suffix.lower()
    if not ext or ext not in allowed_exts:
        raise ValueError(f"Extension non autorisée ({ext}). Autorisées: {sorted(allowed_exts)}")
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]{1,128}", base):
        raise ValueError("Nom non autorisé (A-Za-z0-9_-. uniquement, 128 chars max).")
    return base

def _ensure_exchange_dir() -> Path:
    _require_root(COMFYUI_ROOT, "COMFYUI_ROOT")
    root = _safe_join(COMFYUI_ROOT, "output")
    exch = _safe_join(root, "MCP_exchange")
    exch.mkdir(parents=True, exist_ok=True)
    return exch

# =====================================================================
# OUTILS MCP (@mcp.tool())
# =====================================================================

# Tools ComfyUI (client synchrone)
@mcp.tool()
def queue_prompt(workflow: dict) -> dict:
    """Envoie un workflow à ComfyUI pour exécution"""
    return client.queue_prompt(workflow)

@mcp.tool()
def get_queue_status() -> dict:
    """Récupère l'état de la file d'attente ComfyUI"""
    return client.get_queue_info()

@mcp.tool()
def get_history(prompt_id: str) -> dict:
    """Récupère l'historique d'un prompt spécifique"""
    return client.get_history(prompt_id)

@mcp.tool()
def cancel_prompt(prompt_id: str = "") -> dict: # Le prompt_id n'est pas utilisé par l'API interrupt
    """Annule un prompt en cours d'exécution"""
    return client.interrupt() # Appelle la nouvelle méthode

@mcp.tool()
def get_system_stats() -> dict:
    """Récupère les statistiques système de ComfyUI"""
    return client.get_system_stats()

@mcp.tool()
def list_models(model_type: str = "checkpoints") -> dict:
    """Liste les modèles disponibles dans ComfyUI"""
    if hasattr(client, "list_models"):
        return client.list_models(model_type)
    try:
        info = client.get_object_info("CheckpointLoaderSimple")
        models = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        return {"model_type": "checkpoints", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def upload_image(image_path: str) -> dict:
    """Upload une image vers ComfyUI"""
    if hasattr(client, "upload_image"):
        return client.upload_image(image_path)
    return {"status": "error", "message": "upload_image non implémenté"}

@mcp.tool()
def get_image(filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
    """Récupère une image depuis ComfyUI"""
    if hasattr(client, "get_image"):
        return client.get_image(filename, subfolder, folder_type)
    return b""

@mcp.tool()
def list_node_types() -> dict:
    """Liste tous les types de nœuds disponibles"""
    return client.get_object_info()

@mcp.tool()
def interrupt_execution() -> dict:
    """Interrompt l'exécution en cours"""
    if hasattr(client, "interrupt"):
        return client.interrupt()
    return {"status": "error", "message": "interrupt non implémenté"}

# Gestion des workflows
@mcp.tool()
def save_workflow(name: str, workflow: dict) -> dict:
    """Sauvegarde un workflow (supporte les sous-dossiers)"""
    if not isinstance(workflow, dict):
        return {"status": "error", "message": "Payload 'workflow' invalide"}
    # Interdit absolus et traversées
    if ".." in name or name.strip().startswith(("/", "\\")):
        return {"status": "error", "message": "Nom de workflow invalide"}
    try:
        # Construit un chemin sûr sous WORKFLOWS_DIR
        rel_path = Path(*[p for p in Path(name).parts if p not in ("", ".", "..")]).with_suffix(".json")
        filepath = _safe_join(WORKFLOWS_DIR, str(rel_path))
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"status": "error", "message": f"Chemin non autorisé: {e}"}

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(workflow, f, indent=2, ensure_ascii=False)

    stat = Path(filepath).stat()
    return {
        "status": "success",
        "path": str(filepath),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "name": str(rel_path.with_suffix("")).replace("\\", "/")
    }


@mcp.tool()
def load_workflow(name: str) -> dict:
    """Charge un workflow sauvegardé (supporte les sous-dossiers)"""
    # Interdit les patterns d'évasion
    if ".." in name or name.strip().startswith(("/", "\\")):
        return {"status": "error", "message": "Nom de workflow invalide"}
    try:
        # Construit un chemin sûr sous WORKFLOWS_DIR
        rel_path = Path(*[p for p in Path(name).parts if p not in ("", ".", "..")])
        filepath = _safe_join(WORKFLOWS_DIR, str(rel_path.with_suffix(".json")))
    except Exception as e:
        return {"status": "error", "message": f"Chemin non autorisé: {e}"}
    if not Path(filepath).exists():
        return {"status": "error", "message": f"Workflow '{name}' introuvable"}
    with open(filepath, 'r', encoding='utf-8') as f:
        workflow = json.load(f)
    return {"status": "success", "workflow": workflow}


@mcp.tool()
def list_workflows() -> dict:
    """Liste tous les workflows sauvegardés (récursif, avec sous-dossiers)"""
    workflows = []
    for filepath in WORKFLOWS_DIR.rglob("*.json"):
        stat = filepath.stat()
        rel = filepath.relative_to(WORKFLOWS_DIR).with_suffix("")  # garde les sous-dossiers
        workflows.append({
            "name": str(rel).replace("\\", "/"),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    workflows.sort(key=lambda w: w["name"])
    return {"status": "success", "workflows": workflows}

@mcp.tool()
def inspect_workflow(name: str) -> dict:
    """
    Inspecte un workflow pour analyser sa structure.
    Supporte les sous-dossiers (ex: 'production/upscale').
    
    Args:
        name: Nom du workflow avec ou sans .json (peut contenir des /)
    
    Returns:
        Dict avec status, format (UI/API), nombre de nodes, etc.
    """
    # Protection contre path traversal
    if ".." in name or name.strip().startswith(("/", "\\")):
        return {"status": "error", "message": "Nom de workflow invalide"}
    
    try:
        # Nettoyer et construire le chemin sécurisé
        rel_path = Path(*[p for p in Path(name).parts if p not in ("", ".", "..")])
        wf_path = _safe_join(WORKFLOWS_DIR, str(rel_path.with_suffix(".json")))
    except Exception as e:
        return {"status": "error", "message": f"Chemin non autorisé: {e}"}
    
    if not Path(wf_path).exists():
        return {"status": "error", "message": f"Workflow '{name}' introuvable"}

    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        return {"status": "error", "message": f"Lecture invalide: {e}"}

    # Analyse du format (UI ou API)
    if isinstance(payload, dict) and "nodes" in payload and "links" in payload:
        info = {
            "format": "UI",
            "nodes": len(payload.get("nodes", [])),
            "links": len(payload.get("links", [])),
            "path": str(wf_path)
        }
    else:
        class_types = []
        if isinstance(payload, dict):
            graph = payload.get("prompt", payload)
            if isinstance(graph, dict):
                for node_id, node in graph.items():
                    ct = node.get("class_type")
                    if ct:
                        class_types.append(ct)
        info = {
            "format": "API",
            "nodes": len(class_types),
            "class_types": class_types[:100],
            "path": str(wf_path)
        }

    return {"status": "success", "workflow": info}

# Contrôle UI Chrome
@mcp.tool()
async def ui_click_element(selector: str) -> dict:
    """Clique sur un élément dans l'interface Chrome de ComfyUI"""
    if not ENABLE_BROWSER_CONTROL:
        return {"status": "disabled", "message": "Browser control disabled"}
    return await browser.click_element(selector)

@mcp.tool()
async def ui_fill_input(selector: str, text: str) -> dict:
    """Remplit un champ de saisie dans l'interface Chrome"""
    if not ENABLE_BROWSER_CONTROL:
        return {"status": "disabled", "message": "Browser control disabled"}
    return await browser.fill_input(selector, text)

@mcp.tool()
async def ui_get_current_workflow() -> dict:
    """Récupère le workflow actuel depuis l'interface Chrome"""
    if not ENABLE_BROWSER_CONTROL:
        return {"status": "disabled", "message": "Browser control disabled"}
    return await browser.get_workflow()

# OUTILS ADMIN
@mcp.tool()
def write_custom_node(name: str, content: str, subdir: str = "mcp_drop", overwrite: bool = False) -> dict:
    """Écrit un fichier de custom node dans ComfyUI"""
    _require_root(CUSTOM_NODES_DIR, "custom_nodes")
    
    if len(content.encode("utf-8")) > 200_000:
        return {"status": "error", "message": "Contenu trop volumineux (>200 KB)"}
    
    safe_name = _sanitize_filename(name, ".py")
    target_dir = _safe_join(CUSTOM_NODES_DIR, subdir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = _safe_join(target_dir, safe_name)
    
    if target_path.exists() and not overwrite:
        return {"status": "error", "message": "Fichier existe déjà (overwrite=false)"}
    
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return {
        "status": "success",
        "path": str(target_path),
        "size": target_path.stat().st_size,
        "sha256": _sha256_of_file(target_path),
        "tip": "Relance ComfyUI ou 'Reload custom nodes' pour prendre en compte."
    }

@mcp.tool()
def create_custom_node_template(folder_name: str, node_name: str, description: str = "") -> dict:
    """
    Crée un squelette complet de Custom Node :
    - Dossier sous custom_nodes/
    - __init__.py
    - nodes.py avec une classe simple
    - README.md descriptif
    """
    try:
        if not folder_name or not node_name:
            return {"status": "error", "message": "folder_name et node_name sont requis."}

        # Vérifie le dossier cible
        target_dir = _safe_join(CUSTOM_NODES_DIR, folder_name)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Fichier __init__.py
        init_path = target_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text(
                f'"""Init for {folder_name} custom nodes"""\n\n'
                f"from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS\n\n"
                "__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']\n",
                encoding="utf-8"
            )

        # Fichier nodes.py
        nodes_path = target_dir / "nodes.py"
        if not nodes_path.exists():
            nodes_path.write_text(
                f"class {node_name}:\n"
                f"    @classmethod\n"
                f"    def INPUT_TYPES(cls):\n"
                f"        return {{'required': {{'text': ('STRING', {{'default': 'Hello World'}})}}}}\n\n"
                f"    RETURN_TYPES = ('STRING',)\n"
                f"    FUNCTION = 'say_hello'\n"
                f"    CATEGORY = 'custom/{folder_name}'\n\n"
                f"    def say_hello(self, text):\n"
                f"        return (f'{node_name} dit: {{text}}',)\n\n"
                f"NODE_CLASS_MAPPINGS = {{'{node_name}': {node_name}}}\n"
                f"NODE_DISPLAY_NAME_MAPPINGS = {{'{node_name}': '{node_name}'}}\n",
                encoding="utf-8"
            )

        # Fichier README.md
        readme_path = target_dir / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                f"# {node_name}\n\n"
                f"Custom node généré automatiquement.\n\n"
                f"{description}\n",
                encoding="utf-8"
            )

        return {
            "status": "success",
            "message": f"Custom node '{node_name}' créé dans '{target_dir}'.",
            "files": [str(init_path), str(nodes_path), str(readme_path)]
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def read_custom_node(name: str, subdir: str = "mcp_drop") -> dict:
    """Lit le contenu d'un fichier custom node depuis ComfyUI"""
    _require_root(CUSTOM_NODES_DIR, "custom_nodes")
    
    safe_name = _sanitize_filename(name, ".py")
    target_dir = _safe_join(CUSTOM_NODES_DIR, subdir)
    target_path = _safe_join(target_dir, safe_name)
    
    if not target_path.exists():
        return {"status": "error", "message": f"Fichier '{name}' introuvable dans {subdir}"}
    
    try:
        content = target_path.read_text(encoding="utf-8")
        return {
            "status": "success",
            "name": safe_name,
            "path": str(target_path),
            "content": content,
            "size": len(content),
            "lines": len(content.splitlines())
        }
    except Exception as e:
        return {"status": "error", "message": f"Erreur de lecture: {e}"}

@mcp.tool()
def list_custom_subdir(folder: str) -> dict:
    """
    Liste les fichiers .py d'un sous-dossier direct de custom_nodes (sans descendre).
    Exemple: folder="Orion4D_external_mcp"
    """
    try:
        # sécurité nom de dossier (pas de traversée, pas de séparateurs)
        if not folder or ".." in folder or "/" in folder or "\\" in folder:
            return {"status": "error", "message": "Nom de dossier invalide"}

        # Vérifie la racine custom_nodes
        _require_root(CUSTOM_NODES_DIR, "custom_nodes")

        target = _safe_join(CUSTOM_NODES_DIR, folder)
        if not target.exists() or not target.is_dir():
            return {"status": "error", "message": f"Dossier introuvable: {folder}"}

        from datetime import datetime
        items = []
        for p in target.glob("*.py"):
            try:
                st = p.stat()
                items.append({
                    "name": p.name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except Exception as e:
                items.append({"name": p.name, "error": str(e)})

        items.sort(key=lambda x: x.get("name", "").lower())
        return {"status": "success", "folder": str(target), "count": len(items), "files": items}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def autodoc_nodes() -> dict:
    """Génère automatiquement la documentation des custom nodes"""
    _require_root(CUSTOM_NODES_DIR, "custom_nodes")
    
    data = []
    class_rx = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", flags=re.MULTILINE)
    mapping_rx = re.compile(r"NODE_CLASS_MAPPINGS\s*=\s*\{([^}]*)\}", flags=re.DOTALL)
    
    for folder in sorted(CUSTOM_NODES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        
        entry = {"folder": folder.name, "files": []}
        for py in sorted(folder.glob("*.py")):
            item = {"file": py.name, "classes": []}
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
                item["classes"] = class_rx.findall(text)[:50]
                
                m = mapping_rx.search(text)
                if m:
                    keys = []
                    for line in m.group(1).splitlines():
                        line = line.strip()
                        if line.startswith("#") or ":" not in line:
                            continue
                        key = line.split(":", 1)[0].strip().strip("'\"")
                        if key and len(keys) < 50:
                            keys.append(key)
                    if keys:
                        item["node_keys"] = keys
            except Exception as e:
                item["error"] = str(e)
            
            entry["files"].append(item)
        
        if entry["files"]:
            data.append(entry)
    
    return {"status": "success", "custom_nodes": data}

# Liste les images de COMFYUI_ROOT/output (hors MCP_exchange si tu veux tout)
@mcp.tool()
def list_output_images(limit: int = 100, exts: str = "png,jpg,jpeg,webp") -> dict:
    """
    Liste les images du dossier ComfyUI/output (triées du plus récent au plus ancien).
    exts: extensions autorisées, séparées par virgules.
    """
    _require_root(COMFYUI_ROOT, "COMFYUI_ROOT")
    output_dir = _safe_join(COMFYUI_ROOT, "output")
    if not output_dir.exists():
        return {"status": "success", "files": []}

    allowed = {e.strip().lower().lstrip(".") for e in exts.split(",") if e.strip()}
    items = []
    for p in output_dir.rglob("*"):
        if p.is_file() and p.suffix.lower().lstrip(".") in allowed:
            rel = p.relative_to(output_dir)
            stat = p.stat()
            filename = p.name
            subfolder = str(rel.parent).replace("\\", "/") if rel.parent != Path(".") else ""
            view = f"/view?filename={quote(filename)}&type=output"
            if subfolder:
                view += f"&subfolder={quote(subfolder)}"
            items.append({
                "filename": filename,
                "subfolder": subfolder,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "view_path": view,
            })

    items.sort(key=lambda x: x["modified"], reverse=True)
    return {"status": "success", "count": len(items[:limit]), "files": items[:limit]}
@mcp.tool()
def list_exchange(limit: int = 200, exts: str = "png,jpg,jpeg,webp,bmp,tif,tiff,txt,md,html,htm,json,js,py,css") -> dict:
    """Liste les fichiers dans output/MCP_exchange (du + récent au + ancien)."""
    root = _ensure_exchange_dir()
    allowed = {"." + e.strip().lower().lstrip(".") for e in exts.split(",") if e.strip()}
    files = []
    for p in root.glob("*"):
        if p.is_file() and p.suffix.lower() in allowed:
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "ext": p.suffix.lower(),
                "view_path": f"/view?filename={quote(p.name)}&subfolder=MCP_exchange&type=output"
                              if p.suffix.lower() in IMG_EXTS else None,
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"status":"success","count":len(files[:limit]),"files":files[:limit]}

@mcp.tool()
def read_exchange(name: str, as_data_url: bool = True) -> dict:
    """
    Lit un fichier dans output/MCP_exchange.
    - Images: si as_data_url=True -> data:image/...;base64, sinon base64 brut.
    - Textes: renvoie content (str).
    """
    root = _ensure_exchange_dir()
    safe = _sanitize_name_for_any(name)
    path = _safe_join(root, safe)

    if not path.exists() or not path.is_file():
        return {"status":"error","message":f"Fichier introuvable: {safe}"}

    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            txt = path.read_text(encoding="utf-8", errors="replace")
            return {"status":"success","name":safe,"ext":ext,"mode":"text","content":txt}
        else:
            raw = path.read_bytes()
            b64 = b64encode(raw).decode("ascii")
            if as_data_url:
                mime = {
                    ".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",
                    ".webp":"image/webp",".bmp":"image/bmp",".tif":"image/tiff",".tiff":"image/tiff"
                }.get(ext, "application/octet-stream")
                return {"status":"success","name":safe,"ext":ext,"mode":"data_url","data_url":f"data:{mime};base64,{b64}"}
            else:
                return {"status":"success","name":safe,"ext":ext,"mode":"base64","base64":b64}
    except Exception as e:
        return {"status":"error","message":str(e)}

@mcp.tool()
def write_exchange(name: str, content: str, mode: str = "text", overwrite: bool = False) -> dict:
    """
    Écrit un fichier dans output/MCP_exchange.
    mode:
      - 'text'    : content = texte UTF-8 (extensions texte uniquement)
      - 'base64'  : content = base64 de données binaires
      - 'data_url': content = data:<mime>;base64,...
    """
    root = _ensure_exchange_dir()
    safe = _sanitize_name_for_any(name)
    path = _safe_join(root, safe)

    if path.exists() and not overwrite:
        return {"status":"error","message":"Fichier existe déjà (overwrite=false)"}

    ext = path.suffix.lower()
    try:
        if mode == "text":
            if ext not in TEXT_EXTS:
                return {"status":"error","message":f"Extension {ext} non texte"}
            data = content.encode("utf-8")
        elif mode == "base64":
            data = b64decode(content)
        elif mode == "data_url":
            if "," not in content:
                return {"status":"error","message":"data_url invalide"}
            data = b64decode(content.split(",",1)[1])
        else:
            return {"status":"error","message":"mode invalide (text|base64|data_url)"}

        if len(data) > MAX_WRITE_BYTES:
            return {"status":"error","message":"Fichier trop volumineux (>10MB)"}

        path.write_bytes(data)
        return {"status":"success","name":safe,"size_bytes":len(data),"path":str(path)}
    except Exception as e:
        return {"status":"error","message":str(e)}

@mcp.tool()
def delete_exchange(name: str) -> dict:
    """Supprime un fichier dans output/MCP_exchange."""
    root = _ensure_exchange_dir()
    safe = _sanitize_name_for_any(name)
    path = _safe_join(root, safe)
    if not path.exists():
        return {"status":"error","message":"Fichier introuvable"}
    try:
        path.unlink()
        return {"status":"success","deleted":safe}
    except Exception as e:
        return {"status":"error","message":str(e)}


@mcp.tool()
def model_info(name: str) -> dict:
    """Récupère les informations détaillées d'un modèle"""
    _require_root(MODELS_DIR, "models")
    
    rel = name.strip().lstrip("\\/")
    target = _safe_join(MODELS_DIR, rel)
    
    if not target.exists() or not target.is_file():
        return {"status": "error", "message": f"Modèle introuvable: {rel}"}
    
    stat = target.stat()
    info = {
        "status": "success",
        "path": str(target),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "sha256": _sha256_of_file(target),
        "extension": target.suffix.lower()
    }
    
    if target.suffix.lower() == ".safetensors":
        try:
            from safetensors import safe_open
            md = {}
            with safe_open(str(target), framework="pt") as f:
                md = f.metadata() or {}
            info["safetensors_metadata"] = md
        except Exception as e:
            info["safetensors_metadata"] = {"warning": f"Non disponible ({e})"}
    
    return info

# =====================================================================
# ROUTES HTTP personnalisées (@mcp.custom_route)
# =====================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint"""
    try:
        status = client.get_queue_info()
        comfyui_status = "connected" if status else "unknown"
    except Exception:
        comfyui_status = "disconnected"
    
    return JSONResponse({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "comfyui": comfyui_status,
        "browser_control_enabled": ENABLE_BROWSER_CONTROL,
        "chrome_connections": len(manager.active_connections) if ENABLE_BROWSER_CONTROL else 0,
        "api_key_enabled": bool(API_KEY)
    })

@mcp.custom_route("/debug/tools", methods=["GET"])
async def debug_tools(request: Request):
    try:
        names = set()

        # Registres possibles selon versions de FastMCP
        for attr in ("tools", "_tools"):
            reg = getattr(mcp, attr, None)
            if isinstance(reg, dict):
                names |= set(reg.keys())

        tm = getattr(mcp, "_tool_manager", None)
        if tm:
            for attr in ("tools", "_tools"):
                reg = getattr(tm, attr, None)
                if isinstance(reg, dict):
                    names |= set(reg.keys())

        return JSONResponse({"status": "success", "count": len(names), "tools": sorted(names)})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# WebSocket endpoint
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket pour le contrôle du navigateur"""
    if not ENABLE_BROWSER_CONTROL:
        await websocket.close(code=1008, reason="Browser control disabled")
        return
    
    token = websocket.query_params.get("token")
    if not token or token != WEBSOCKET_TOKEN:
        await websocket.close(code=1008, reason="Unauthorized - Invalid token")
        return
    
    origin = websocket.headers.get("origin", "")
    if not origin.startswith("chrome-extension://"):
        await websocket.close(code=1008, reason="Invalid origin")
        return
    
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    client_info = {
        "origin": origin,
        "connected_at": datetime.now().isoformat(),
        "client_id": client_id
    }
    
    await manager.connect(websocket, client_info)
    
    try:
        while True:
            data = await websocket.receive_text()
            
            if not rate_limiter.is_allowed(client_id):
                await websocket.send_json({"error": "Rate limit exceeded"})
                continue
            
            if data:
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        })
                except Exception as e:
                    logger.error(f"Erreur traitement message: {e}")
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        rate_limiter.reset(client_id)
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        manager.disconnect(websocket)
        rate_limiter.reset(client_id)

# --- ROUTE DEBUG HEALTH ---
from fastapi import Request
from fastapi.responses import JSONResponse
import platform

@mcp.custom_route("/debug/health", methods=["GET"])
async def debug_health(request: Request):
    names = set()
    for attr in ("tools", "_tools"):
        reg = getattr(mcp, attr, None)
        if isinstance(reg, dict):
            names |= set(reg.keys())
    tm = getattr(mcp, "_tool_manager", None)
    if tm:
        for attr in ("tools", "_tools"):
            reg = getattr(tm, attr, None)
            if isinstance(reg, dict):
                names |= set(reg.keys())

    return JSONResponse({
        "status": "success",
        "health": {
            "COMFYUI_ROOT": str(COMFYUI_ROOT),
            "CUSTOM_NODES_DIR": str(CUSTOM_NODES_DIR),
            "WORKFLOWS_DIR": str(WORKFLOWS_DIR),
            "python": platform.python_version(),
            "tool_count": len(names),
            "tools_sample": sorted(list(names))[:50],
        }
    })
# --- FIN ROUTE DEBUG HEALTH ---

# =====================================================================
# APP SETUP (APRÈS tous les outils)
# =====================================================================
app = mcp.http_app()

# Ajout WebSocket route
if ENABLE_BROWSER_CONTROL:
    app.routes.append(WebSocketRoute("/ws", websocket_endpoint))

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key middleware
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for health and WebSocket
        if request.url.path in ["/health", "/ws"] or request.headers.get("upgrade") == "websocket":
            return await call_next(request)
        
        # Si pas d'API key configurée, passer
        if not API_KEY:
            return await call_next(request)
        
        # Vérifier l'API key
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        if api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API Key")
        
        return await call_next(request)

app.add_middleware(APIKeyMiddleware)

# ---------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------
def cleanup():
    logger.info("🛑 Arrêt du serveur MCP ComfyUI")

atexit.register(cleanup)
signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

# ---------------------------------------------------------------------
# ROUTE DE DÉBOGAGE (VERSION UNIQUE ET AMÉLIORÉE)
# ---------------------------------------------------------------------
@mcp.custom_route("/debug/health", methods=["GET"])
async def debug_health(request: Request):
    import platform
    info = {}

    # Chemins utiles
    info["COMFYUI_ROOT"] = str(COMFYUI_ROOT) if COMFYUI_ROOT else None
    info["CUSTOM_NODES_DIR"] = str(CUSTOM_NODES_DIR) if CUSTOM_NODES_DIR else None
    info["WORKFLOWS_DIR"] = str(WORKFLOWS_DIR) if WORKFLOWS_DIR else None

    # Versions
    info["python"] = platform.python_version()
    try:
        import fastmcp
        info["fastmcp"] = getattr(fastmcp, "__version__", "unknown")
    except Exception:
        info["fastmcp"] = "unknown"

    # Compte d'outils enregistrés
    names = set()
    try:
        tm = getattr(mcp, "_tool_manager", mcp)
        names.update(getattr(tm, "tools", {}).keys())
        names.update(getattr(tm, "_tools", {}).keys())
    except Exception:
        pass

    info["tool_count"] = len(names)
    info["tools_sample"] = sorted(list(names))[:50]

    return JSONResponse({"status": "success", "health": info})

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
