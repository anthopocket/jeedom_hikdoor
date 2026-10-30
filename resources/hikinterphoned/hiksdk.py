# -*- coding: utf-8 -*-
"""Wrapper ctypes minimal du SDK Hikvision HCNetSDK (Linux), port 8000.

Utilisé quand le portier refuse l'ISAPI en HTTP (firmwares récents : « Invalid Operation »).
Types Linux du SDK : DWORD = uint32, LONG = int32, BOOL = int32, WORD = uint16.
"""

import ctypes
import logging
import os
import threading
import time
from ctypes import (CFUNCTYPE, POINTER, Structure, byref, c_char, c_char_p, c_int32,
                    c_ubyte, c_uint16, c_uint32, c_void_p, cast, create_string_buffer, sizeof, addressof)

LOG = logging.getLogger("hikinterphoned.sdk")

DWORD = c_uint32
LONG = c_int32
BOOL = c_int32
WORD = c_uint16
BYTE = c_ubyte

# Commandes SDK
NET_DVR_GET_CALL_STATUS = 16034
NET_DVR_SET_CALL_SIGNAL = 16036
NET_DVR_REMOTECONTROL_GATEWAY = 16009

# Messages d'alarme
COMM_UPLOAD_VIDEO_INTERCOM_EVENT = 0x1132
COMM_ALARM_VIDEO_INTERCOM = 0x1133
COMM_ALARM_ACS = 0x5002
COMM_ISAPI_ALARM = 0x6009
DOORBELL_RINGING = 17            # byAlarmType de COMM_ALARM_VIDEO_INTERCOM
DISMISS_INCOMING_CALL = 18       # fin de sonnerie (raccroché, refusé, délai écoulé)
INTERCOM_ALARMS = {1: "Alarme zone", 2: "Autoprotection (arrachement)", 3: "Alarme contrainte",
                   4: "Trop d'essais de code", 5: "Porte non ouverte", 6: "Porte restée ouverte",
                   7: "Alarme panique", 8: "Alarme interphone", 19: "SOS annulé"}

# NET_DVR_VIDEO_CALL_PARAM.dwCmdType
CALL_CMD = {"request": 0, "cancel": 1, "answer": 2, "reject": 3, "timeout": 4, "hangUp": 5}

# NET_DVR_SetSDKInitCfg
NET_SDK_INIT_CFG_SDK_PATH = 2
NET_SDK_INIT_CFG_LIBEAY_PATH = 3
NET_SDK_INIT_CFG_SSLEAY_PATH = 4

AUDIO_ENC = {0: "G.722", 1: "G.711ulaw", 2: "G.711alaw", 5: "MP2L2", 6: "G.726", 7: "AAC", 8: "PCM"}


class NET_DVR_DEVICEINFO_V30(Structure):
    _fields_ = [
        ("sSerialNumber", BYTE * 48),
        ("byAlarmInPortNum", BYTE), ("byAlarmOutPortNum", BYTE), ("byDiskNum", BYTE),
        ("byDVRType", BYTE), ("byChanNum", BYTE), ("byStartChan", BYTE),
        ("byAudioChanNum", BYTE), ("byIPChanNum", BYTE), ("byZeroChanNum", BYTE),
        ("byMainProto", BYTE), ("bySubProto", BYTE), ("bySupport", BYTE),
        ("bySupport1", BYTE), ("bySupport2", BYTE), ("wDevType", WORD),
        ("bySupport3", BYTE), ("byMultiStreamProto", BYTE), ("byStartDChan", BYTE),
        ("byStartDTalkChan", BYTE), ("byHighDChanNum", BYTE), ("bySupport4", BYTE),
        ("byLanguageType", BYTE), ("byVoiceInChanNum", BYTE), ("byStartVoiceInChanNo", BYTE),
        ("byRes3", BYTE * 2), ("byMirrorChanNum", BYTE), ("wStartMirrorChanNo", WORD),
        ("byRes2", BYTE * 2),
    ]

    def serial(self):
        return bytes(self.sSerialNumber).split(b"\0")[0].decode(errors="ignore")


class NET_DVR_SETUPALARM_PARAM_V50(Structure):
    _fields_ = [
        ("dwSize", DWORD), ("byLevel", BYTE), ("byAlarmInfoType", BYTE),
        ("byRetAlarmTypeV40", BYTE), ("byRetDevInfoVersion", BYTE), ("byRetVQDAlarmType", BYTE),
        ("byFaceAlarmDetection", BYTE), ("bySupport", BYTE), ("byBrokenNetHttp", BYTE),
        ("wTaskNo", WORD), ("byDeployType", BYTE), ("byRes1", BYTE * 3),
        ("byAlarmTypeURL", BYTE), ("byCustomCtrl", BYTE), ("byRes4", BYTE * 128),
    ]


class NET_DVR_ALARMER_HEAD(Structure):
    """Début de NET_DVR_ALARMER : suffisant pour retrouver l'équipement (lUserID)."""
    _fields_ = [("byValid", BYTE * 8), ("lUserID", LONG)]


class NET_DVR_ALARM_ISAPI_INFO(Structure):
    _fields_ = [("pAlarmData", c_void_p), ("dwAlarmDataLen", DWORD), ("byDataType", BYTE),
                ("byPicturesNumber", BYTE), ("byRes", BYTE * 2), ("pPicPackData", c_void_p),
                ("byRes1", BYTE * 32)]


class NET_DVR_XML_CONFIG_INPUT(Structure):
    _fields_ = [("dwSize", DWORD), ("lpRequestUrl", c_void_p), ("dwRequestUrlLen", DWORD),
                ("lpInBuffer", c_void_p), ("dwInBufferSize", DWORD), ("dwRecvTimeOut", DWORD),
                ("byForceEncrpt", BYTE), ("byRes", BYTE * 31)]


class NET_DVR_XML_CONFIG_OUTPUT(Structure):
    _fields_ = [("dwSize", DWORD), ("lpOutBuffer", c_void_p), ("dwOutBufferSize", DWORD),
                ("dwReturnedXMLSize", DWORD), ("lpStatusBuffer", c_void_p), ("dwStatusSize", DWORD),
                ("byRes", BYTE * 32)]


class NET_DVR_VIDEO_CALL_PARAM(Structure):
    _fields_ = [("dwSize", DWORD), ("dwCmdType", DWORD), ("wPeriod", WORD),
                ("wBuildingNumber", WORD), ("wUnitNumber", WORD), ("wFloorNumber", ctypes.c_int16),
                ("wRoomNumber", WORD), ("wDevIndex", WORD), ("byUnitType", BYTE), ("byRes", BYTE * 115)]


class NET_DVR_CALL_STATUS(Structure):
    _fields_ = [("dwSize", DWORD), ("byCallStatus", BYTE), ("byRes", BYTE * 127)]


class NET_DVR_CONTROL_GATEWAY(Structure):
    _fields_ = [("dwSize", DWORD), ("dwGatewayIndex", DWORD), ("byCommand", BYTE),
                ("byLockType", BYTE), ("wLockID", WORD), ("byControlSrc", BYTE * 32),
                ("byControlType", BYTE), ("byRes3", BYTE * 3), ("byPassword", BYTE * 16),
                ("byRes2", BYTE * 108)]


class NET_DVR_COMPRESSION_AUDIO(Structure):
    _fields_ = [("byAudioEncType", BYTE), ("byAudioSamplingRate", BYTE), ("byAudioBitRate", BYTE),
                ("byres", BYTE * 4), ("bySupport", BYTE)]


class NET_DVR_JPEGPARA(Structure):
    _fields_ = [("wPicSize", WORD), ("wPicQuality", WORD)]


class NET_DVR_LOCAL_SDK_PATH(Structure):
    _fields_ = [("sPath", c_char * 256), ("byRes", BYTE * 128)]


MSGCallBack = CFUNCTYPE(BOOL, LONG, POINTER(NET_DVR_ALARMER_HEAD), c_void_p, DWORD, c_void_p)
ExceptionCallBack = CFUNCTYPE(None, DWORD, LONG, LONG, c_void_p)

# Exceptions SDK (NET_DVR_SetExceptionCallBack_V30) : perte / reprise de liaison poussées par le SDK
EXC_LOST = {0x8000: "liaison perdue", 0x8002: "canal d'alarme perdu", 0x8006: "reconnexion du canal d'alarme",
            0x8040: "reconnexion en cours"}
EXC_BACK = {0x8016: "canal d'alarme rétabli", 0x8017: "liaison rétablie", 0x8041: "reconnecté"}
VoiceDataCallBack = CFUNCTYPE(None, LONG, POINTER(c_char), DWORD, BYTE, c_void_p)


class SDKError(RuntimeError):
    def __init__(self, what, code, msg):
        super().__init__("%s : erreur SDK %s (%s)" % (what, code, msg))
        self.code = code


# Erreurs SDK les plus courantes, pour un log lisible
ERRORS = {
    1: "mot de passe ou utilisateur incorrect", 4: "canal incorrect", 7: "connexion impossible (IP / port 8000 ?)",
    10: "délai de réception dépassé", 17: "paramètre incorrect", 23: "fonction non supportée par l'appareil",
    29: "opération refusée par l'appareil", 47: "utilisateur inexistant", 153: "compte verrouillé (trop d'essais)",
}


class HikSDK:
    """Chargement unique de libhcnetsdk.so et routage des callbacks."""

    def __init__(self, libdir, logdir=None, loglevel=0):
        self.libdir = os.path.abspath(libdir)
        path = os.path.join(self.libdir, "libhcnetsdk.so")
        if not os.path.exists(path):
            raise RuntimeError("SDK absent : %s (relancez l'installation des dépendances)" % path)
        # Les bibliothèques dépendantes sont trouvées via LD_LIBRARY_PATH (positionné par Jeedom)
        # et chargées explicitement ici en secours.
        for dep in ("libhpr.so", "libHCCore.so"):
            p = os.path.join(self.libdir, dep)
            if os.path.exists(p):
                try:
                    ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
                except OSError as exc:
                    LOG.debug("Pré-chargement %s : %s", dep, exc)
        self._log_switch(logdir)
        self.lib = ctypes.CDLL(path)
        self._types()
        self._init_cfg()
        if not self.lib.NET_DVR_Init():
            raise RuntimeError("NET_DVR_Init a échoué (%s)" % self.last_error())
        self.lib.NET_DVR_SetConnectTime(3000, 1)
        self.lib.NET_DVR_SetReconnect(10000, 1)
        if logdir:
            os.makedirs(logdir, exist_ok=True)
            self.lib.NET_DVR_SetLogToFile(loglevel, logdir.encode(), 1)
        self.handlers = {}            # lUserID -> callable(command, data_ptr, length)
        self.exc_handlers = {}        # lUserID -> callable(type)
        self._exc_cb = ExceptionCallBack(self._on_exception)
        self.lib.NET_DVR_SetExceptionCallBack_V30(0, None, self._exc_cb, None)
        self._msg_cb = MSGCallBack(self._on_message)
        self.lib.NET_DVR_SetDVRMessageCallBack_V50(0, self._msg_cb, None)
        self.lock = threading.Lock()
        LOG.info("SDK Hikvision chargé (version 0x%08x)", self.lib.NET_DVR_GetSDKBuildVersion())

    def _log_switch(self, logdir):
        """Le SDK lit HCNetSDK_Log_Switch.xml au chargement : niveau INFO et dossier ./SDKLOG par défaut,
        ce qui inonde le log du démon. On force le niveau ERREUR et un dossier temporaire."""
        d = logdir or "/tmp/jeedom/hikinterphone/sdklog"
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(self.libdir, "HCNetSDK_Log_Switch.xml"), "w") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<SdkLocal>\n<SdkLog>\n'
                        '<logLevel>1</logLevel>\n<logDirectory>%s/</logDirectory>\n<autoDelete>true</autoDelete>\n'
                        '</SdkLog>\n<HeartbeatCfg>\n<Interval>30</Interval>\n<Count>1</Count>\n</HeartbeatCfg>\n'
                        '</SdkLocal>\n' % d.rstrip("/"))
        except OSError as exc:
            LOG.debug("Configuration des logs SDK impossible : %s", exc)

    def _types(self):
        L = self.lib
        sig = {
            "NET_DVR_Init": (BOOL, []),
            "NET_DVR_Cleanup": (BOOL, []),
            "NET_DVR_GetLastError": (DWORD, []),
            "NET_DVR_GetErrorMsg": (c_char_p, [POINTER(LONG)]),
            "NET_DVR_GetSDKBuildVersion": (DWORD, []),
            "NET_DVR_SetSDKInitCfg": (BOOL, [ctypes.c_int, c_void_p]),
            "NET_DVR_SetConnectTime": (BOOL, [DWORD, DWORD]),
            "NET_DVR_SetReconnect": (BOOL, [DWORD, BOOL]),
            "NET_DVR_SetLogToFile": (BOOL, [DWORD, c_char_p, BOOL]),
            "NET_DVR_Login_V30": (LONG, [c_char_p, WORD, c_char_p, c_char_p, POINTER(NET_DVR_DEVICEINFO_V30)]),
            "NET_DVR_Logout_V30": (BOOL, [LONG]),
            "NET_DVR_SetDVRMessageCallBack_V50": (BOOL, [ctypes.c_int, MSGCallBack, c_void_p]),
            "NET_DVR_SetExceptionCallBack_V30": (BOOL, [ctypes.c_uint, c_void_p, ExceptionCallBack, c_void_p]),
            "NET_DVR_SetupAlarmChan_V50": (LONG, [LONG, POINTER(NET_DVR_SETUPALARM_PARAM_V50), c_char_p, DWORD]),
            "NET_DVR_CloseAlarmChan_V30": (BOOL, [LONG]),
            "NET_DVR_GetDeviceStatus": (BOOL, [LONG, DWORD, DWORD, c_void_p, DWORD, c_void_p, c_void_p, DWORD]),
            "NET_DVR_SetDVRConfig": (BOOL, [LONG, DWORD, LONG, c_void_p, DWORD]),
            "NET_DVR_RemoteControl": (BOOL, [LONG, DWORD, c_void_p, DWORD]),
            "NET_DVR_STDXMLConfig": (BOOL, [LONG, POINTER(NET_DVR_XML_CONFIG_INPUT), POINTER(NET_DVR_XML_CONFIG_OUTPUT)]),
            "NET_DVR_CaptureJPEGPicture_NEW": (BOOL, [LONG, LONG, POINTER(NET_DVR_JPEGPARA), c_void_p, DWORD, POINTER(DWORD)]),
            "NET_DVR_GetCurrentAudioCompress": (BOOL, [LONG, POINTER(NET_DVR_COMPRESSION_AUDIO)]),
            "NET_DVR_StartVoiceCom_MR_V30": (LONG, [LONG, DWORD, VoiceDataCallBack, c_void_p]),
            "NET_DVR_VoiceComSendData": (BOOL, [LONG, c_void_p, DWORD]),
            "NET_DVR_StopVoiceCom": (BOOL, [LONG]),
        }
        for name, (res, args) in sig.items():
            fn = getattr(L, name)
            fn.restype = res
            fn.argtypes = args

    def _init_cfg(self):
        p = NET_DVR_LOCAL_SDK_PATH()
        p.sPath = (self.libdir + "/").encode()
        self.lib.NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, byref(p))
        for kind, names in ((NET_SDK_INIT_CFG_LIBEAY_PATH, ("libcrypto.so.1.1", "libcrypto.so.1.0.0", "libcrypto.so")),
                            (NET_SDK_INIT_CFG_SSLEAY_PATH, ("libssl.so.1.1", "libssl.so.1.0.0", "libssl.so"))):
            for n in names:
                f = os.path.join(self.libdir, n)
                if os.path.exists(f):
                    self._keep = getattr(self, "_keep", []) + [create_string_buffer(f.encode())]
                    self.lib.NET_DVR_SetSDKInitCfg(kind, cast(self._keep[-1], c_void_p))
                    break

    def last_error(self):
        code = self.lib.NET_DVR_GetLastError()
        msg = ERRORS.get(code)
        if not msg:
            c = LONG(code)
            raw = self.lib.NET_DVR_GetErrorMsg(byref(c))
            msg = raw.decode(errors="ignore") if raw else ""
        return code, msg

    def error(self, what):
        code, msg = self.last_error()
        return SDKError(what, code, msg)

    def _on_exception(self, exc_type, user_id, handle, user):
        try:
            handler = self.exc_handlers.get(user_id)
            if handler:
                handler(exc_type)
            else:
                LOG.debug("Exception SDK 0x%x pour userID %s", exc_type, user_id)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Callback exception : %s", exc)

    def _on_message(self, command, alarmer, info, length, user):
        try:
            uid = alarmer.contents.lUserID if alarmer else -1
            handler = self.handlers.get(uid)
            if handler:
                handler(command, info, length)
            else:
                LOG.debug("Alarme 0x%x pour userID inconnu %s", command, uid)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Callback alarme : %s", exc)
        return 1

    def cleanup(self):
        try:
            self.lib.NET_DVR_Cleanup()
        except Exception:  # noqa: BLE001
            pass


class SdkSession:
    """Connexion SDK à un portier (login + armement des alarmes)."""

    def __init__(self, sdk, ip, port, user, password, on_alarm, on_exception=None):
        self.sdk = sdk
        self.ip, self.port, self.user, self.password = ip, int(port or 8000), user, password
        self.on_alarm = on_alarm
        self.on_exception = on_exception
        self.snap_method = None
        self.snap_fail_until = 0
        self.snap_fail_msg = ""
        self.user_id = -1
        self.alarm_handle = -1
        self.info = None

    @property
    def lib(self):
        return self.sdk.lib

    def login(self):
        info = NET_DVR_DEVICEINFO_V30()
        uid = self.lib.NET_DVR_Login_V30(self.ip.encode(), self.port, self.user.encode(),
                                         self.password.encode(), byref(info))
        if uid < 0:
            raise self.sdk.error("Connexion SDK %s:%s" % (self.ip, self.port))
        self.user_id = uid
        self.info = info
        self.sdk.handlers[uid] = self.on_alarm
        if self.on_exception:
            self.sdk.exc_handlers[uid] = self.on_exception
        LOG.info("Connecté en SDK à %s:%s (série %s, type %s, voix canal %s)", self.ip, self.port,
                 info.serial(), info.wDevType, info.byStartDTalkChan or 1)
        param = NET_DVR_SETUPALARM_PARAM_V50()
        param.dwSize = sizeof(param)
        param.byLevel = 1
        param.byAlarmInfoType = 1
        param.byDeployType = 1
        param.bySupport = 0
        self.alarm_handle = self.lib.NET_DVR_SetupAlarmChan_V50(uid, byref(param), None, 0)
        if self.alarm_handle < 0:
            code, msg = self.sdk.last_error()
            LOG.warning("Armement des alarmes impossible (%s %s) : la sonnerie sera détectée par l'état d'appel", code, msg)

    def logout(self):
        if self.alarm_handle >= 0:
            self.lib.NET_DVR_CloseAlarmChan_V30(self.alarm_handle)
            self.alarm_handle = -1
        if self.user_id >= 0:
            self.sdk.handlers.pop(self.user_id, None)
            self.sdk.exc_handlers.pop(self.user_id, None)
            self.lib.NET_DVR_Logout_V30(self.user_id)
            self.user_id = -1

    # ------------------------------------------------------------------ Fonctions
    def call_status(self):
        st = NET_DVR_CALL_STATUS()
        st.dwSize = sizeof(st)
        status_list = (DWORD * 1)()
        if not self.lib.NET_DVR_GetDeviceStatus(self.user_id, NET_DVR_GET_CALL_STATUS, 1, None, 0,
                                                status_list, byref(st), sizeof(st)):
            raise self.sdk.error("Etat d'appel")
        return st.byCallStatus

    def call_signal(self, cmd):
        p = NET_DVR_VIDEO_CALL_PARAM()
        p.dwSize = sizeof(p)
        p.dwCmdType = CALL_CMD[cmd]
        p.wUnitNumber = 1
        if self.lib.NET_DVR_SetDVRConfig(self.user_id, NET_DVR_SET_CALL_SIGNAL, 1, byref(p), sizeof(p)):
            return "sdk"
        err = self.sdk.error("Signal d'appel %s" % cmd)
        # Secours : la même commande ISAPI, transportée par le SDK
        try:
            self.isapi("PUT", "/ISAPI/VideoIntercom/callSignal?format=json",
                       '{"CallSignal":{"cmdType":"%s"}}' % cmd)
            return "isapi-sdk"
        except SDKError:
            raise err

    def open_door(self, door):
        gw = NET_DVR_CONTROL_GATEWAY()
        gw.dwSize = sizeof(gw)
        gw.dwGatewayIndex = 1
        gw.byCommand = 1
        gw.byLockType = 0
        gw.wLockID = max(0, int(door) - 1)
        for i, c in enumerate(b"jeedom"):
            gw.byControlSrc[i] = c
        gw.byControlType = 1
        if self.lib.NET_DVR_RemoteControl(self.user_id, NET_DVR_REMOTECONTROL_GATEWAY, byref(gw), sizeof(gw)):
            return "sdk"
        err = self.sdk.error("Ouverture porte")
        try:
            self.isapi("PUT", "/ISAPI/AccessControl/RemoteControl/door/%s" % int(door),
                       "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>")
            return "isapi-sdk"
        except SDKError:
            raise err

    def _capture(self, chan, pic_size, quality=2):
        para = NET_DVR_JPEGPARA(pic_size, quality)
        size = 2 * 1024 * 1024
        buf = create_string_buffer(size)
        ret = DWORD(0)
        if not self.lib.NET_DVR_CaptureJPEGPicture_NEW(self.user_id, chan, byref(para), buf, size, byref(ret)):
            raise self.sdk.error("Capture image (canal %s, taille %s)" % (chan, pic_size))
        return buf.raw[:ret.value]

    @staticmethod
    def _picture_url(chan, w, h):
        return ("/ISAPI/Streaming/channels/%s/picture?snapShotImageType=JPEG"
                "&videoResolutionWidth=%s&videoResolutionHeight=%s&imageQuality=best" % (chan, w, h))

    def snapshot(self, channel=None):
        """Capture JPEG. Essaie plusieurs méthodes (celles de l'add-on HA en premier) et garde celle qui marche."""
        chans = [int(channel)] if channel else [1, 101]
        methods = []
        for ch in chans:
            for w, h in ((1280, 720), (704, 576)):
                methods.append(("isapi-%s-%sx%s" % (ch, w, h),
                                (lambda ch=ch, w=w, h=h: self.isapi("GET", self._picture_url(ch, w, h)))))
        for ch in chans:
            for sz in (0xFF, 16, 2):
                methods.append(("sdk-%s-%s" % (ch, sz), (lambda ch=ch, sz=sz: self._capture(ch, sz))))
        if time.time() < self.snap_fail_until:
            raise RuntimeError("capture indisponible (nouvel essai dans %ss) : %s" % (
                int(self.snap_fail_until - time.time()), self.snap_fail_msg))
        if self.snap_method:
            if self.snap_method in [m[0] for m in methods]:
                methods = [m for m in methods if m[0] == self.snap_method] + \
                          [m for m in methods if m[0] != self.snap_method]
        errors = []
        for name, fn in methods:
            try:
                data = fn()
            except Exception as exc:  # noqa: BLE001
                errors.append("%s : %s" % (name, exc))
                continue
            start = data.find(b"\xff\xd8")
            if start < 0 or len(data) < 500:
                errors.append("%s : pas une image JPEG (%s octets, début %r)" % (name, len(data), data[:16]))
                continue
            if self.snap_method != name:
                LOG.info("Capture image : méthode %s (%s Ko)", name, len(data) // 1024)
                self.snap_method = name
            return data[start:]
        self.snap_method = None
        self.snap_fail_msg = " | ".join(errors)
        self.snap_fail_until = time.time() + 60
        raise RuntimeError("Aucune méthode de capture ne fonctionne : " + self.snap_fail_msg)

    def audio_codec(self):
        c = NET_DVR_COMPRESSION_AUDIO()
        if self.lib.NET_DVR_GetCurrentAudioCompress(self.user_id, byref(c)):
            return c.byAudioEncType, AUDIO_ENC.get(c.byAudioEncType, "type %s" % c.byAudioEncType)
        code, msg = self.sdk.last_error()
        LOG.debug("Codec audio inconnu (%s %s), G.711ulaw supposé", code, msg)
        return 1, "G.711ulaw (supposé)"

    def isapi(self, method, url, body=""):
        """Requête ISAPI transportée par le SDK (fonctionne même si l'ISAPI HTTP est bloqué)."""
        req = create_string_buffer(("%s %s" % (method, url)).encode())
        data = body.encode() if body else b""
        inbuf = create_string_buffer(data or b"\0")
        inp = NET_DVR_XML_CONFIG_INPUT()
        inp.dwSize = sizeof(inp)
        inp.lpRequestUrl = addressof(req)
        inp.dwRequestUrlLen = len(req.value)
        inp.lpInBuffer = addressof(inbuf) if data else None
        inp.dwInBufferSize = len(data)
        inp.dwRecvTimeOut = 5000
        out = NET_DVR_XML_CONFIG_OUTPUT()
        out.dwSize = sizeof(out)
        outbuf = create_string_buffer(4 * 1024 * 1024)
        status = create_string_buffer(8 * 1024)
        out.lpOutBuffer = addressof(outbuf)
        out.dwOutBufferSize = sizeof(outbuf)
        out.lpStatusBuffer = addressof(status)
        out.dwStatusSize = sizeof(status)
        if not self.lib.NET_DVR_STDXMLConfig(self.user_id, byref(inp), byref(out)):
            err = self.sdk.error("ISAPI via SDK %s %s" % (method, url))
            detail = status.value.decode(errors="ignore").strip()
            if detail:
                LOG.debug("Réponse : %s", detail[:500])
            raise err
        n = out.dwReturnedXMLSize or len(outbuf.value)
        return outbuf.raw[:n]

    # ------------------------------------------------------------------ Voix
    def voice_start(self, channel, callback):
        h = self.lib.NET_DVR_StartVoiceCom_MR_V30(self.user_id, int(channel), callback, None)
        if h < 0:
            raise self.sdk.error("Démarrage interphonie")
        return h

    def voice_send(self, handle, data):
        buf = create_string_buffer(data, len(data))
        return bool(self.lib.NET_DVR_VoiceComSendData(handle, buf, len(data)))

    def voice_stop(self, handle):
        self.lib.NET_DVR_StopVoiceCom(handle)


def parse_alarm(command, info, length):
    """Retourne (libellé, nature) pour une alarme SDK ; nature = "ring", "end" ou None."""
    if not info:
        return "0x%x" % command, None
    if command == COMM_ALARM_VIDEO_INTERCOM:
        # dwSize(4) + NET_DVR_TIME_EX(8) + byDevNumber(32) -> byAlarmType à l'offset 44
        alarm_type = cast(info, POINTER(BYTE * 48)).contents[44]
        if alarm_type == DOORBELL_RINGING:
            return "Sonnerie", "ring"
        if alarm_type == DISMISS_INCOMING_CALL:
            return "Fin d'appel", "end"
        return INTERCOM_ALARMS.get(alarm_type, "IntercomAlarm type=%s" % alarm_type), None
    if command == COMM_UPLOAD_VIDEO_INTERCOM_EVENT:
        ev_type = cast(info, POINTER(BYTE * 48)).contents[44]
        names = {1: "Ouverture porte", 2: "Authentification", 3: "Lecture carte", 7: "Appel"}
        return "IntercomEvent %s" % names.get(ev_type, "type=%s" % ev_type), None
    if command == COMM_ISAPI_ALARM:
        isa = cast(info, POINTER(NET_DVR_ALARM_ISAPI_INFO)).contents
        if isa.pAlarmData and isa.dwAlarmDataLen:
            text = ctypes.string_at(isa.pAlarmData, min(isa.dwAlarmDataLen, 65536)).decode(errors="ignore")
            return "ISAPI " + text.strip()[:300], None
        return "ISAPI", None
    if command == COMM_ALARM_ACS:
        return "AccessControl", None
    return "Alarme 0x%x" % command, None
