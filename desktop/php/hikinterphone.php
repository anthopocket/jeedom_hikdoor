<?php
if (!isConnect('admin')) {
    throw new Exception('{{401 - Accès non autorisé}}');
}
$plugin = plugin::byId('hikinterphone');
sendVarToJS('eqType', $plugin->getId());
$eqLogics = eqLogic::byType($plugin->getId());
sendVarToJS('hikTalkBase', 'https://' . hikinterphone::getJeedomIp() . ':' . intval(config::byKey('talkport', 'hikinterphone', 55121)));
?>

<div class="row row-overflow">
    <div class="col-xs-12 eqLogicThumbnailDisplay">
        <legend><i class="fas fa-cog"></i> {{Gestion}}</legend>
        <div class="eqLogicThumbnailContainer">
            <div class="cursor eqLogicAction logoPrimary" data-action="add">
                <i class="fas fa-plus-circle"></i><br><span>{{Ajouter}}</span>
            </div>
            <div class="cursor eqLogicAction logoSecondary" data-action="gotoPluginConf">
                <i class="fas fa-wrench"></i><br><span>{{Configuration}}</span>
            </div>
        </div>
        <legend><i class="fas fa-door-open"></i> {{Mes interphones}}</legend>
        <?php if (count($eqLogics) == 0) { ?>
            <div class="text-center" style="font-size:1.2em;font-weight:bold;">{{Aucun interphone, cliquez sur Ajouter}}</div>
        <?php } else { ?>
            <div class="input-group" style="margin:5px;">
                <input class="form-control roundedLeft" placeholder="{{Rechercher}}" id="in_searchEqlogic">
                <div class="input-group-btn">
                    <a id="bt_resetSearch" class="btn roundedRight" style="width:30px"><i class="fas fa-times"></i></a>
                </div>
            </div>
            <div class="eqLogicThumbnailContainer">
                <?php foreach ($eqLogics as $eqLogic) {
                    $opacity = ($eqLogic->getIsEnable()) ? '' : 'disableCard';
                    echo '<div class="eqLogicDisplayCard cursor ' . $opacity . '" data-eqLogic_id="' . $eqLogic->getId() . '">';
                    echo '<img src="' . $plugin->getPathImgIcon() . '">';
                    echo '<br><span class="name">' . $eqLogic->getHumanName(true, true) . '</span>';
                    echo '</div>';
                } ?>
            </div>
        <?php } ?>
    </div>

    <div class="col-xs-12 eqLogic" style="display:none;">
        <div class="input-group pull-right" style="display:inline-flex;">
            <span class="input-group-btn">
                <a class="btn btn-sm btn-warning roundedLeft" id="bt_recreateCmds"><i class="fas fa-sync"></i> {{Recréer les commandes}}</a>
                <a class="btn btn-sm btn-default eqLogicAction" data-action="configure"><i class="fas fa-cogs"></i> {{Configuration avancée}}</a>
                <a class="btn btn-sm btn-success eqLogicAction" data-action="save"><i class="fas fa-check-circle"></i> {{Sauvegarder}}</a>
                <a class="btn btn-sm btn-danger eqLogicAction roundedRight" data-action="remove"><i class="fas fa-minus-circle"></i> {{Supprimer}}</a>
            </span>
        </div>
        <ul class="nav nav-tabs" role="tablist">
            <li role="presentation"><a href="#" class="eqLogicAction" aria-controls="home" role="tab" data-toggle="tab" data-action="returnToThumbnailDisplay"><i class="fas fa-arrow-circle-left"></i></a></li>
            <li role="presentation" class="active"><a href="#eqlogictab" aria-controls="home" role="tab" data-toggle="tab"><i class="fas fa-tachometer-alt"></i> {{Equipement}}</a></li>
            <li role="presentation"><a href="#commandtab" aria-controls="profile" role="tab" data-toggle="tab"><i class="fas fa-list"></i> {{Commandes}}</a></li>
        </ul>
        <div class="tab-content">
            <div role="tabpanel" class="tab-pane active" id="eqlogictab">
                <form class="form-horizontal">
                    <fieldset>
                        <div class="col-lg-6">
                            <legend><i class="fas fa-wrench"></i> {{Général}}</legend>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Nom}}</label>
                                <div class="col-sm-6">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="id" style="display:none;">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="name" placeholder="{{Nom de l'interphone}}">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Objet parent}}</label>
                                <div class="col-sm-6">
                                    <select class="eqLogicAttr form-control" data-l1key="object_id">
                                        <option value="">{{Aucun}}</option>
                                        <?php
                                        $options = '';
                                        foreach ((jeeObject::buildTree(null, false)) as $object) {
                                            $options .= '<option value="' . $object->getId() . '">' . str_repeat('&nbsp;&nbsp;', $object->getConfiguration('parentNumber')) . $object->getName() . '</option>';
                                        }
                                        echo $options;
                                        ?>
                                    </select>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Catégorie}}</label>
                                <div class="col-sm-6">
                                    <?php
                                    foreach (jeedom::getConfiguration('eqLogic:category') as $key => $value) {
                                        echo '<label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="category" data-l2key="' . $key . '">' . $value['name'] . '</label>';
                                    }
                                    ?>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Options}}</label>
                                <div class="col-sm-6">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="isEnable" checked>{{Activer}}</label>
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="isVisible" checked>{{Visible}}</label>
                                </div>
                            </div>

                            <legend><i class="fas fa-network-wired"></i> {{Connexion}}</legend>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Protocole}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{SDK (port 8000) : recommandé, fonctionne même quand le portier répond « Invalid Operation » en ISAPI HTTP (firmwares récents). ISAPI HTTP (port 80) : anciens firmwares.}}"></i></sup>
                                </label>
                                <div class="col-sm-6">
                                    <select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="protocol" id="sel_protocol">
                                        <option value="sdk">{{SDK Hikvision (port 8000) — recommandé}}</option>
                                        <option value="isapi">{{ISAPI HTTP (port 80)}}</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Adresse IP}}</label>
                                <div class="col-sm-6">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ip" placeholder="192.168.1.50">
                                </div>
                            </div>
                            <div class="form-group hik-sdk">
                                <label class="col-sm-4 control-label">{{Port SDK (Server Port)}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="sdk_port" placeholder="8000">
                                </div>
                            </div>
                            <div class="form-group hik-isapi">
                                <label class="col-sm-4 control-label">{{Port HTTP}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="port" placeholder="80">
                                </div>
                                <div class="col-sm-3">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="https">HTTPS</label>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Utilisateur}}</label>
                                <div class="col-sm-6">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="username" placeholder="admin">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Mot de passe}}</label>
                                <div class="col-sm-6">
                                    <input type="password" autocomplete="new-password" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="password">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Sorties (gâches / relais)}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Nombre de sorties du portier à piloter (le DS-KV8113 en a 2 : ex. portillon + portail). Une commande « Ouvrir … » et un bouton dans la page Parler par sortie.}}"></i></sup>
                                </label>
                                <div class="col-sm-3">
                                    <select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="door_count" id="sel_doorCount">
                                        <option value="1">1</option>
                                        <option value="2">2</option>
                                        <option value="3">3</option>
                                        <option value="4">4</option>
                                    </select>
                                </div>
                            </div>
                            <?php for ($n = 1; $n <= 4; $n++) { ?>
                            <div class="form-group hik-door" data-door="<?php echo $n; ?>">
                                <label class="col-sm-4 control-label">{{Nom sortie}} <?php echo $n; ?></label>
                                <div class="col-sm-6">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="door<?php echo $n; ?>_name" placeholder="<?php echo ($n == 1) ? '{{Portillon}}' : (($n == 2) ? '{{Portail}}' : 'Porte ' . $n); ?>">
                                </div>
                            </div>
                            <?php } ?>
                            <div class="form-group hik-isapi">
                                <label class="col-sm-4 control-label">{{Flux d'événements}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Écoute /ISAPI/Event/notification/alertStream (appels, ouvertures, alarmes) en plus de l'état d'appel.}}"></i></sup>
                                </label>
                                <div class="col-sm-6">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="alertstream" checked>{{Activer l'alertStream}}</label>
                                </div>
                            </div>
                        </div>
                        <div class="col-lg-6">
                            <legend><i class="fas fa-microphone"></i> {{Parler depuis une tablette}}</legend>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Lien de la page Parler}}</label>
                                <div class="col-sm-8">
                                    <div class="input-group">
                                        <input type="text" class="form-control roundedLeft" id="in_talkUrl" readonly placeholder="{{Sauvegardez l'équipement}}">
                                        <span class="input-group-btn">
                                            <a class="btn btn-default roundedRight" id="bt_openTalk" target="_blank"><i class="fas fa-external-link-alt"></i></a>
                                        </span>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Code pour un Design}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{À coller dans un élément Zone HTML du Design. Mode compact sans image (la vidéo est déjà dans Frigate/caméra) ; mettre video=1 pour l'afficher.}}"></i></sup>
                                </label>
                                <div class="col-sm-8">
                                    <textarea class="form-control" id="ta_talkIframe" rows="3" readonly style="font-family:monospace;font-size:11px;" onclick="this.select()"></textarea>
                                </div>
                            </div>
                            <div class="form-group hik-sdk">
                                <label class="col-sm-4 control-label">{{Décrocher automatiquement}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Si ça sonne quand vous activez l'audio, le plugin décroche d'abord : sinon le portier garde son haut-parleur pour la sonnerie.}}"></i></sup>
                                </label>
                                <div class="col-sm-6">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="auto_answer" checked>{{Décrocher avant de parler}}</label>
                                </div>
                            </div>
                            <div class="form-group hik-sdk">
                                <label class="col-sm-4 control-label">{{Durée max de sonnerie (s)}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Sécurité : « Sonnerie » repasse à 0 au plus tard après ce délai, si l'alarme de fin d'appel n'arrive pas. Normalement la fin d'appel est poussée par le portier.}}"></i></sup>
                                </label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ring_time" placeholder="90">
                                </div>
                            </div>
                            <div class="form-group hik-sdk">
                                <label class="col-sm-4 control-label">{{Interrogation de l'état d'appel (s)}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{0 (conseillé) : aucun échange périodique, tout est poussé par le portier (sonnerie, fin d'appel, perte de liaison). Mettre 5 à 10 s seulement pour voir dans Jeedom un décroché fait depuis un moniteur intérieur ou l'appli Hik-Connect.}}"></i></sup>
                                </label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="status_poll" placeholder="0">
                                </div>
                            </div>
                            <div class="form-group hik-sdk">
                                <label class="col-sm-4 control-label">{{Canal interphonie}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="voice_channel" placeholder="{{auto}}">
                                </div>
                            </div>
                            <div class="form-group hik-isapi">
                                <label class="col-sm-4 control-label">{{Écouter le portier}}</label>
                                <div class="col-sm-6">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="audio_listen" checked>{{Recevoir le son du portier}}</label>
                                </div>
                            </div>
                            <div class="form-group hik-isapi">
                                <label class="col-sm-4 control-label">{{Mode d'envoi audio}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Selon le firmware. Si le portier n'émet aucun son, essayez l'autre mode.}}"></i></sup>
                                </label>
                                <div class="col-sm-6">
                                    <select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="audio_cl">
                                        <option value="0">{{Content-Length: 0 (défaut, méthode go2rtc)}}</option>
                                        <option value="1">{{Content-Length élevé}}</option>
                                    </select>
                                </div>
                            </div>
                            <legend><i class="fas fa-video"></i> {{Vidéo}}</legend>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Vidéo live}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Flux RTSP du portier converti par ffmpeg en vidéo fluide pour la page Parler. ffmpeg ne tourne que lorsqu'une page affiche la vidéo.}}"></i></sup>
                                </label>
                                <div class="col-sm-6">
                                    <label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="video_live" checked>{{Activer (sinon images fixes)}}</label>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Flux RTSP}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="rtsp_port" placeholder="554">
                                </div>
                                <div class="col-sm-5">
                                    <select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="rtsp_path">
                                        <option value="/Streaming/Channels/102">{{Sous-flux 102 (léger, conseillé)}}</option>
                                        <option value="/Streaming/Channels/101">{{Flux principal 101 (HD)}}</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{URL RTSP (optionnel)}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Remplace le flux du portier. Ex. le restream go2rtc de Frigate : rtsp://IP_FRIGATE:8554/NOM_CAMERA — évite une connexion de plus sur le portier.}}"></i></sup>
                                </label>
                                <div class="col-sm-8">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="rtsp_url" placeholder="rtsp://192.168.1.x:8554/portier">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Images/s · largeur}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="video_fps" placeholder="12">
                                </div>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="video_width" placeholder="{{origine}}">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{URL d'image (optionnel)}}
                                    <sup><i class="fas fa-question-circle tooltips" title="{{Laisser vide pour capturer sur le portier. Sinon une URL JPEG prise à la place, ex. Frigate : http://IP:5000/api/NOM_CAMERA/latest.jpg}}"></i></sup>
                                </label>
                                <div class="col-sm-8">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="snapshot_url" placeholder="http://192.168.1.x:5000/api/portier/latest.jpg">
                                </div>
                            </div>
                            <div class="form-group hik-isapi">
                                <label class="col-sm-4 control-label">{{Canal image}}</label>
                                <div class="col-sm-3">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="snapshot_channel" placeholder="101">
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="col-sm-4 control-label">{{Jeton d'accès}}</label>
                                <div class="col-sm-6">
                                    <input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="talk_token" readonly>
                                </div>
                            </div>
                            <div class="alert alert-info">
                                {{Ouvrez le lien dans Chrome sur la tablette (pas dans l'appli Jeedom) : le navigateur n'autorise le micro qu'en HTTPS. Le certificat est auto-signé : acceptez l'avertissement une fois (Paramètres avancés → Continuer), puis « Ajouter à l'écran d'accueil ».}}<br>
                                {{Le lien contient un jeton secret : ne le partagez pas. Pour le changer, videz le champ Jeton (configuration avancée) et sauvegardez.}}<br>
                                {{La commande « Tester capacités » (masquée) écrit dans le log les capacités ISAPI de votre firmware, dont le codec du two-way audio.}}
                            </div>
                        </div>
                    </fieldset>
                </form>
            </div>

            <div role="tabpanel" class="tab-pane" id="commandtab">
                <br>
                <div class="table-responsive">
                    <table id="table_cmd" class="table table-bordered table-condensed">
                        <thead>
                            <tr>
                                <th class="hidden-xs" style="min-width:50px;width:70px;">ID</th>
                                <th style="min-width:200px;width:350px;">{{Nom}}</th>
                                <th>{{Type}}</th>
                                <th>{{Valeur}}</th>
                                <th style="min-width:260px;width:310px;">{{Options}}</th>
                                <th style="min-width:80px;width:200px;">{{Actions}}</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

<?php include_file('desktop', 'hikinterphone', 'js', 'hikinterphone'); ?>
<?php include_file('core', 'plugin.template', 'js'); ?>
