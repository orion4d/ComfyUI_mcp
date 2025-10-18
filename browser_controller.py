"""
Contrôleur pour envoyer des commandes à l'extension Chrome via WebSocket.
Compatible avec le ConnectionManager du serveur MCP.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class BrowserController:
    """
    Contrôleur pour envoyer des commandes à l'extension Chrome.
    Utilise le WebSocket ConnectionManager au lieu de Playwright.
    """
    
    def __init__(self, manager):
        """
        Initialise le contrôleur avec le WebSocket manager.
        
        Args:
            manager: Instance de ConnectionManager pour WebSocket
        """
        self.manager = manager
        logger.info("BrowserController initialisé avec WebSocket manager")
    
    async def click_element(self, selector: str) -> Dict[str, Any]:
        """
        Envoie une commande de clic à l'extension Chrome.
        
        Args:
            selector: Sélecteur CSS de l'élément
            
        Returns:
            dict: Confirmation de l'envoi
        """
        command = {
            "action": "click",
            "selector": selector
        }
        
        await self.manager.send_command(command)
        logger.info(f"Commande click envoyée: {selector}")
        
        return {
            "status": "sent",
            "action": "click",
            "selector": selector,
            "message": f"Commande envoyée à {len(self.manager.active_connections)} extension(s)"
        }
    
    async def fill_input(self, selector: str, text: str) -> Dict[str, Any]:
        """
        Envoie une commande pour remplir un champ texte.
        
        Args:
            selector: Sélecteur CSS du champ
            text: Texte à insérer
            
        Returns:
            dict: Confirmation de l'envoi
        """
        command = {
            "action": "fill",
            "selector": selector,
            "text": text
        }
        
        await self.manager.send_command(command)
        logger.info(f"Commande fill envoyée: {selector} = '{text[:50]}'")
        
        return {
            "status": "sent",
            "action": "fill",
            "selector": selector,
            "text": text,
            "message": f"Commande envoyée à {len(self.manager.active_connections)} extension(s)"
        }
    
    async def get_workflow(self) -> Dict[str, Any]:
        """
        Demande à l'extension de récupérer le workflow actuel.
        
        Returns:
            dict: Confirmation (workflow sera affiché dans la console de l'extension)
        """
        command = {
            "action": "get_workflow"
        }
        
        await self.manager.send_command(command)
        logger.info("Commande get_workflow envoyée")
        
        return {
            "status": "sent",
            "action": "get_workflow",
            "message": "Le workflow sera affiché dans la console de l'extension Chrome (F12)",
            "connections": len(self.manager.active_connections)
        }
    
    async def execute_script(self, script: str) -> Dict[str, Any]:
        """
        Envoie du JavaScript arbitraire à exécuter.
        
        Args:
            script: Code JavaScript à exécuter
            
        Returns:
            dict: Confirmation de l'envoi
        """
        command = {
            "action": "execute_js",
            "script": script
        }
        
        await self.manager.send_command(command)
        logger.info(f"Script JS envoyé: {script[:100]}")
        
        return {
            "status": "sent",
            "action": "execute_js",
            "message": f"Script envoyé à {len(self.manager.active_connections)} extension(s)"
        }
