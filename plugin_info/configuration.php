<?php
require_once dirname(__FILE__) . '/../../../core/php/core.inc.php';
include_file('core', 'authentification', 'php');
if (!isConnect()) {
    include_file('desktop', '404', 'php');
    die();
}
?>
<form class="form-horizontal">
    <fieldset>
        <div class="form-group">
            <label class="col-md-4 control-label">{{Port socket interne du démon}}</label>
            <div class="col-md-3">
                <input class="configKey form-control" data-l1key="socketport" placeholder="55120"/>
            </div>
        </div>
        <div class="form-group">
            <label class="col-md-4 control-label">{{Intervalle de lecture de l'état d'appel (s)}}
                <sup><i class="fas fa-question-circle tooltips" title="{{Interrogation de /ISAPI/VideoIntercom/callStatus. 1 s conseillé pour détecter la sonnerie rapidement.}}"></i></sup>
            </label>
            <div class="col-md-3">
                <input class="configKey form-control" data-l1key="poll_interval" placeholder="1"/>
            </div>
        </div>
        <div class="form-group">
            <label class="col-md-4 control-label">{{Port HTTPS de la page Parler}}
                <sup><i class="fas fa-question-circle tooltips" title="{{Page servie par le démon pour parler avec le micro de la tablette. 0 pour désactiver.}}"></i></sup>
            </label>
            <div class="col-md-3">
                <input class="configKey form-control" data-l1key="talkport" placeholder="55121"/>
            </div>
        </div>
    </fieldset>
</form>

<legend><i class="fas fa-cubes"></i> {{Librairies}}
    <a class="btn btn-xs btn-default pull-right" id="bt_hikLibsRefresh"><i class="fas fa-sync"></i> {{Vérifier les mises à jour}}</a>
</legend>
<div id="div_hikLibs"><i class="fas fa-spinner fa-spin"></i> {{Chargement…}}</div>
<div class="alert alert-info" style="margin-top:8px">
    {{Les librairies Python sont mises à jour en relançant l'installation des dépendances. Le SDK Hikvision reste sur la version testée avec le plugin ; « Utiliser la dernière » le fait passer à la version la plus récente de l'add-on Home Assistant (dépendances à relancer ensuite). Une vérification automatique a lieu chaque jour et crée un message Jeedom si une mise à jour est disponible.}}
</div>

<script>
(function () {
    var labels = {
        ok: '<span class="label label-success">{{À jour}}</span>',
        update: '<span class="label label-warning">{{Mise à jour disponible}}</span>',
        required: '<span class="label label-danger">{{Mise à jour nécessaire}}</span>',
        missing: '<span class="label label-danger">{{Absent}}</span>'
    };
    function esc(s) { return $('<div>').text(s == null ? '—' : s).html(); }
    function load(force) {
        $('#div_hikLibs').html('<i class="fas fa-spinner fa-spin"></i> {{Vérification…}}');
        $.ajax({
            type: 'POST', url: 'plugins/hikinterphone/core/ajax/hikinterphone.ajax.php', dataType: 'json',
            data: { action: 'libsInfo', force: force ? 1 : 0 },
            error: function (r, s, e) { $('#div_hikLibs').html('<div class="alert alert-danger">' + esc(e) + '</div>'); },
            success: function (data) {
                if (data.state != 'ok') { $('#div_hikLibs').html('<div class="alert alert-danger">' + data.result + '</div>'); return; }
                var r = data.result;
                var h = '<table class="table table-condensed table-bordered"><thead><tr><th>{{Librairie}}</th><th>{{Source}}</th><th>{{Installée}}</th><th>{{Requise}}</th><th>{{Dernière}}</th><th>{{Statut}}</th></tr></thead><tbody>';
                r.rows.forEach(function (l) {
                    var action = '';
                    if (l.latest_sha && l.status == 'update') {
                        action = ' <a class="btn btn-xs btn-warning bt_hikSdk" data-sha="' + l.latest_sha + '">{{Utiliser la dernière}}</a>';
                    }
                    if (l.latest_sha !== undefined && l.required && l.status == 'required') {
                        action = ' <a class="btn btn-xs btn-default bt_hikSdk" data-sha="default">{{Revenir à la version testée}}</a>';
                    }
                    h += '<tr><td><b>' + esc(l.name) + '</b></td><td>' + esc(l.type) + '</td><td>' + esc(l.installed) + '</td><td>' + esc(l.required) + '</td><td>' + esc(l.latest) + '</td><td>' + (labels[l.status] || esc(l.status)) + action + '</td></tr>';
                });
                h += '</tbody></table>';
                h += '<small>{{Dépendances installées le}} ' + esc(r.installed_at) + ' — {{dernière vérification}} ' + esc(r.checked) + '</small>';
                if (!r.deps_ok) {
                    h += '<div class="alert alert-warning" style="margin-top:6px">{{Relancez l\'installation des dépendances pour appliquer les mises à jour nécessaires.}}</div>';
                }
                $('#div_hikLibs').html(h);
            }
        });
    }
    $('#bt_hikLibsRefresh').off('click').on('click', function () { load(true); });
    $('#div_hikLibs').off('click', '.bt_hikSdk').on('click', '.bt_hikSdk', function () {
        var sha = $(this).attr('data-sha');
        $.ajax({
            type: 'POST', url: 'plugins/hikinterphone/core/ajax/hikinterphone.ajax.php', dataType: 'json',
            data: { action: 'setSdkCommit', sha: sha },
            success: function (data) {
                if (data.state != 'ok') { $('#div_alert').showAlert({ message: data.result, level: 'danger' }); return; }
                $('#div_alert').showAlert({ message: '{{Version du SDK enregistrée : relancez l\'installation des dépendances.}}', level: 'warning' });
                load(false);
            }
        });
    });
    load(false);
})();
</script>
