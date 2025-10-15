import requests
import json
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ComfyUIClient")

DEFAULT_MAPPING = {
    "prompt": ("6", "text"),
    "width": ("5", "width"),
    "height": ("5", "height"),
    "model": ("4", "ckpt_name")
}

class ComfyUIClient:
    def __init__(self, base_url="http://127.0.0.1:8188", workflows_dir="workflows"):
        self.base_url = base_url
        self.workflows_dir = Path(workflows_dir)
        self.available_models = self._get_available_models()

    def _get_available_models(self):
        """Fetch list of available checkpoint models from ComfyUI"""
        try:
            response = requests.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
            if response.status_code != 200:
                logger.warning("Failed to fetch model list; using default handling")
                return []
            
            data = response.json()
            models = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            logger.info(f"Available models: {len(models)} models found")
            return models
        except Exception as e:
            logger.warning(f"Error fetching models: {e}")
            return []

    def list_workflows(self):
        """Liste tous les workflows disponibles (récursif avec sous-dossiers)"""
        if not self.workflows_dir.exists():
            return []
        
        workflows = []
        for json_file in self.workflows_dir.rglob("*.json"):
            relative_path = json_file.relative_to(self.workflows_dir)
            workflow_id = str(relative_path.with_suffix('')).replace('\\', '/')
            workflows.append(workflow_id)
        
        return sorted(workflows)

    def _is_ui_format(self, workflow: dict) -> bool:
        """Détecte si le workflow est au format UI ou API"""
        return "nodes" in workflow and "links" in workflow

    def _convert_ui_to_api(self, ui_workflow: dict) -> dict:
        """
        Convertit un workflow UI ComfyUI en format API.
        Version améliorée qui gère correctement les widgets.
        """
        logger.info("Converting workflow from UI format to API format")
        
        api_workflow = {}
        nodes = ui_workflow.get("nodes", [])
        links = ui_workflow.get("links", [])
        
        # Créer un mapping link_id -> (source_node_id, source_slot)
        link_map = {}
        for link in links:
            if len(link) >= 5:
                link_id = link[0]
                source_node_id = str(link[1])
                source_slot = link[2]
                link_map[link_id] = (source_node_id, source_slot)
        
        # Convertir chaque node
        for node in nodes:
            node_id = str(node["id"])
            node_type = node.get("type")
            
            if not node_type:
                logger.warning(f"Node {node_id} has no type, skipping")
                continue
            
            inputs = {}
            
            # Récupérer la définition des inputs du node
            node_inputs = node.get("inputs", [])
            
            # 1. D'ABORD : Traiter les connections (links)
            #    Ces inputs NE DOIVENT PAS être dans widgets_values
            for input_def in node_inputs:
                link_id = input_def.get("link")
                if link_id is not None and link_id in link_map:
                    source_node_id, source_slot = link_map[link_id]
                    input_name = input_def.get("name")
                    if input_name:
                        inputs[input_name] = [source_node_id, source_slot]
            
            # 2. ENSUITE : Traiter les widgets_values
            #    Seulement pour les inputs qui ont un widget (pas de link)
            if "widgets_values" in node and node["widgets_values"]:
                widgets = node["widgets_values"]
                
                # Filtrer les inputs qui sont des widgets (pas des connections)
                widget_inputs = []
                for input_def in node_inputs:
                    # Si l'input a un widget ET n'a pas de link, c'est un widget
                    has_widget = input_def.get("widget") is not None
                    has_link = input_def.get("link") is not None
                    
                    if has_widget and not has_link:
                        widget_inputs.append(input_def["name"])
                
                # Mapper les widgets_values aux bons input names
                for i, value in enumerate(widgets):
                    if i < len(widget_inputs):
                        input_name = widget_inputs[i]
                        inputs[input_name] = value
                    else:
                        logger.warning(f"Node {node_id}: Extra widget value at index {i}: {value}")
            
            # Créer le node au format API
            api_workflow[node_id] = {
                "inputs": inputs,
                "class_type": node_type
            }
            
            logger.debug(f"Node {node_id} ({node_type}): {len(inputs)} inputs converted")
        
        logger.info(f"Converted {len(api_workflow)} nodes from UI to API format")
        return api_workflow

    def load_workflow(self, workflow_id: str) -> dict:
        """
        Charge un workflow et le convertit automatiquement si nécessaire.
        Supporte les sous-dossiers (ex: "flux/upscale")
        """
        workflow_path = self.workflows_dir / f"{workflow_id}.json"
        
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow '{workflow_id}' not found at {workflow_path}")
        
        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
        
        # Détection et conversion automatique
        if self._is_ui_format(workflow):
            logger.info(f"Workflow '{workflow_id}' is in UI format, converting to API format")
            return self._convert_ui_to_api(workflow)
        else:
            logger.info(f"Workflow '{workflow_id}' is already in API format")
            return workflow

    def generate_image(self, prompt, width=512, height=512, workflow_id="basic_api_test", model=None):
        """
        Generate an image using ComfyUI with a predefined workflow.
        Automatically converts UI format workflows to API format.
        """
        # Load workflow (with automatic conversion)
        workflow = self.load_workflow(workflow_id)
        
        # Apply parameters using mapping
        mapping = DEFAULT_MAPPING
        
        # Update prompt
        if "prompt" in mapping:
            node_id, field = mapping["prompt"]
            if node_id in workflow:
                workflow[node_id]["inputs"][field] = prompt
        
        # Update dimensions
        if "width" in mapping:
            node_id, field = mapping["width"]
            if node_id in workflow:
                workflow[node_id]["inputs"][field] = width
        
        if "height" in mapping:
            node_id, field = mapping["height"]
            if node_id in workflow:
                workflow[node_id]["inputs"][field] = height
        
        # Update model if specified
        if model and "model" in mapping:
            node_id, field = mapping["model"]
            if node_id in workflow:
                if self.available_models and model not in self.available_models:
                    logger.warning(f"Model '{model}' not found. Using workflow default.")
                else:
                    workflow[node_id]["inputs"][field] = model
        
        # Submit workflow
        payload = {"prompt": workflow}
        response = requests.post(f"{self.base_url}/prompt", json=payload)
        response.raise_for_status()
        result = response.json()
        
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ValueError("No prompt_id returned from ComfyUI")
        
        logger.info(f"Workflow submitted. Prompt ID: {prompt_id}")
        
        # Poll for completion
        max_wait = 120
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            history_response = requests.get(f"{self.base_url}/history/{prompt_id}")
            history_response.raise_for_status()
            history = history_response.json()
            
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                for node_output in outputs.values():
                    if "images" in node_output:
                        images = node_output["images"]
                        if images:
                            img = images[0]
                            filename = img["filename"]
                            subfolder = img.get("subfolder", "")
                            img_type = img.get("type", "output")
                            
                            url = f"{self.base_url}/view?filename={filename}"
                            if subfolder:
                                url += f"&subfolder={subfolder}"
                            url += f"&type={img_type}"
                            
                            logger.info(f"Image generated: {url}")
                            return url
            
            time.sleep(1)
        
        raise TimeoutError(f"Image generation timed out after {max_wait} seconds")
