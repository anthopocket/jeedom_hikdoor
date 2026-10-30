<?php
/* Callback du démon hikinterphoned */
try {
    require_once __DIR__ . '/../../../../core/php/core.inc.php';

    if (!jeedom::apiAccess(init('apikey'), 'hikinterphone')) {
        echo __('Vous n\'êtes pas autorisé à effectuer cette action', __FILE__);
        die();
    }
    $result = json_decode(file_get_contents('php://input'), true);
    if (!is_array($result)) {
        die();
    }
    $eqLogic = eqLogic::byId(isset($result['id']) ? $result['id'] : 0);
    if (!is_object($eqLogic) || $eqLogic->getEqType_name() != 'hikinterphone') {
        die();
    }
    if (isset($result['callStatus'])) {
        $eqLogic->updateCallStatus($result['callStatus']);
    }
    if (isset($result['online'])) {
        $eqLogic->checkAndUpdateCmd('en_ligne', $result['online'] ? 1 : 0);
    }
    if (isset($result['event'])) {
        $eqLogic->checkAndUpdateCmd('dernier_evenement', $result['event']);
        log::add('hikinterphone', 'info', $eqLogic->getHumanName() . ' événement : ' . $result['event']);
    }
} catch (Exception $e) {
    log::add('hikinterphone', 'error', displayException($e));
}
