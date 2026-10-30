# Hikdoor — portiers vidéo Hikvision pour Jeedom

Pilotage local des portiers vidéo Hikvision (gamme DS-KV / DS-KD), sans cloud Hik-Connect.

## Deux protocoles
- **SDK Hikvision, port 8000 (par défaut, recommandé).** C'est le « Server Port » de l'interface du portier. Il fonctionne même quand le portier répond `Invalid Operation` à toute requête ISAPI HTTP, ce qui arrive sur les firmwares récents (KV6113 3.x…). C'est la méthode de l'add-on Home Assistant pergolafabio/Hikvision-Addons. Il apporte une connexion permanente, les alarmes poussées (sonnerie instantanée), l'état d'appel, Décrocher, Raccrocher, Refuser, l'ouverture de porte, l'image et l'interphonie G.711 (`NET_DVR_StartVoiceCom_MR_V30`).
- **ISAPI HTTP, port 80.** Pour les anciens firmwares : callStatus, alertStream et two-way audio ISAPI.

Le SDK (bibliothèques Linux x86_64 ou aarch64) est téléchargé pendant l'installation des dépendances, depuis le dépôt de l'add-on HA (commit figé). Il n'est pas inclus dans le zip du plugin.

## Installation
1. Copier le dossier `hikinterphone` dans `/var/www/html/plugins/` (ou zip via l'installation de plugin depuis un fichier).
2. `chown -R www-data:www-data /var/www/html/plugins/hikinterphone`, puis `chmod +x resources/install_apt.sh`.
3. Activer le plugin, installer les dépendances (venv propre au plugin, seulement `requests`), démarrer le démon.
4. Ajouter un équipement : protocole SDK, IP, port SDK 8000, utilisateur et mot de passe du portier, n° de porte.
5. Lancer la commande « Tester capacités » (masquée, dans l'onglet Commandes) : le log `hikinterphoned` affiche le numéro de série, le codec d'interphonie et l'état d'appel lu par le SDK.

## Commandes
| Commande | Type | ISAPI |
|---|---|---|
| Etat appel | info texte | `GET /ISAPI/VideoIntercom/callStatus?format=json` (idle / ring / onCall…) |
| Sonnerie | info binaire | 1 quand l'état vaut `ring` |
| En communication | info binaire | 1 quand l'état vaut `onCall` |
| En ligne | info binaire | 0 après 5 échecs consécutifs |
| Dernier événement | info texte | alertStream (`AccessControllerEvent major=… minor=…`) |
| Décrocher | action | `PUT /ISAPI/VideoIntercom/callSignal?format=json` `{"CallSignal":{"cmdType":"answer"}}` |
| Raccrocher | action | idem `hangUp` |
| Refuser | action | idem `reject` |
| Ouvrir porte | action | `PUT /ISAPI/AccessControl/RemoteControl/door/<n>` |
| Rafraîchir | action | relit l'état d'appel |
| Tester capacités (log) | action masquée | écrit deviceInfo + capacités dans le log `hikinterphone` |

## Parler avec le micro de la tablette
Le démon sert une page **Parler** en HTTPS : `https://<ip-jeedom>:55121/talk?eq=<id>&token=<jeton>`. Le lien est affiché sur la page de l'équipement et dans la commande info « Lien Parler ».

- **Chrome sur la tablette**, pas l'appli Jeedom : un navigateur n'autorise le micro qu'en HTTPS. Au premier accès, accepter l'avertissement du certificat auto-signé (Paramètres avancés → Continuer), puis « Ajouter à l'écran d'accueil ».
- **Activer l'audio** ouvre une session `/ISAPI/System/TwoWayAudio/channels/1/open`. Le micro est envoyé en G.711 8 kHz (µ-law ou A-law, selon le codec annoncé par le portier) et le son du portier est lu en retour.
- **Appuyer pour parler** (par défaut) : le son du portier est coupé pendant que tu parles, donc pas d'écho. **Mains libres** : dialogue simultané, avec l'annulation d'écho du navigateur.
- La page affiche aussi l'image du portier (environ 1 image/s), l'état d'appel (vibration à la sonnerie) et les boutons Décrocher, Raccrocher et Ouvrir.
- Une seule tablette à la fois : la dernière qui active l'audio reprend la main.
- Le certificat est généré au démarrage du démon dans `data/` pour l'IP interne de Jeedom, et régénéré si cette IP change.
- Accès local uniquement : le port 55121 n'a pas à être ouvert vers l'extérieur.

### Dans un Design Jeedom
La page s'intègre en iframe. Le code prêt à coller est affiché sur la page de l'équipement, dans « Code pour un Design ». Colle-le dans un élément **Zone HTML** du Design, d'environ 300 × 260 px :
```html
<iframe src="https://<ip>:55121/talk?eq=<id>&token=<jeton>&embed=1&bg=transparent"
        allow="microphone; autoplay; screen-wake-lock" style="width:100%;height:100%;border:0;"></iframe>
```
Options d'URL : `embed=1` (compact : état, Activer l'audio, Parler, Décrocher/Raccrocher/Ouvrir), `video=1` (ajoute l'image du portier), `bg=transparent`, `mode=ptt` ou `mode=free`.

**Conditions pour que le micro marche dans le Design** (règle des navigateurs, pas du plugin) :
1. **Accepter une fois le certificat** en ouvrant le lien direct dans le navigateur de la tablette. Sinon l'iframe reste blanche, car un navigateur n'affiche pas l'avertissement de certificat dans une iframe.
2. **Le Design doit être dans un contexte sécurisé**. Trois possibilités :
   - ouvrir Jeedom en **https** sur la tablette ;
   - **Chrome Android** : `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, ajouter `http://<ip-jeedom>`, activer et relancer Chrome ;
   - **Fully Kiosk Browser** (tablette murale) : activer l'accès au micro et ignorer les erreurs SSL dans les paramètres Web Content, et déclarer Jeedom en origine sécurisée si l'option existe sur ta version.
3. L'**appli mobile Jeedom** ne transmet en général pas le micro à ses pages : utilise Chrome ou Fully Kiosk.

Si une de ces conditions manque, la page l'indique en rouge au clic sur « Activer l'audio ».

Si le portier n'émet aucun son : essaie le mode d'envoi « Content-Length élevé », puis vérifie dans le log (« Tester capacités ») que `TwoWayAudio/channels` répond et annonce `G.711ulaw` ou `G.711alaw`.

## Fonctionnement
- Le démon (`hikinterphoned`) interroge l'état d'appel toutes les N secondes (1 s par défaut) et garde ouvert l'alertStream. Il remonte les changements vers `core/php/jeeHikinterphone.php`.
- Les actions passent par le démon (socket locale avec réponse), donc le démon doit tourner. Une erreur du portier remonte dans le message d'erreur Jeedom.
- En SDK, quand tu actives l'audio pendant que ça sonne, le plugin **décroche d'abord** (option « Décrocher avant de parler »). Sinon le portier garde son haut-parleur pour la sonnerie.
- Si le portier refuse Décrocher ou Raccrocher (`Invalid Operation` / erreur 29) : enregistre-le une fois dans l'appli Hik-Connect. C'est un comportement connu des firmwares récents, et la commande continue ensuite de marcher même sans Internet.
- Les événements `videoloss` (battement de cœur Hik) sont ignorés.

## À vérifier sur ton firmware
- Lancer « Tester capacités » et regarder le log : si `callSignal` ou `callStatus` répondent 404, ton firmware ne les expose pas (certains anciens DS-KV8x13 ne les ont que derrière un moniteur intérieur).
- Pour la gâche, si `door/1` refuse le XML, certains firmwares récents veulent `PUT /ISAPI/AccessControl/RemoteControl/door/1?format=json` avec `{"RemoteControlDoor":{"cmd":"open"}}`.
- Décrocher et Raccrocher ne pilotent que l'état de l'appel. Le son passe par la page Parler (two-way audio), ce qui est indépendant de l'appel.
- Le log en mode debug affiche les événements bruts de l'alertStream : sonne une fois pour voir quels `major`/`minor` ton portier envoie lors d'un appel.

## Dépendances
Venv Python simple (`resources/venv`), compatible Debian 11 (Python 3.9). Paquets : `requests` et `aiohttp`, plus `openssl` pour le certificat. Le codec G.711 est en pur Python (pas d'`audioop`, retiré de Python 3.13). Pour s'aligner sur les autres plugins, `install_apt.sh` peut être remplacé par la méthode `dependance.lib` / `pyenv.lib` (NebzHB) du plugin Roborock.
