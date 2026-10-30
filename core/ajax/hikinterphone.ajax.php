<?php
try {
    require_once __DIR__ . '/../../../../core/php/core.inc.php';
    include_file('core', 'authentification', 'php');
    if (!isConnect('admin')) {
        throw new Exception(__('401 - Accès non autorisé', __FILE__));
    }
    ajax::init();

    if (init('action') == 'recreateCmds') {
        $eqLogic = hikinterphone::byId(init('id'));
        if (!is_object($eqLogic)) {
            throw new Exception(__('Equipement introuvable : ', __FILE__) . init('id'));
        }
        $created = $eqLogic->createCommands();
        $eqLogic->checkAndUpdateCmd('lien_parler', $eqLogic->getTalkUrl());
        hikinterphone::syncDaemon();
        ajax::success(array('doors' => $eqLogic->getDoorCount(), 'created' => $created));
    }

    if (init('action') == 'libsInfo') {
        ajax::success(hikinterphone::libsInfo(init('force') == 1));
    }

    if (init('action') == 'setSdkCommit') {
        $sha = init('sha');
        if ($sha == 'default') {
            config::remove('sdk_commit', 'hikinterphone');
        } elseif (preg_match('/^[0-9a-f]{40}$/', $sha)) {
            config::save('sdk_commit', $sha, 'hikinterphone');
        } else {
            throw new Exception(__('Version de SDK invalide', __FILE__));
        }
        ajax::success(array('wanted' => hikinterphone::wantedSdkCommit()));
    }

    throw new Exception(__('Aucune méthode correspondante à : ', __FILE__) . init('action'));
} catch (Exception $e) {
    ajax::error(displayException($e), $e->getCode());
}
