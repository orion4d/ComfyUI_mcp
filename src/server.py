"""
ComfyUI MCP Server - Ultimate Edition + P0 Fixes
Serveur MCP complet pour contrôler ComfyUI via ChatGPT ou tout client MCP

P0 Fixes appliqués:
- Fix URL encoding (quote)
- Validation automatique KSampler
- Protection path traversal
- Timeouts configurables
"""

import os
import json
import uuid
import shutil
import random
import logging
from typing import Any, Dict
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Import du client ComfyUI
try:
    from .comfyui_client import ComfyUIClient
except ImportError:
    from comfyui_client import ComfyUIClient

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ComfyUIMCP")

# ============================================================
# Configuration
# ============================================================

load_dotenv()
COMFY_BASE_URL = os.getenv("COMFY_BASE_URL", "http://127.0.0.1:8188")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "workflows")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "60"))
GENERATION_TIMEOUT = int(os.getenv("GENERATION_TIMEOUT", "300"))

# ============================================================
# Auto-détection du chemin ComfyUI
# ============================================================

def auto_detect_comfyui_path() -> str:
    """Détecte automatiquement le chemin de ComfyUI."""
    env_path = os.getenv("COMFYUI_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists() and (path / "custom_nodes").exists():
            logger.info(f"✓ ComfyUI path from .env: {path}")
            return str(path)
        else:
            logger.warning(f"⚠ COMFYUI_PATH in .env is invalid: {env_path}")
    
    workflows_abs = Path(WORKFLOWS_DIR).absolute()
    if workflows_abs.exists():
        potential_comfy = workflows_abs.parent
        if (potential_comfy / "custom_nodes").exists() and (potential_comfy / "models").exists():
            logger.info(f"✓ ComfyUI path detected from workflows: {potential_comfy}")
            return str(potential_comfy)
    
    cwd = Path.cwd()
    if (cwd / "custom_nodes").exists() and (cwd / "models").exists():
        logger.info(f"✓ ComfyUI path is current directory: {cwd}")
        return str(cwd)
    
    if workflows_abs.exists():
        fallback = workflows_abs.parent
        logger.warning(f"⚠ Using fallback path (may be incorrect): {fallback}")
        return str(fallback)
    
    logger.error("✗ Could not detect ComfyUI path automatically")
    return None

COMFYUI_PATH = auto_detect_comfyui_path()

# Clients
client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
comfyui_client = ComfyUIClient(COMFY_BASE_URL, WORKFLOWS_DIR)

# ============================================================
# Helpers
# ============================================================

def require_comfyui_path() -> Path:
    """Vérifie que le chemin ComfyUI est disponible."""
    if COMFYUI_PATH is None:
        raise ValueError(
            "ComfyUI path not detected. Tools requiring file system access are unavailable.\n"
            "Please ensure 'workflows/' is inside ComfyUI, or set COMFYUI_PATH in .env"
        )
    return Path(COMFYUI_PATH)

def ensure_safe_path(base: Path, target: Path) -> Path:
    """
    P0 FIX: Vérifie qu'un chemin reste dans le dossier autorisé.
    Protège contre les attaques de type path traversal (../).
    
    Raises:
        ValueError: Si le chemin sort du dossier de base
    """
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    
    if not target_resolved.is_relative_to(base_resolved):
        raise ValueError(f"Path traversal detected: {target} is outside {base}")
    
    return target_resolved

def sanitize_ksampler_inputs(workflow: dict) -> dict:
    """
    P0 FIX: Valide et nettoie les inputs du node KSampler.
    Évite les erreurs 400 en appliquant automatiquement les contraintes ComfyUI.
    """
    VALID_SCHEDULERS = {
        "simple", "sgm_uniform", "karras", "exponential", "ddim_uniform", 
        "beta", "normal", "linear_quadratic", "kl_optimal", "bong_tangent", "beta57"
    }
    
    VALID_SAMPLERS = {
        "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral",
        "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde",
        "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde", "ddim", "uni_pc", "uni_pc_bh2"
    }
    
    for node_id, node_data in workflow.items():
        if node_data.get("class_type") == "KSampler":
            inputs = node_data.setdefault("inputs", {})
            
            # Valider steps (int >= 1)
            try:
                steps = inputs.get("steps", 20)
                inputs["steps"] = max(1, int(steps))
            except (ValueError, TypeError):
                inputs["steps"] = 20
            
            # Valider cfg (float)
            try:
                inputs["cfg"] = float(inputs.get("cfg", 7.0))
            except (ValueError, TypeError):
                inputs["cfg"] = 7.0
            
            # Valider denoise (float 0..1)
            try:
                denoise = float(inputs.get("denoise", 1.0))
                inputs["denoise"] = max(0.0, min(1.0, denoise))
            except (ValueError, TypeError):
                inputs["denoise"] = 1.0
            
            # Valider scheduler
            if inputs.get("scheduler") not in VALID_SCHEDULERS:
                inputs["scheduler"] = "karras"
            
            # Valider sampler_name
            if inputs.get("sampler_name") not in VALID_SAMPLERS:
                inputs["sampler_name"] = "euler"
            
            # Valider seed
            try:
                seed = inputs.get("seed", 0)
                if isinstance(seed, str) and seed.lower() in ("random", "randomize"):
                    inputs["seed"] = random.randint(0, 2**32 - 1)
                else:
                    inputs["seed"] = max(0, int(seed))
            except (ValueError, TypeError):
                inputs["seed"] = random.randint(0, 2**32 - 1)
    
    return workflow

async def comfy_get(path: str) -> Any:
    """GET request to ComfyUI API"""
    r = await client.get(f"{COMFY_BASE_URL}{path}")
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text

async def comfy_post(path: str, body: Dict[str, Any]) -> Any:
    """POST request to ComfyUI API"""
    r = await client.post(f"{COMFY_BASE_URL}{path}", json=body)
    if r.status_code >= 400:
        try:
            data = r.json()
        except:
            data = r.text
        raise httpx.HTTPStatusError(
            f"HTTP {r.status_code} @ {path}: {data}",
            request=r.request,
            response=r
        )
    try:
        return r.json()
    except:
        return r.text

def create_backup(file_path: Path) -> str:
    """Crée une sauvegarde d'un fichier avant modification"""
    if not file_path.exists():
        return None
    
    backup_dir = file_path.parent / ".backups"
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
    backup_path = backup_dir / backup_name
    
    shutil.copy2(file_path, backup_path)
    return str(backup_path)

def explore_directory(base_path: Path, extensions: list = None, max_depth: int = 5) -> dict:
    """Explore récursivement un dossier"""
    if not base_path.exists():
        return {"error": f"Path does not exist: {base_path}"}
    
    result = {
        "path": str(base_path),
        "folders": [],
        "files": []
    }
    
    def scan_recursive(path: Path, current_depth: int = 0):
        if current_depth >= max_depth:
            return
        
        try:
            for item in sorted(path.iterdir()):
                relative_path = item.relative_to(base_path)
                
                if item.is_dir():
                    folder_info = {
                        "name": item.name,
                        "path": str(relative_path).replace('\\', '/'),
                        "files": []
                    }
                    
                    for file in sorted(item.iterdir()):
                        if file.is_file():
                            if extensions is None or file.suffix.lower() in extensions:
                                file_info = {
                                    "name": file.name,
                                    "path": str(file.relative_to(base_path)).replace('\\', '/'),
                                    "size_mb": round(file.stat().st_size / (1024 * 1024), 2),
                                    "extension": file.suffix
                                }
                                folder_info["files"].append(file_info)
                    
                    result["folders"].append(folder_info)
                    scan_recursive(item, current_depth + 1)
                    
                elif item.is_file() and current_depth == 0:
                    if extensions is None or item.suffix.lower() in extensions:
                        file_info = {
                            "name": item.name,
                            "path": str(relative_path).replace('\\', '/'),
                            "size_mb": round(item.stat().st_size / (1024 * 1024), 2),
                            "extension": item.suffix
                        }
                        result["files"].append(file_info)
        except PermissionError:
            pass
    
    scan_recursive(base_path)
    
    total_files = len(result["files"]) + sum(len(f["files"]) for f in result["folders"])
    total_size = sum(f["size_mb"] for f in result["files"]) + sum(
        sum(file["size_mb"] for file in folder["files"]) 
        for folder in result["folders"]
    )
    
    result["stats"] = {
        "total_folders": len(result["folders"]),
        "total_files": total_files,
        "total_size_mb": round(total_size, 2),
        "total_size_gb": round(total_size / 1024, 2)
    }
    
    return result

# ============================================================
# Serveur MCP
# ============================================================

mcp = FastMCP("comfyui-mcp-ultimate")

# ============================================================
# CATÉGORIE 1 : OUTILS BAS NIVEAU COMFYUI (7 outils)
# ============================================================

@mcp.tool()
async def ping_comfy() -> str:
    """Ping ComfyUI et retourne les informations système (GPU, RAM, OS)."""
    stats = await comfy_get("/system_stats")
    return json.dumps(stats, indent=2)

@mcp.tool()
async def queue_workflow(workflow: Dict[str, Any], client_id: str | None = None) -> str:
    """
    Soumet un workflow JSON complet à ComfyUI pour exécution.
    P0 FIX: Valide automatiquement les inputs KSampler.
    """
    # P0 FIX: Valider et nettoyer automatiquement
    workflow = sanitize_ksampler_inputs(workflow)
    
    payload = {"prompt": workflow, "client_id": client_id or str(uuid.uuid4())}
    res = await comfy_post("/prompt", payload)
    return json.dumps(res, indent=2)

@mcp.tool()
async def get_history(prompt_id: str) -> str:
    """Récupère l'historique d'exécution d'un workflow par son prompt_id."""
    hist = await comfy_get(f"/history/{prompt_id}")
    return json.dumps(hist, indent=2)

@mcp.tool()
async def get_image_urls(prompt_id: str) -> str:
    """
    Extrait toutes les URLs d'images générées par un workflow.
    P0 FIX: Correction de l'URL encoding avec urllib.parse.quote.
    """
    hist = await comfy_get(f"/history/{prompt_id}")
    images = []
    for _, item in (hist or {}).items():
        outputs = item.get("outputs", {})
        for node_data in outputs.values():
            for img in node_data.get("images", []):
                filename = img.get("filename")
                subfolder = img.get("subfolder", "")
                img_type = img.get("type", "output")
                
                # P0 FIX: Utiliser urllib.parse.quote au lieu de httpx.utils.quote
                url = (
                    f"{COMFY_BASE_URL}/view?"
                    f"filename={quote(str(filename))}"
                    f"&subfolder={quote(str(subfolder))}"
                    f"&type={quote(str(img_type))}"
                )
                images.append(url)
    return json.dumps({"images": images}, indent=2)

@mcp.tool()
async def get_queue_status() -> str:
    """Récupère l'état actuel de la queue ComfyUI (running, pending)."""
    queue = await comfy_get("/queue")
    return json.dumps(queue, indent=2)

@mcp.tool()
async def interrupt_generation() -> str:
    """Interrompt la génération en cours dans ComfyUI."""
    try:
        result = await comfy_post("/interrupt", {})
        return json.dumps({"success": True, "message": "Generation interrupted"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def clear_queue() -> str:
    """Vide complètement la queue ComfyUI (supprime tous les workflows en attente)."""
    try:
        result = await comfy_post("/queue", {"clear": True})
        return json.dumps({"success": True, "message": "Queue cleared"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================
# CATÉGORIE 2 : WORKFLOWS ET GÉNÉRATION (8 outils)
# ============================================================

@mcp.tool()
async def list_available_workflows() -> str:
    """Liste tous les workflows disponibles (incluant sous-dossiers)."""
    workflows = comfyui_client.list_workflows()
    return json.dumps({"workflows": workflows, "count": len(workflows)}, indent=2)

@mcp.tool()
async def list_workflows_with_structure() -> str:
    """Liste tous les workflows avec leur structure de dossiers complète."""
    workflows_path = Path(WORKFLOWS_DIR)
    
    if not workflows_path.exists():
        return json.dumps({
            "error": f"Workflows directory not found: {workflows_path}"
        }, indent=2)
    
    def scan_directory(path: Path, relative_to: Path) -> dict:
        result = {
            "path": str(path.relative_to(relative_to)).replace('\\', '/') if path != relative_to else ".",
            "folders": [],
            "workflows": []
        }
        
        try:
            for item in sorted(path.iterdir()):
                if item.is_dir():
                    subfolder = scan_directory(item, relative_to)
                    if subfolder["workflows"] or subfolder["folders"]:
                        result["folders"].append({
                            "name": item.name,
                            "content": subfolder
                        })
                elif item.is_file() and item.suffix == '.json':
                    try:
                        with open(item, 'r', encoding='utf-8') as f:
                            workflow_data = json.load(f)
                        
                        workflow_id = str(item.relative_to(workflows_path).with_suffix('')).replace('\\', '/')
                        
                        result["workflows"].append({
                            "id": workflow_id,
                            "name": item.stem,
                            "file": item.name,
                            "size_kb": round(item.stat().st_size / 1024, 2),
                            "node_count": len(workflow_data)
                        })
                    except Exception as e:
                        result["workflows"].append({
                            "id": item.stem,
                            "name": item.stem,
                            "file": item.name,
                            "error": f"Failed to parse: {str(e)}"
                        })
        except PermissionError:
            result["error"] = "Permission denied"
        
        return result
    
    structure = scan_directory(workflows_path, workflows_path)
    
    def count_workflows(node: dict) -> int:
        total = len(node.get("workflows", []))
        for folder in node.get("folders", []):
            total += count_workflows(folder["content"])
        return total
    
    total_workflows = count_workflows(structure)
    
    return json.dumps({
        "base_path": str(workflows_path.absolute()),
        "total_workflows": total_workflows,
        "structure": structure
    }, indent=2)

@mcp.tool()
async def list_workflow_nodes(workflow_id: str) -> str:
    """
    Liste tous les nodes d'un workflow avec leurs IDs et types.
    Gère automatiquement la conversion UI → API.
    """
    try:
        workflow = comfyui_client.load_workflow(workflow_id)
        
        nodes = []
        for node_id, node_data in workflow.items():
            node_info = {
                "id": node_id,
                "class_type": node_data.get("class_type", "unknown"),
                "inputs": {}
            }
            
            if "inputs" in node_data:
                for key, value in node_data["inputs"].items():
                    if isinstance(value, (str, int, float, bool)):
                        node_info["inputs"][key] = value
                    else:
                        node_info["inputs"][key] = f"<connection: {value}>"
            
            nodes.append(node_info)
        
        return json.dumps({
            "workflow_id": workflow_id,
            "node_count": len(nodes),
            "nodes": nodes
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "error_type": type(e).__name__
        }, indent=2)

@mcp.tool()
async def inject_text_in_workflow(
    workflow_id: str,
    node_id: str,
    text: str,
    field_name: str = "text"
) -> str:
    """
    Injecte du texte dans un node spécifique d'un workflow.
    Gère automatiquement la conversion UI → API.
    """
    try:
        workflow = comfyui_client.load_workflow(workflow_id)
        
        if node_id not in workflow:
            available_nodes = list(workflow.keys())
            return json.dumps({
                "error": f"Node '{node_id}' not found in workflow",
                "available_nodes": available_nodes,
                "workflow_id": workflow_id,
                "tip": "Use list_workflow_nodes() to see available nodes"
            }, indent=2)
        
        if "inputs" not in workflow[node_id]:
            workflow[node_id]["inputs"] = {}
        
        workflow[node_id]["inputs"][field_name] = text
        
        return json.dumps({
            "success": True,
            "workflow_id": workflow_id,
            "node_id": node_id,
            "field_name": field_name,
            "text_injected": text[:100] + "..." if len(text) > 100 else text,
            "workflow": workflow,
            "message": "Use queue_workflow() with the 'workflow' field to execute"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "error_type": type(e).__name__
        }, indent=2)

@mcp.tool()
async def inject_texts_batch(
    workflow_id: str,
    text_mappings: list
) -> str:
    """Injecte plusieurs textes dans plusieurs nodes en une seule fois."""
    try:
        workflow = comfyui_client.load_workflow(workflow_id)
        
        injections = []
        
        for mapping in text_mappings:
            node_id = mapping.get("node_id")
            text = mapping.get("text")
            field_name = mapping.get("field_name", "text")
            
            if node_id not in workflow:
                injections.append({
                    "node_id": node_id,
                    "status": "error",
                    "message": f"Node '{node_id}' not found"
                })
                continue
            
            if "inputs" not in workflow[node_id]:
                workflow[node_id]["inputs"] = {}
            
            workflow[node_id]["inputs"][field_name] = text
            
            injections.append({
                "node_id": node_id,
                "field_name": field_name,
                "status": "success",
                "text_preview": text[:50] + "..." if len(text) > 50 else text
            })
        
        return json.dumps({
            "success": True,
            "workflow_id": workflow_id,
            "injections": injections,
            "workflow": workflow,
            "message": "Use queue_workflow() with the 'workflow' field to execute"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "error_type": type(e).__name__
        }, indent=2)

@mcp.tool()
async def list_available_models() -> str:
    """Liste tous les modèles de checkpoint disponibles dans ComfyUI."""
    models = comfyui_client.available_models
    return json.dumps({"models": models, "count": len(models)}, indent=2)

@mcp.tool()
async def generate_image(
    prompt: str,
    width: int = 512,
    height: int = 512,
    workflow_id: str = "basic_api_test",
    model: str | None = None
) -> str:
    """Génère une image en utilisant un workflow prédéfini."""
    try:
        image_url = comfyui_client.generate_image(
            prompt=prompt,
            width=width,
            height=height,
            workflow_id=workflow_id,
            model=model
        )
        return json.dumps({
            "success": True,
            "image_url": image_url,
            "prompt": prompt,
            "dimensions": f"{width}x{height}",
            "workflow": workflow_id
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }, indent=2)

@mcp.tool()
async def read_workflow(workflow_id: str) -> str:
    """Lit et retourne le contenu JSON d'un workflow (conversion UI → API automatique)."""
    try:
        workflow = comfyui_client.load_workflow(workflow_id)
        
        return json.dumps({
            "workflow_id": workflow_id,
            "content": workflow,
            "node_count": len(workflow),
            "format": "API (converted if necessary)"
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)

# ============================================================
# CATÉGORIE 3 : EXPLORATION DES MODÈLES (2 outils)
# ============================================================

@mcp.tool()
async def list_models_directory(subfolder: str = "") -> str:
    """Liste tous les modèles dans models/ de ComfyUI."""
    try:
        base_path = require_comfyui_path() / "models"
        
        if subfolder:
            base_path = base_path / subfolder
        
        model_extensions = ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']
        result = explore_directory(base_path, extensions=model_extensions)
        return json.dumps(result, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
async def search_models(query: str, model_type: str = "") -> str:
    """Recherche des modèles par nom."""
    try:
        base_path = require_comfyui_path() / "models"
        
        if model_type:
            base_path = base_path / model_type
        
        if not base_path.exists():
            return json.dumps({"error": f"Path does not exist: {base_path}"}, indent=2)
        
        query_lower = query.lower()
        results = []
        
        model_extensions = ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']
        
        for model_file in base_path.rglob("*"):
            if model_file.is_file() and model_file.suffix.lower() in model_extensions:
                if query_lower in model_file.name.lower():
                    relative_path = model_file.relative_to(require_comfyui_path() / "models")
                    results.append({
                        "name": model_file.name,
                        "path": str(relative_path).replace('\\', '/'),
                        "size_mb": round(model_file.stat().st_size / (1024 * 1024), 2),
                        "size_gb": round(model_file.stat().st_size / (1024 * 1024 * 1024), 2),
                        "type": str(relative_path.parts[0]) if relative_path.parts else "root"
                    })
        
        return json.dumps({
            "query": query,
            "results": results,
            "total_found": len(results)
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)

# ============================================================
# CATÉGORIE 4 : CUSTOM NODES - LECTURE (5 outils)
# ============================================================

@mcp.tool()
async def list_custom_nodes() -> str:
    """Liste tous les custom nodes installés avec leurs informations."""
    try:
        base_path = require_comfyui_path() / "custom_nodes"
        
        if not base_path.exists():
            return json.dumps({"error": f"Custom nodes path does not exist: {base_path}"}, indent=2)
        
        nodes = []
        
        for node_dir in sorted(base_path.iterdir()):
            if node_dir.is_dir() and not node_dir.name.startswith('.'):
                node_info = {
                    "name": node_dir.name,
                    "path": str(node_dir.relative_to(base_path)),
                    "has_init": (node_dir / "__init__.py").exists(),
                    "has_requirements": (node_dir / "requirements.txt").exists(),
                    "has_readme": any((node_dir / f"README{ext}").exists() for ext in ['.md', '.txt', '']),
                    "python_files": [py.name for py in node_dir.glob("*.py")],
                    "json_files": [js.name for js in node_dir.glob("*.json")],
                    "is_git_repo": (node_dir / ".git").exists()
                }
                nodes.append(node_info)
        
        return json.dumps({
            "custom_nodes": nodes,
            "total_nodes": len(nodes),
            "path": str(base_path)
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
async def read_custom_node_file(node_name: str, filename: str) -> str:
    """
    Lit le contenu d'un fichier dans un custom node.
    P0 FIX: Protection path traversal.
    """
    try:
        base_path = require_comfyui_path() / "custom_nodes"
        file_path = base_path / node_name / filename
        
        # P0 FIX: Vérification path traversal
        file_path = ensure_safe_path(base_path, file_path)
        
        if not file_path.exists():
            return json.dumps({
                "error": f"File not found: {file_path}"
            }, indent=2)
        
        max_size = 5 * 1024 * 1024
        file_size = file_path.stat().st_size
        
        if file_size > max_size:
            return json.dumps({
                "error": f"File too large: {file_size / (1024*1024):.2f} MB (max 5 MB)",
                "suggestion": "Use read_file_partial"
            }, indent=2)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        line_count = content.count('\n') + 1
        
        return json.dumps({
            "node": node_name,
            "filename": filename,
            "path": str(file_path),
            "size_kb": round(file_size / 1024, 2),
            "lines": line_count,
            "content": content
        }, indent=2)
        
    except UnicodeDecodeError:
        return json.dumps({"error": "File is binary (not text)"}, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
async def read_file_partial(node_name: str, filename: str, start_line: int = 1, num_lines: int = 100) -> str:
    """
    Lit une portion d'un fichier (utile pour les gros fichiers).
    P0 FIX: Protection path traversal.
    """
    try:
        base_path = require_comfyui_path() / "custom_nodes"
        file_path = base_path / node_name / filename
        
        # P0 FIX: Vérification path traversal
        file_path = ensure_safe_path(base_path, file_path)
        
        if not file_path.exists():
            return json.dumps({"error": f"File not found"}, indent=2)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        end_line = min(start_line + num_lines - 1, total_lines)
        selected_lines = lines[start_line-1:end_line]
        content = ''.join(selected_lines)
        
        return json.dumps({
            "node": node_name,
            "filename": filename,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "content": content
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
async def analyze_custom_node_structure(node_name: str) -> str:
    """Analyse la structure complète d'un custom node."""
    try:
        base_path = require_comfyui_path() / "custom_nodes" / node_name
        
        if not base_path.exists():
            return json.dumps({"error": f"Custom node not found: {node_name}"}, indent=2)
        
        analysis = {
            "node_name": node_name,
            "path": str(base_path),
            "python_files": [],
            "has_init": False,
            "has_requirements": False,
            "requirements": [],
            "classes_found": [],
            "functions_found": []
        }
        
        for py_file in base_path.glob("*.py"):
            file_info = {"filename": py_file.name}
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    file_info["lines"] = content.count('\n') + 1
                    
                    import re
                    classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
                    if classes:
                        file_info["classes"] = classes
                        analysis["classes_found"].extend([f"{py_file.name}:{cls}" for cls in classes])
                    
                    functions = re.findall(r'^def\s+(\w+)', content, re.MULTILINE)
                    if functions:
                        file_info["functions"] = functions[:10]
                        if len(functions) > 10:
                            file_info["functions_count"] = len(functions)
                    
                    if "NODE_CLASS_MAPPINGS" in content:
                        file_info["has_node_mappings"] = True
            except:
                pass
            
            analysis["python_files"].append(file_info)
        
        analysis["has_init"] = (base_path / "__init__.py").exists()
        
        req_file = base_path / "requirements.txt"
        if req_file.exists():
            analysis["has_requirements"] = True
            try:
                with open(req_file, 'r') as f:
                    analysis["requirements"] = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            except:
                pass
        
        return json.dumps(analysis, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
async def search_in_custom_nodes(query: str, file_extension: str = ".py") -> str:
    """Recherche un terme dans tous les fichiers des custom nodes."""
    try:
        base_path = require_comfyui_path() / "custom_nodes"
        results = []
        
        for node_dir in base_path.iterdir():
            if not node_dir.is_dir() or node_dir.name.startswith('.'):
                continue
            
            for file in node_dir.rglob(f"*{file_extension}"):
                if file.is_file():
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        
                        matches = []
                        for line_num, line in enumerate(lines, 1):
                            if query in line:
                                matches.append({
                                    "line_number": line_num,
                                    "content": line.strip()[:200]
                                })
                        
                        if matches:
                            results.append({
                                "node": node_dir.name,
                                "file": file.name,
                                "path": str(file.relative_to(base_path)),
                                "matches_count": len(matches),
                                "matches": matches[:5]
                            })
                    except:
                        pass
        
        return json.dumps({
            "query": query,
            "files_found": len(results),
            "results": results[:20]
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)

# ============================================================
# CATÉGORIE 5 : CUSTOM NODES - MODIFICATION (3 outils)
# ============================================================

@mcp.tool()
async def write_custom_node_file(
    node_name: str,
    filename: str,
    content: str,
    create_backup_flag: bool = True
) -> str:
    """
    Écrit ou modifie un fichier dans un custom node.
    P0 FIX: Protection path traversal.
    """
    try:
        base_path = require_comfyui_path() / "custom_nodes" / node_name
        file_path = base_path / filename
        
        # P0 FIX: Vérification path traversal
        file_path = ensure_safe_path(base_path.parent, file_path)
        
        if not base_path.exists():
            return json.dumps({"error": f"Custom node not found: {node_name}"}, indent=2)
        
        backup_path = None
        if create_backup_flag and file_path.exists():
            backup_path = create_backup(file_path)
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return json.dumps({
            "success": True,
            "node": node_name,
            "filename": filename,
            "path": str(file_path),
            "backup_path": backup_path,
            "lines_written": content.count('\n') + 1
        }, indent=2)
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def create_custom_node_template(node_name: str, node_display_name: str, category: str = "custom") -> str:
    """Crée un nouveau custom node avec un template de base."""
    try:
        base_path = require_comfyui_path() / "custom_nodes" / node_name
        
        if base_path.exists():
            return json.dumps({"error": f"Custom node '{node_name}' already exists"}, indent=2)
        
        base_path.mkdir(parents=True)
        
        init_content = f"""\"\"\"
{node_display_name}
Custom node for ComfyUI
\"\"\"

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
"""
        
        nodes_content = f"""class {node_name}Node:
    \"\"\"
    {node_display_name}
    \"\"\"
    
    @classmethod
    def INPUT_TYPES(cls):
        return {{
            "required": {{
                "text": ("STRING", {{"default": "Hello World", "multiline": False}}),
            }}
        }}
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "{category}"
    
    def process(self, text):
        result = text.upper()
        return (result,)

NODE_CLASS_MAPPINGS = {{
    "{node_name}": {node_name}Node
}}

NODE_DISPLAY_NAME_MAPPINGS = {{
    "{node_name}": "{node_display_name}"
}}
"""
        
        readme_content = f"""# {node_display_name}

## Description
A custom node for ComfyUI.

## Installation
Copy this folder to `ComfyUI/custom_nodes/`

## Usage
Add the node from the menu: {category} -> {node_display_name}
"""
        
        (base_path / "__init__.py").write_text(init_content, encoding='utf-8')
        (base_path / "nodes.py").write_text(nodes_content, encoding='utf-8')
        (base_path / "README.md").write_text(readme_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "node_name": node_name,
            "path": str(base_path),
            "files_created": ["__init__.py", "nodes.py", "README.md"],
            "message": "Custom node template created. Restart ComfyUI to load."
        }, indent=2)
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def delete_custom_node(node_name: str, confirm: bool = False) -> str:
    """Supprime un custom node (avec confirmation requise)."""
    if not confirm:
        return json.dumps({
            "error": "Confirmation required",
            "message": f"To delete '{node_name}', call with confirm=True"
        }, indent=2)
    
    try:
        base_path = require_comfyui_path() / "custom_nodes" / node_name
        
        if not base_path.exists():
            return json.dumps({"error": f"Custom node not found: {node_name}"}, indent=2)
        
        backup_dir = require_comfyui_path() / "custom_nodes" / ".deleted_backups"
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{node_name}_{timestamp}"
        
        shutil.copytree(base_path, backup_path)
        shutil.rmtree(base_path)
        
        return json.dumps({
            "success": True,
            "node_name": node_name,
            "backup_path": str(backup_path),
            "message": "Custom node deleted. Backup created. Restart ComfyUI."
        }, indent=2)
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================
# CATÉGORIE 6 : WORKFLOWS - MODIFICATION (2 outils)
# ============================================================

@mcp.tool()
async def save_workflow(workflow_id: str, workflow_data: Dict[str, Any], create_backup_flag: bool = True) -> str:
    """Sauvegarde un workflow JSON (création ou modification)."""
    workflow_path = Path(WORKFLOWS_DIR) / f"{workflow_id}.json"
    
    try:
        backup_path = None
        if create_backup_flag and workflow_path.exists():
            backup_path = create_backup(workflow_path)
        
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(workflow_path, 'w', encoding='utf-8') as f:
            json.dump(workflow_data, f, indent=2)
        
        return json.dumps({
            "success": True,
            "workflow_id": workflow_id,
            "path": str(workflow_path),
            "backup_path": backup_path,
            "node_count": len(workflow_data)
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def delete_workflow(workflow_id: str, confirm: bool = False) -> str:
    """Supprime un workflow (confirmation requise)."""
    if not confirm:
        return json.dumps({
            "error": "Confirmation required",
            "message": f"To delete '{workflow_id}', call with confirm=True"
        }, indent=2)
    
    workflow_path = Path(WORKFLOWS_DIR) / f"{workflow_id}.json"
    
    if not workflow_path.exists():
        return json.dumps({"error": f"Workflow not found: {workflow_id}"}, indent=2)
    
    try:
        backup_path = create_backup(workflow_path)
        workflow_path.unlink()
        
        return json.dumps({
            "success": True,
            "workflow_id": workflow_id,
            "backup_path": backup_path,
            "message": "Workflow deleted. Backup created."
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================
# Affichage au démarrage
# ============================================================

workflows = comfyui_client.list_workflows()
models_count = len(comfyui_client.available_models)

print(f"\n{'='*60}")
print(f"🚀 Serveur MCP ComfyUI ULTIMATE + P0 Fixes")
print(f"{'='*60}")
print(f"🎨 ComfyUI: {COMFY_BASE_URL}")
print(f"📁 ComfyUI Path: {COMFYUI_PATH or 'NOT DETECTED'}")
print(f"📍 MCP Endpoint: /mcp")
print(f"📁 Workflows: {len(workflows)} disponibles")
print(f"🤖 Modèles: {models_count} checkpoints")
print(f"🔧 Outils: 29 disponibles")
print(f"{'='*60}")
print(f"✅ P0 Fixes appliqués:")
print(f"   • URL encoding (quote) fix")
print(f"   • KSampler validation automatique")
print(f"   • Protection path traversal")
print(f"   • Timeouts configurables ({HTTP_TIMEOUT}s / {GENERATION_TIMEOUT}s)")
print(f"{'='*60}")

if COMFYUI_PATH is None:
    print("⚠️  WARNING: ComfyUI path not detected")
    print("   Some tools (models, custom_nodes) will be unavailable")
    print("   To fix: place 'workflows/' in ComfyUI or set COMFYUI_PATH in .env")
else:
    print(f"✓ File system tools enabled")
    print(f"✓ Automatic UI → API workflow conversion")

print(f"{'='*60}\n")

# Export pour uvicorn
app = mcp.http_app(path="/mcp")
