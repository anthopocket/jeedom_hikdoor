/* Plugin Hikdoor */

$('#sel_protocol').off('change').on('change', function () {
    var isapi = $(this).value() == 'isapi';
    $('.hik-isapi').toggle(isapi);
    $('.hik-sdk').toggle(!isapi);
});

$('#sel_doorCount').off('change').on('change', function () {
    var count = parseInt($(this).value() || 1);
    $('.hik-door').each(function () {
        $(this).toggle(parseInt($(this).attr('data-door')) <= count);
    });
});

$('#bt_recreateCmds').off('click').on('click', function () {
    var id = $('.eqLogicAttr[data-l1key=id]').value();
    if (!id) {
        return;
    }
    $.ajax({
        type: 'POST',
        url: 'plugins/hikinterphone/core/ajax/hikinterphone.ajax.php',
        data: { action: 'recreateCmds', id: id },
        dataType: 'json',
        error: function (request, status, error) {
            $('#div_alert').showAlert({ message: error, level: 'danger' });
        },
        success: function (data) {
            if (data.state != 'ok') {
                $('#div_alert').showAlert({ message: data.result, level: 'danger' });
                return;
            }
            var created = data.result.created || [];
            $('#div_alert').showAlert({
                message: '{{Sorties}} : ' + data.result.doors + ' — ' + (created.length ? '{{créées}} : ' + created.join(', ') : '{{aucune nouvelle commande (déjà présentes)}}'),
                level: 'success'
            });
            $('.eqLogicDisplayCard[data-eqLogic_id=' + id + ']').click();
        }
    });
});

function printEqLogic(_eqLogic) {
    if (!_eqLogic.configuration || !_eqLogic.configuration.door_count) {
        $('#sel_doorCount').value('1');
    }
    $('#sel_doorCount').trigger('change');
    if (!_eqLogic.configuration || !_eqLogic.configuration.protocol) {
        $('#sel_protocol').value('sdk');
    }
    $('#sel_protocol').trigger('change');
    var token = (_eqLogic.configuration && _eqLogic.configuration.talk_token) ? _eqLogic.configuration.talk_token : '';
    var url = (token && _eqLogic.id) ? hikTalkBase + '/talk?eq=' + _eqLogic.id + '&token=' + token : '';
    $('#in_talkUrl').val(url);
    $('#bt_openTalk').attr('href', url || '#');
    $('#ta_talkIframe').val(url ? '<iframe src="' + url + '&embed=1&bg=transparent" allow="microphone; autoplay; screen-wake-lock" style="width:100%;height:100%;border:0;"></iframe>' : '');
}

function addCmdToTable(_cmd) {
    if (!isset(_cmd)) {
        var _cmd = { configuration: {} };
    }
    if (!isset(_cmd.configuration)) {
        _cmd.configuration = {};
    }
    var tr = '<tr class="cmd" data-cmd_id="' + init(_cmd.id) + '">';
    tr += '<td class="hidden-xs"><span class="cmdAttr" data-l1key="id"></span></td>';
    tr += '<td>';
    tr += '<input class="cmdAttr form-control input-sm" data-l1key="name" placeholder="{{Nom de la commande}}">';
    tr += '</td>';
    tr += '<td>';
    tr += '<span class="type" type="' + init(_cmd.type) + '">' + jeedom.cmd.availableType() + '</span>';
    tr += '<span class="subType" subType="' + init(_cmd.subType) + '"></span>';
    tr += '</td>';
    tr += '<td><span class="cmdAttr" data-l1key="htmlstate"></span></td>';
    tr += '<td>';
    tr += '<label class="checkbox-inline"><input type="checkbox" class="cmdAttr" data-l1key="isVisible" checked/>{{Afficher}}</label> ';
    tr += '<label class="checkbox-inline"><input type="checkbox" class="cmdAttr" data-l1key="isHistorized" checked/>{{Historiser}}</label> ';
    tr += '<label class="checkbox-inline"><input type="checkbox" class="cmdAttr" data-l1key="display" data-l2key="invertBinary"/>{{Inverser}}</label> ';
    tr += '</td>';
    tr += '<td>';
    if (is_numeric(_cmd.id)) {
        tr += '<a class="btn btn-default btn-xs cmdAction" data-action="configure"><i class="fas fa-cogs"></i></a> ';
        tr += '<a class="btn btn-default btn-xs cmdAction" data-action="test"><i class="fas fa-rss"></i> {{Tester}}</a>';
    }
    tr += '</td>';
    tr += '</tr>';
    $('#table_cmd tbody').append(tr);
    var tr = $('#table_cmd tbody tr').last();
    jeedom.eqLogic.buildSelectCmd({
        id: $('.eqLogicAttr[data-l1key=id]').value(),
        filter: { type: 'info' },
        error: function (error) {
            $('#div_alert').showAlert({ message: error.message, level: 'danger' });
        },
        success: function (result) {
            tr.setValues(_cmd, '.cmdAttr');
            jeedom.cmd.changeType(tr, init(_cmd.subType));
        }
    });
}
