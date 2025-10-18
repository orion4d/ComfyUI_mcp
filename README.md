# Orion4D_maskpro

Outil d’édition de masque intégré à ComfyUI.

## Ce que fait le node
- Expose un **éditeur web** accessible via `/orion4d_maskpro/editor` (redirigé vers `web/editor.html`).
- Stocke les fichiers par instance de node dans : `ComfyUI/user/orion4d_cache/maskpro_<NODE_ID>/`.
  - `image.png` : image de référence (optionnelle).
  - `mask.png` : masque édité (8-bit L).
- Fournit des **endpoints** pour ouvrir, sauvegarder, nettoyer et lister les brosses.

## Entrées / sorties
- **Entrées** :
  - `image` (IMAGE, optionnel)
  - `mask` (MASK, optionnel)
  - `invert_mask` (BOOLEAN)
- **Sorties** :
  - `mask` (MASK, 0..1, blanc = garder)
  - `image` (IMAGE, passthrough ou image vide)
  - `image_rgba` (IMAGE, alpha = masque)

## Logique du node
1. S’il y a un `mask.png` édité sur disque (via l’éditeur), il est prioritaire.
2. Sinon, si un `mask` est fourni en entrée :
   - on le convertit en "paint convention" (blanc = masqué) et on le **met en cache** sous forme de `mask.png` pour l’édition.
3. Sinon, on part d’un **masque vide** (0).
4. Si la taille diffère de l’image, on **centre** et on **crop/pad** le masque.
5. Le masque de sortie respecte la convention standard ComfyUI : **blanc = garder** (donc `final = 1 - paint`).

## Endpoints HTTP
- `GET /orion4d_maskpro/editor` : redirige vers l’éditeur.
- `GET /orion4d_maskpro/open?node_id=<id>` : info dispo + taille image.
- `POST /orion4d_maskpro/save` (multipart `image`, `mask`) : enregistre dans le cache.
- `GET /orion4d_maskpro/clear?node_id=<id>` : supprime le `mask.png`.
- `GET /orion4d_maskpro/list_brushes` : liste les png dans `web/brushes/`.
- `POST /orion4d_maskpro/rembg?node_id=<id>` : génère un masque via `rembg` si installé.

## Dossiers
```
custom_nodes/Orion4D_maskpro/
├─ __init__.py
├─ maskpro.py
└─ web/
   ├─ editor.html (à fournir)
   └─ brushes/
```

## Notes
- `register_routes()` est appelé à l’import pour monter les routes.
- Le script gère les conversions PIL ↔ Tensor et la convention de masque.
- Si `rembg` n'est pas présent, l'endpoint renvoie une erreur claire.

