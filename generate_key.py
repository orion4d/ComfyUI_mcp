"""
Générateur de clés sécurisées pour le serveur MCP ComfyUI.
Génère MCP_API_KEY (pour ChatGPT) et WEBSOCKET_TOKEN (pour Extension Chrome).
"""

import secrets
from datetime import datetime
from pathlib import Path

def generate_api_key(length: int = 32) -> str:
    """
    Génère une clé API cryptographiquement sécurisée.
    
    Args:
        length: Longueur de la clé (par défaut 32 caractères)
    
    Returns:
        Clé API URL-safe
    """
    return secrets.token_urlsafe(length)

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🔑 Générateur de Clés Sécurisées - Serveur MCP ComfyUI")
    print("="*70 + "\n")
    
    # Générer les clés
    mcp_api_key = generate_api_key(32)
    websocket_token = generate_api_key(32)
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"📅 Date de génération : {date}\n")
    
    print("🔐 Vos clés générées :")
    print("-" * 70)
    print(f"\n1️⃣  MCP_API_KEY (pour ChatGPT via API HTTP):")
    print(f"   {mcp_api_key}\n")
    print(f"2️⃣  WEBSOCKET_TOKEN (pour Extension Chrome):")
    print(f"   {websocket_token}\n")
    
    print("="*70)
    print("📋 CONFIGURATION .env")
    print("="*70)
    print("\nAjoutez ces lignes dans votre fichier .env :\n")
    print(f"MCP_API_KEY={mcp_api_key}")
    print(f"WEBSOCKET_TOKEN={websocket_token}\n")
    
    print("="*70)
    print("📋 CONFIGURATION CHATGPT")
    print("="*70)
    print("\nCustom Action / GPT Configuration:")
    print("  • Authentication Type: API Key")
    print("  • Custom Header Name: X-API-Key")
    print(f"  • API Key: {mcp_api_key}\n")
    
    print("="*70)
    print("📋 CONFIGURATION EXTENSION CHROME")
    print("="*70)
    print("\nDans le popup de l'extension :")
    print("  • URL: ws://127.0.0.1:8000/ws")
    print(f"  • Token: {websocket_token}\n")
    
    print("="*70)
    print("\n⚠️  SÉCURITÉ - IMPORTANT :")
    print("="*70)
    print("  • Ne partagez JAMAIS ces clés")
    print("  • Conservez-les uniquement dans .env (git ignoré)")
    print("  • Regénérez-les si elles sont compromises")
    print("  • Utilisez des clés différentes pour chaque environnement")
    print("\n" + "="*70 + "\n")
    
    # Proposer de sauvegarder
    save = input("💾 Voulez-vous créer/mettre à jour le fichier .env ? (o/n) : ")
    
    if save.lower() in ['o', 'oui', 'y', 'yes']:
        env_path = Path('.env')
        
        # Vérifier si .env existe déjà
        if env_path.exists():
            backup = input("\n⚠️  Le fichier .env existe déjà. Créer une sauvegarde ? (o/n) : ")
            if backup.lower() in ['o', 'oui', 'y', 'yes']:
                backup_path = Path(f'.env.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
                env_path.rename(backup_path)
                print(f"✅ Sauvegarde créée : {backup_path}")
        
        env_content = f"""# Configuration Serveur MCP ComfyUI
# Généré le {date}

# ComfyUI
COMFYUI_BASE_URL=http://127.0.0.1:8188
WORKFLOWS_DIR=workflows
COMFYUI_PATH=D:\\ComfyUI_dev\\ComfyUI

# Sécurité - API Key pour ChatGPT (via HTTP/HTTPS)
MCP_API_KEY={mcp_api_key}

# Sécurité - Token WebSocket pour Extension Chrome
ENABLE_BROWSER_CONTROL=true
WEBSOCKET_TOKEN={websocket_token}

# Timeouts (en secondes)
HTTP_TIMEOUT=60
GENERATION_TIMEOUT=300

# Options navigateur (non utilisé avec Extension Chrome)
BROWSER_HEADLESS=false
"""
        
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print(f"\n✅ Fichier .env créé avec succès !")
        print(f"   Emplacement : {env_path.absolute()}")
        
        # Créer aussi un .env.example (sans les vraies clés)
        env_example_content = f"""# Configuration Serveur MCP ComfyUI
# Exemple de configuration - Générez vos propres clés avec generate_api_key.py

# ComfyUI
COMFYUI_BASE_URL=http://127.0.0.1:8188
WORKFLOWS_DIR=workflows
COMFYUI_PATH=D:\\ComfyUI_dev\\ComfyUI

# Sécurité - API Key pour ChatGPT (via HTTP/HTTPS)
# Générez avec : python generate_api_key.py
MCP_API_KEY=votre_cle_api_ici

# Sécurité - Token WebSocket pour Extension Chrome
ENABLE_BROWSER_CONTROL=true
# Générez avec : python generate_api_key.py
WEBSOCKET_TOKEN=votre_token_websocket_ici

# Timeouts (en secondes)
HTTP_TIMEOUT=60
GENERATION_TIMEOUT=300

# Options navigateur
BROWSER_HEADLESS=false
"""
        
        with open('.env.example', 'w', encoding='utf-8') as f:
            f.write(env_example_content)
        
        print(f"✅ Fichier .env.example créé (template pour Git)")
        
        print("\n" + "="*70)
        print("🎉 CONFIGURATION TERMINÉE")
        print("="*70)
        print("\n✅ Prochaines étapes :")
        print("   1. Redémarrez le serveur MCP : python server.py")
        print("   2. Configurez l'extension Chrome avec le WEBSOCKET_TOKEN")
        print("   3. Configurez ChatGPT avec le MCP_API_KEY")
        print("\n" + "="*70 + "\n")
        
    else:
        print("\n✅ Copiez manuellement les clés dans votre .env")
        print("   N'oubliez pas les deux clés : MCP_API_KEY et WEBSOCKET_TOKEN\n")

