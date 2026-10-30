<?php
require_once dirname(__FILE__) . '/../../../core/php/core.inc.php';

function hikinterphone_install() {
    if (config::byKey('socketport', 'hikinterphone') == '') {
        config::save('socketport', 55120, 'hikinterphone');
    }
    if (config::byKey('poll_interval', 'hikinterphone') == '') {
        config::save('poll_interval', 1, 'hikinterphone');
    }
    if (config::byKey('talkport', 'hikinterphone') == '') {
        config::save('talkport', 55121, 'hikinterphone');
    }
}

function hikinterphone_update() {
    hikinterphone_install();
    foreach (eqLogic::byType('hikinterphone') as $eqLogic) {
        $eqLogic->save(); // crée le jeton, les nouvelles commandes et le lien Parler
    }
}

function hikinterphone_remove() {
}
