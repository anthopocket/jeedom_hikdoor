<?php
/* Plugin Hikdoor (SDK port 8000 ou ISAPI HTTP) */
require_once __DIR__ . '/../../../../core/php/core.inc.php';

class hikinterphone extends eqLogic {

    /*     * ************************ Dépendances ************************* */

    public static function dependancy_info() {
        $return = array();
        $return['log'] = log::getPathToLog(__CLASS__ . '_update');
        $return['progress_file'] = jeedom::getTmpFolder(__CLASS__) . '/dependency';
        $python = self::getPython();
        if (file_exists($return['progress_file'])) {
            $return['state'] = 'in_progress';
        } elseif (is_executable($python) && file_exists(self::getSdkDir() . '/libhcnetsdk.so') && self::depsUpToDate()) {
            $return['state'] = 'ok';
        } else {
            $return['state'] = 'nok';
        }
        return $return;
    }

    /*     * ************************ Versions des librairies ************************* */

    public static function getResourcesDir() {
        return realpath(__DIR__ . '/../../resources');
    }

    public static function installedVersions() {
        $file = self::getResourcesDir() . '/versions.json';
        $data = file_exists($file) ? json_decode(file_get_contents($file), true) : null;
        return is_array($data) ? $data : array();
    }

    /* Dépendances à réinstaller si : versions.json absent, révision du plugin plus récente
       (nouvelle librairie ou version minimale relevée), librairie manquante ou trop ancienne. */
    public static function depsUpToDate() {
        $inst = self::installedVersions();
        $rev = intval(trim(@file_get_contents(self::getResourcesDir() . '/deps_rev')));
        if (!isset($inst['rev']) || intval($inst['rev']) < $rev) {
            return false;
        }
        foreach (self::requirements() as $name => $min) {
            $v = isset($inst['python'][$name]) ? $inst['python'][$name] : null;
            if ($v === null || ($min != '' && version_compare($v, $min, '<'))) {
                return false;
            }
        }
        $wanted = self::wantedSdkCommit();
        if (isset($inst['sdk_commit']) && $wanted != '' && $inst['sdk_commit'] != $wanted) {
            return false;
        }
        return true;
    }

    public static function requirements() {
        $req = array();
        foreach (@file(self::getResourcesDir() . '/requirements.txt') ?: array() as $line) {
            $line = trim(preg_replace('/#.*/', '', $line));
            if ($line == '') {
                continue;
            }
            if (preg_match('/^([A-Za-z0-9_.\-]+)\s*(>=|==)?\s*([0-9][0-9A-Za-z.\-]*)?/', $line, $m)) {
                $req[$m[1]] = isset($m[3]) ? $m[3] : '';
            }
        }
        return $req;
    }

    public static function defaultSdkCommit() {
        return trim(@file_get_contents(self::getResourcesDir() . '/sdk_commit'));
    }

    public static function wantedSdkCommit() {
        $c = trim(config::byKey('sdk_commit', __CLASS__, ''));
        return preg_match('/^[0-9a-f]{40}$/', $c) ? $c : self::defaultSdkCommit();
    }

    private static function httpJson($url) {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        curl_setopt($ch, CURLOPT_USERAGENT, 'jeedom-hikinterphone');
        curl_setopt($ch, CURLOPT_HTTPHEADER, array('Accept: application/json'));
        $res = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        return ($res !== false && $code == 200) ? json_decode($res, true) : null;
    }

    /* Tableau des librairies : installée / requise / dernière disponible / statut.
       Les versions « dernière » viennent de PyPI et GitHub, mises en cache 24 h. */
    public static function libsInfo($force = false) {
        $cache = cache::byKey('hikinterphone::latest');
        $latest = $force ? null : $cache->getValue(null);
        if (!is_array($latest)) {
            $latest = array('python' => array(), 'sdk' => null, 'checked' => date('Y-m-d H:i'));
            foreach (array_keys(self::requirements()) as $name) {
                $j = self::httpJson('https://pypi.org/pypi/' . rawurlencode($name) . '/json');
                $latest['python'][$name] = isset($j['info']['version']) ? $j['info']['version'] : null;
            }
            // SDK : dernier commit ayant modifié les bibliothèques + empreinte (blob git) de chaque fichier publié
            $arch = (php_uname('m') == 'aarch64') ? 'lib-aarch64' : 'lib-amd64';
            $repo = 'https://api.github.com/repos/pergolafabio/Hikvision-Addons';
            $j = self::httpJson($repo . '/commits?per_page=1&path=hikvision-doorbell/' . $arch);
            if (isset($j[0]['sha'])) {
                $files = array();
                foreach (array('', '/HCNetSDKCom') as $sub) {
                    $list = self::httpJson($repo . '/contents/hikvision-doorbell/' . $arch . $sub . '?ref=' . $j[0]['sha']);
                    foreach (is_array($list) ? $list : array() as $f) {
                        if (isset($f['type'], $f['sha']) && $f['type'] == 'file') {
                            $files[ltrim($sub . '/' . $f['name'], '/')] = $f['sha'];
                        }
                    }
                }
                $latest['sdk'] = array('sha' => $j[0]['sha'], 'date' => substr($j[0]['commit']['committer']['date'], 0, 10), 'files' => $files);
            }
            cache::set('hikinterphone::latest', $latest, 86400);
        }
        $inst = self::installedVersions();
        $rows = array();
        $python = self::getPython();
        $live = array();
        if (is_executable($python)) {
            $names = json_encode(array_keys(self::requirements()));
            $out = shell_exec($python . ' -c ' . escapeshellarg('import json,importlib.metadata as m
r={}
for n in ' . $names . ':
    try: r[n]=m.version(n)
    except Exception: r[n]=None
print(json.dumps(r))') . ' 2>/dev/null');
            $live = json_decode(trim($out), true) ?: array();
        }
        foreach (self::requirements() as $name => $min) {
            $v = isset($live[$name]) ? $live[$name] : (isset($inst['python'][$name]) ? $inst['python'][$name] : null);
            $l = isset($latest['python'][$name]) ? $latest['python'][$name] : null;
            if ($v === null) {
                $status = 'missing';
            } elseif ($min != '' && version_compare($v, $min, '<')) {
                $status = 'required';
            } elseif ($l !== null && version_compare($l, $v, '>')) {
                $status = 'update';
            } else {
                $status = 'ok';
            }
            $rows[] = array('name' => $name, 'type' => 'Python (venv)', 'installed' => $v, 'required' => $min != '' ? '≥ ' . $min : '', 'latest' => $l, 'status' => $status);
        }
        // SDK Hikvision
        $sdkInst = trim(@file_get_contents(self::getSdkDir() . '/.commit'));
        if ($sdkInst == '' && isset($inst['sdk_commit'])) {
            $sdkInst = $inst['sdk_commit'];
        }
        $wanted = self::wantedSdkCommit();
        $l = $latest['sdk'];
        // Compare le contenu des fichiers installés à ceux publiés (empreinte git) : un commit différent
        // ne veut pas dire un SDK différent.
        $changed = array();
        if ($l !== null && !empty($l['files'])) {
            foreach ($l['files'] as $name => $sha) {
                $local = self::getSdkDir() . '/' . $name;
                if ($name == 'HCNetSDK_Log_Switch.xml' || !file_exists($local)) {
                    continue;      // fichier réécrit par le plugin, ou non utilisé
                }
                $c = file_get_contents($local);
                if (sha1('blob ' . strlen($c) . "\0" . $c) !== $sha) {
                    $changed[] = $name;
                }
            }
        }
        if (!file_exists(self::getSdkDir() . '/libhcnetsdk.so')) {
            $status = 'missing';
        } elseif ($sdkInst != '' && $sdkInst != $wanted) {
            $status = 'required';
        } elseif (count($changed) > 0) {
            $status = 'update';
        } else {
            $status = 'ok';
        }
        $rows[] = array('name' => 'SDK Hikvision (HCNetSDK)', 'type' => 'pergolafabio/Hikvision-Addons',
            'installed' => $sdkInst != '' ? substr($sdkInst, 0, 8) : null, 'required' => substr($wanted, 0, 8),
            'latest' => $l !== null ? ($l['date'] . (count($changed) ? ' — ' . count($changed) . ' fichier(s) modifié(s) : ' . implode(', ', array_slice($changed, 0, 4)) : ' — identique')) : null,
            'status' => $status,
            'latest_sha' => $l !== null ? $l['sha'] : '');
        // ffmpeg (paquet système)
        $ff = trim(shell_exec('ffmpeg -version 2>/dev/null | head -1'));
        $ffv = preg_match('/ffmpeg version (\S+)/', $ff, $m) ? $m[1] : null;
        $rows[] = array('name' => 'ffmpeg', 'type' => 'paquet Debian', 'installed' => $ffv, 'required' => '', 'latest' => 'via apt', 'status' => $ffv ? 'ok' : 'missing');
        $py = is_executable($python) ? trim(shell_exec($python . ' -V 2>&1')) : null;
        $rows[] = array('name' => 'Python', 'type' => 'venv du plugin', 'installed' => $py ? str_replace('Python ', '', $py) : null, 'required' => '≥ 3.9', 'latest' => '', 'status' => $py ? 'ok' : 'missing');
        return array('rows' => $rows, 'checked' => $latest['checked'], 'installed_at' => isset($inst['date']) ? $inst['date'] : null,
            'deps_ok' => self::depsUpToDate());
    }

    /* Vérification quotidienne : message Jeedom si une mise à jour est disponible ou nécessaire */
    public static function cronDaily() {
        try {
            $info = self::libsInfo(true);
            $todo = array();
            foreach ($info['rows'] as $r) {
                if ($r['status'] != 'ok') {
                    $todo[] = $r['name'] . ' (' . ($r['installed'] ?: 'absent') . ' → ' . ($r['latest'] ?: $r['required']) . ')';
                }
            }
            message::removeAll(__CLASS__, 'libsUpdate');
            if (count($todo) > 0) {
                message::add(__CLASS__, __('Mise à jour des librairies disponible : ', __FILE__) . implode(', ', $todo)
                    . '. ' . __('Voir Plugins > Hikdoor > Configuration > Librairies.', __FILE__), '', 'libsUpdate');
            }
        } catch (Exception $e) {
            log::add(__CLASS__, 'debug', 'Vérification des librairies : ' . $e->getMessage());
        }
    }

    public static function dependancy_install() {
        log::remove(__CLASS__ . '_update');
        return array(
            'script' => __DIR__ . '/../../resources/install_apt.sh ' . jeedom::getTmpFolder(__CLASS__) . '/dependency ' . self::wantedSdkCommit(),
            'log' => log::getPathToLog(__CLASS__ . '_update')
        );
    }

    public static function getPython() {
        return realpath(__DIR__ . '/../../resources') . '/venv/bin/python3';
    }

    public static function getSdkDir() {
        return realpath(__DIR__ . '/../../resources') . '/hiksdk';
    }

    /*     * ************************ Démon ************************* */

    public static function deamon_info() {
        $return = array('log' => __CLASS__, 'state' => 'nok', 'launchable' => 'ok');
        $pid_file = jeedom::getTmpFolder(__CLASS__) . '/deamon.pid';
        if (file_exists($pid_file)) {
            if (@posix_getsid(trim(file_get_contents($pid_file)))) {
                $return['state'] = 'ok';
            } else {
                shell_exec(system::getCmdSudo() . 'rm -rf ' . $pid_file . ' 2>&1 > /dev/null');
            }
        }
        return $return;
    }

    public static function deamon_start() {
        self::deamon_stop();
        $deamon_info = self::deamon_info();
        if ($deamon_info['launchable'] != 'ok') {
            throw new Exception(__('Veuillez vérifier la configuration', __FILE__));
        }
        $path = realpath(__DIR__ . '/../../resources/hikinterphoned');
        $sdk = self::getSdkDir();
        $cmd = 'cd ' . escapeshellarg($sdk) . ' && LD_LIBRARY_PATH=' . escapeshellarg($sdk . ':' . $sdk . '/HCNetSDKCom') . ' ';
        $cmd .= self::getPython() . ' ' . $path . '/hikinterphoned.py';
        $cmd .= ' --sdkdir ' . escapeshellarg($sdk);
        $cmd .= ' --loglevel ' . log::convertLogLevel(log::getLogLevel(__CLASS__));
        $cmd .= ' --socketport ' . config::byKey('socketport', __CLASS__, 55120);
        $cmd .= ' --callback ' . network::getNetworkAccess('internal', 'proto:127.0.0.1:port:comp') . '/plugins/hikinterphone/core/php/jeeHikinterphone.php';
        $cmd .= ' --apikey ' . jeedom::getApiKey(__CLASS__);
        $cmd .= ' --pid ' . jeedom::getTmpFolder(__CLASS__) . '/deamon.pid';
        $cmd .= ' --poll ' . max(1, intval(config::byKey('poll_interval', __CLASS__, 1)));
        $cmd .= ' --talkport ' . intval(config::byKey('talkport', __CLASS__, 55121));
        if (self::ensureCertificate()) {
            $cmd .= ' --cert ' . self::getDataDir() . '/talk.crt --key ' . self::getDataDir() . '/talk.key';
        }
        log::add(__CLASS__, 'info', 'Lancement du démon');
        exec($cmd . ' >> ' . log::getPathToLog(__CLASS__ . 'd') . ' 2>&1 &');
        $i = 0;
        while ($i < 20) {
            $deamon_info = self::deamon_info();
            if ($deamon_info['state'] == 'ok') {
                break;
            }
            sleep(1);
            $i++;
        }
        if ($i >= 20) {
            log::add(__CLASS__, 'error', __('Impossible de lancer le démon, vérifiez le log', __FILE__), 'unableStartDeamon');
            return false;
        }
        message::removeAll(__CLASS__, 'unableStartDeamon');
        sleep(1);
        self::syncDaemon();
        return true;
    }

    public static function deamon_stop() {
        $pid_file = jeedom::getTmpFolder(__CLASS__) . '/deamon.pid';
        if (file_exists($pid_file)) {
            $pid = intval(trim(file_get_contents($pid_file)));
            if ($pid > 0) {
                posix_kill($pid, 15);
                sleep(1);
                if (@posix_getsid($pid)) {
                    posix_kill($pid, 9);
                }
            }
            @unlink($pid_file);
        }
        system::kill('hikinterphoned.py');
    }

    /* Envoie un message au démon et retourne sa réponse JSON (ou false) */
    public static function sendToDaemon($params, $timeout = 15) {
        $deamon_info = self::deamon_info();
        if ($deamon_info['state'] != 'ok') {
            return false;
        }
        $params['apikey'] = jeedom::getApiKey(__CLASS__);
        $payload = json_encode($params);
        $socket = @socket_create(AF_INET, SOCK_STREAM, 0);
        if ($socket === false || !@socket_connect($socket, '127.0.0.1', config::byKey('socketport', __CLASS__, 55120))) {
            log::add(__CLASS__, 'warning', 'Socket démon injoignable');
            return false;
        }
        socket_set_option($socket, SOL_SOCKET, SO_RCVTIMEO, array('sec' => $timeout, 'usec' => 0));
        socket_write($socket, $payload, strlen($payload));
        socket_shutdown($socket, 1);
        $reply = '';
        while (($chunk = @socket_read($socket, 8192)) !== false && $chunk !== '') {
            $reply .= $chunk;
        }
        socket_close($socket);
        $data = json_decode($reply, true);
        return is_array($data) ? $data : array('ok' => true);
    }

    /*     * ************************ Page Parler (HTTPS) ************************* */

    public static function getDataDir() {
        $dir = __DIR__ . '/../../data';
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        return realpath($dir);
    }

    public static function getJeedomIp() {
        $ip = network::getNetworkAccess('internal', 'ip');
        return ($ip != '') ? $ip : '127.0.0.1';
    }

    /* Certificat auto-signé (le navigateur exige le HTTPS pour donner le micro) */
    public static function ensureCertificate() {
        $dir = self::getDataDir();
        $crt = $dir . '/talk.crt';
        $key = $dir . '/talk.key';
        $ip = self::getJeedomIp();
        $ipFile = $dir . '/talk.ip';
        if (file_exists($crt) && file_exists($key) && @file_get_contents($ipFile) == $ip) {
            return true;
        }
        $cmd = 'openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -sha256'
            . ' -keyout ' . escapeshellarg($key) . ' -out ' . escapeshellarg($crt)
            . ' -subj "/CN=Jeedom interphone"'
            . ' -addext ' . escapeshellarg('subjectAltName=IP:' . $ip . ',DNS:localhost') . ' 2>&1';
        $out = shell_exec($cmd);
        if (!file_exists($crt) || !file_exists($key)) {
            log::add(__CLASS__, 'error', 'Génération du certificat impossible : ' . $out);
            return false;
        }
        chmod($key, 0600);
        file_put_contents($ipFile, $ip);
        log::add(__CLASS__, 'info', 'Certificat HTTPS généré pour ' . $ip);
        return true;
    }

    public function getTalkUrl() {
        return 'https://' . self::getJeedomIp() . ':' . intval(config::byKey('talkport', __CLASS__, 55121))
            . '/talk?eq=' . $this->getId() . '&token=' . $this->getConfiguration('talk_token');
    }

    public static function syncDaemon() {
        $equipments = array();
        foreach (eqLogic::byType(__CLASS__, true) as $eqLogic) {
            if ($eqLogic->getConfiguration('ip') == '') {
                continue;
            }
            $equipments[] = array(
                'id' => $eqLogic->getId(),
                'ip' => $eqLogic->getConfiguration('ip'),
                'protocol' => $eqLogic->getConfiguration('protocol', 'sdk'),
                'port' => $eqLogic->getConfiguration('port', 80),
                'sdk_port' => $eqLogic->getConfiguration('sdk_port', 8000),
                'voice_channel' => $eqLogic->getConfiguration('voice_channel', ''),
                'auto_answer' => $eqLogic->getConfiguration('auto_answer', 1),
                'ring_time' => $eqLogic->getConfiguration('ring_time', 90),
                'status_poll' => $eqLogic->getConfiguration('status_poll', 0),
                'https' => $eqLogic->getConfiguration('https', 0),
                'username' => $eqLogic->getConfiguration('username', 'admin'),
                'password' => $eqLogic->getConfiguration('password'),
                'alertstream' => $eqLogic->getConfiguration('alertstream', 1),
                'name' => $eqLogic->getName(),
                'door_count' => $eqLogic->getDoorCount(),
                'door1_name' => $eqLogic->getDoorName(1),
                'door2_name' => $eqLogic->getDoorName(2),
                'door3_name' => $eqLogic->getDoorName(3),
                'door4_name' => $eqLogic->getDoorName(4),
                'token' => $eqLogic->getConfiguration('talk_token'),
                'audio_listen' => $eqLogic->getConfiguration('audio_listen', 1),
                'audio_cl' => $eqLogic->getConfiguration('audio_cl', '0'),
                'snapshot_channel' => $eqLogic->getConfiguration('snapshot_channel', '101'),
                'snapshot_url' => $eqLogic->getConfiguration('snapshot_url', ''),
                'video_live' => $eqLogic->getConfiguration('video_live', 1),
                'rtsp_url' => $eqLogic->getConfiguration('rtsp_url', ''),
                'rtsp_port' => $eqLogic->getConfiguration('rtsp_port', 554),
                'rtsp_path' => $eqLogic->getConfiguration('rtsp_path', '/Streaming/Channels/102'),
                'video_fps' => $eqLogic->getConfiguration('video_fps', 12),
                'video_width' => $eqLogic->getConfiguration('video_width', 0),
            );
        }
        self::sendToDaemon(array('action' => 'sync', 'equipments' => $equipments));
    }

    /*     * ************************ Actions (via le démon) ************************* */

    public function daemonCmd($cmd) {
        $res = self::sendToDaemon(array('action' => 'cmd', 'id' => $this->getId(), 'cmd' => $cmd), 20);
        if ($res === false) {
            throw new Exception(__('Le démon Hikdoor n\'est pas démarré', __FILE__));
        }
        if (empty($res['ok'])) {
            throw new Exception($this->getHumanName() . ' : ' . (isset($res['message']) ? $res['message'] : 'erreur'));
        }
        return $res;
    }

    public function callSignal($cmdType) {
        $this->daemonCmd($cmdType);
    }

    public function openDoor($door = 1) {
        $res = self::sendToDaemon(array('action' => 'cmd', 'id' => $this->getId(), 'cmd' => 'open', 'door' => intval($door)), 20);
        if ($res === false) {
            throw new Exception(__('Le démon Hikdoor n\'est pas démarré', __FILE__));
        }
        if (empty($res['ok'])) {
            throw new Exception($this->getHumanName() . ' : ' . (isset($res['message']) ? $res['message'] : 'erreur'));
        }
    }

    public function getDoorCount() {
        return min(4, max(1, intval($this->getConfiguration('door_count', 1))));
    }

    public function getDoorName($n) {
        $name = trim($this->getConfiguration('door' . $n . '_name', ''));
        return ($name != '') ? $name : 'Porte ' . $n;
    }

    public function refreshCallStatus() {
        $res = $this->daemonCmd('refresh');
        if (isset($res['callStatus']) && $res['callStatus'] !== null) {
            $this->updateCallStatus($res['callStatus']);
        }
        if (isset($res['online']) && $res['online'] !== null) {
            $this->checkAndUpdateCmd('en_ligne', $res['online'] ? 1 : 0);
        }
    }

    public function logCapabilities() {
        $res = $this->daemonCmd('capabilities');
        log::add(__CLASS__, 'info', $this->getHumanName() . " capacités :\n" . (isset($res['message']) ? $res['message'] : ''));
    }

    public function updateCallStatus($status) {
        $this->checkAndUpdateCmd('etat_appel', $status);
        $this->checkAndUpdateCmd('sonnerie', in_array($status, array('ring', 'ringing')) ? 1 : 0);
        $this->checkAndUpdateCmd('en_communication', in_array($status, array('onCall', 'oncall', 'talking')) ? 1 : 0);
    }

    /*     * ************************ Commandes ************************* */

    public function createCommands() {
        $cmds = array(
            'etat_appel' => array('name' => 'Etat appel', 'type' => 'info', 'subType' => 'string'),
            'sonnerie' => array('name' => 'Sonnerie', 'type' => 'info', 'subType' => 'binary'),
            'en_communication' => array('name' => 'En communication', 'type' => 'info', 'subType' => 'binary'),
            'en_ligne' => array('name' => 'En ligne', 'type' => 'info', 'subType' => 'binary'),
            'dernier_evenement' => array('name' => 'Dernier événement', 'type' => 'info', 'subType' => 'string'),
            'lien_parler' => array('name' => 'Lien Parler', 'type' => 'info', 'subType' => 'string', 'visible' => 0),
            'decrocher' => array('name' => 'Décrocher', 'type' => 'action', 'subType' => 'other'),
            'raccrocher' => array('name' => 'Raccrocher', 'type' => 'action', 'subType' => 'other'),
            'refuser' => array('name' => 'Refuser', 'type' => 'action', 'subType' => 'other'),
            'ouvrir_porte' => array('name' => 'Ouvrir porte', 'type' => 'action', 'subType' => 'other'),
            'refresh' => array('name' => 'Rafraîchir', 'type' => 'action', 'subType' => 'other'),
            'capacites' => array('name' => 'Tester capacités (log)', 'type' => 'action', 'subType' => 'other', 'visible' => 0),
        );
        // Une commande d'ouverture par sortie du portier (ouvrir_porte = sortie 1, ouvrir_porte_2…)
        $doors = array();
        for ($n = 1; $n <= 4; $n++) {
            $doors[$n == 1 ? 'ouvrir_porte' : 'ouvrir_porte_' . $n] = $n;
        }
        $newCmds = array();
        foreach ($cmds as $logicalId => $def) {
            if ($logicalId == 'ouvrir_porte') {
                foreach ($doors as $id => $n) {
                    if ($n <= $this->getDoorCount()) {
                        $newCmds[$id] = array('name' => 'Ouvrir ' . $this->getDoorName($n), 'type' => 'action', 'subType' => 'other', 'door' => $n);
                    }
                }
                continue;
            }
            $newCmds[$logicalId] = $def;
        }
        $cmds = $newCmds;
        // Sorties retirées : on supprime leurs commandes (sauf la sortie 1)
        foreach ($doors as $id => $n) {
            if ($n > $this->getDoorCount()) {
                $old = $this->getCmd(null, $id);
                if (is_object($old)) {
                    $old->remove();
                }
            }
        }
        log::add(__CLASS__, 'info', $this->getHumanName() . ' commandes : ' . $this->getDoorCount() . ' sortie(s) configurée(s)');
        $created = array();
        $order = 0;
        foreach ($cmds as $logicalId => $def) {
            $cmd = $this->getCmd(null, $logicalId);
            if (!is_object($cmd)) {
                $cmd = new hikinterphoneCmd();
                $cmd->setLogicalId($logicalId);
                $cmd->setEqLogic_id($this->getId());
                $cmd->setName(__($def['name'], __FILE__));
                $cmd->setType($def['type']);
                $cmd->setSubType($def['subType']);
                $cmd->setIsVisible(isset($def['visible']) ? $def['visible'] : 1);
                $cmd->setOrder($order);
                if ($logicalId == 'sonnerie') {
                    $cmd->setIsHistorized(1);
                }
                if (isset($def['door'])) {
                    $cmd->setConfiguration('door', $def['door']);
                    $cmd->setConfiguration('autoName', $def['name']);
                }
                $cmd->save();
                $created[] = $def['name'];
                log::add(__CLASS__, 'info', $this->getHumanName() . ' commande créée : ' . $def['name']);
            } elseif (isset($def['door']) && $cmd->getName() != $def['name']
                && ($cmd->getConfiguration('autoName') == $cmd->getName() || ($cmd->getConfiguration('autoName') == '' && $cmd->getName() == 'Ouvrir porte'))) {
                // Nom de sortie changé dans l'équipement : on renomme la commande si l'utilisateur ne l'a pas renommée
                $cmd->setName($def['name']);
                $cmd->setConfiguration('autoName', $def['name']);
                $cmd->setConfiguration('door', $def['door']);
                $cmd->save();
            } elseif (isset($def['door']) && $cmd->getConfiguration('door') == '') {
                $cmd->setConfiguration('door', $def['door']);
                $cmd->save();
            }
            $order++;
        }
        return $created;
    }

    public function preSave() {
        if ($this->getConfiguration('talk_token') == '') {
            $this->setConfiguration('talk_token', bin2hex(random_bytes(16)));
        }
    }

    public function postSave() {
        $this->createCommands();
        $this->checkAndUpdateCmd('lien_parler', $this->getTalkUrl());
        self::syncDaemon();
    }

    public function postRemove() {
        self::syncDaemon();
    }
}

class hikinterphoneCmd extends cmd {

    public function dontRemoveCmd() {
        return true;
    }

    public function execute($_options = array()) {
        $eqLogic = $this->getEqLogic();
        switch ($this->getLogicalId()) {
            case 'decrocher':
                $eqLogic->callSignal('answer');
                break;
            case 'raccrocher':
                $eqLogic->callSignal('hangUp');
                break;
            case 'refuser':
                $eqLogic->callSignal('reject');
                break;
            case 'ouvrir_porte':
            case 'ouvrir_porte_2':
            case 'ouvrir_porte_3':
            case 'ouvrir_porte_4':
                $door = intval($this->getConfiguration('door', 0));
                if ($door < 1) {
                    $door = ($this->getLogicalId() == 'ouvrir_porte') ? 1 : intval(substr($this->getLogicalId(), -1));
                }
                $eqLogic->openDoor($door);
                break;
            case 'refresh':
                $eqLogic->refreshCallStatus();
                break;
            case 'capacites':
                $eqLogic->logCapabilities();
                break;
        }
    }
}
