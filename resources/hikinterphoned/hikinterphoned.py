#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Démon hikinterphone : portiers Hikvision via le SDK (port 8000) ou l'ISAPI HTTP (port 80).

- SDK : connexion persistante, alarmes poussées (sonnerie), état d'appel, signal d'appel,
  porte, image, interphonie (G.711). Recommandé : les firmwares récents bloquent l'ISAPI HTTP.
- ISAPI : HTTP Digest, callStatus + alertStream, two-way audio ISAPI.
"""

import argparse
import json
import logging
import os
import re
import signal
import socketserver
import sys
import threading
import time

import requests
from requests.auth import HTTPDigestAuth
import urllib3

import talk

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = logging.getLogger("hikinterphoned")
STOP = threading.Event()
ARGS = None
DEVICES = {}
DEVICES_LOCK = threading.Lock()
SDK = None
SDK_LOCK = threading.Lock()

# Événements de « battement de cœur » envoyés en continu par les équipements Hik
IGNORED_EVENTS = {"videoloss"}


# --------------------------------------------------------------------------- Jeedom

def send_jeedom(payload):
    try:
        r = requests.post(ARGS.callback, params={"apikey": ARGS.apikey},
                          data=json.dumps(payload), timeout=5)
        if r.status_code != 200:
            LOG.warning("Callback HTTP %s", r.status_code)
    except Exception as exc:  # noqa: BLE001
        LOG.error("Callback Jeedom impossible : %s", exc)


def get_sdk():
    global SDK
    with SDK_LOCK:
        if SDK is None:
            import hiksdk
            logdir = None
            if ARGS.loglevel.lower() == "debug":
                logdir = os.path.join(os.path.dirname(ARGS.pid), "sdklog")
            SDK = hiksdk.HikSDK(ARGS.sdkdir, logdir=logdir, loglevel=1)
        return SDK


# --------------------------------------------------------------------------- Base commune

class BaseDevice:
    protocol = ""

    def __init__(self, conf):
        self.conf = conf
        self.id = conf["id"]
        self.stop = threading.Event()
        self.last_status = None
        self.online = None
        self.threads = []
        self.listeners = set()   # WebSockets des pages Parler ouvertes
        self.talk = None         # session audio en cours

    def key(self):
        c = self.conf
        return (self.protocol, c["ip"], str(c.get("port")), str(c.get("sdk_port")), str(c.get("https")),
                c.get("username"), c.get("password"), str(c.get("alertstream")))

    def update_conf(self, conf):
        """Options qui ne nécessitent pas de redémarrer les threads."""
        self.conf.update(conf)

    def thread(self, target, name):
        t = threading.Thread(target=target, name="%s-%s" % (name, self.id), daemon=True)
        t.start()
        self.threads.append(t)

    def shutdown(self):
        self.stop.set()

    def stopped(self):
        return self.stop.is_set() or STOP.is_set()

    def set_online(self, value):
        if value != self.online:
            self.online = value
            LOG.info("[%s] %s", self.id, "en ligne" if value else "hors ligne")
            send_jeedom({"id": self.id, "online": 1 if value else 0})

    def set_status(self, status):
        if status != self.last_status:
            LOG.info("[%s] Etat appel : %s -> %s", self.id, self.last_status, status)
            self.last_status = status
            send_jeedom({"id": self.id, "callStatus": status})
            talk.notify_threadsafe(self, {"type": "status", "callStatus": status})

    def emit_event(self, label, raw=None):
        LOG.info("[%s] Evénement : %s", self.id, label)
        if raw:
            LOG.debug("[%s] Brut : %s", self.id, raw[:1500])
        send_jeedom({"id": self.id, "event": label})
        talk.notify_threadsafe(self, {"type": "event", "event": label})

    def door_count(self):
        try:
            return min(4, max(1, int(self.conf.get("door_count") or 1)))
        except ValueError:
            return 1

    def door(self, n=None):
        """N° de sortie (1..door_count). Sans précision : sortie 1."""
        try:
            n = int(n) if n not in (None, "") else 1
        except ValueError:
            n = 1
        if n < 1 or n > self.door_count():
            raise RuntimeError("Sortie %s inexistante (%s sortie(s) configurée(s))" % (n, self.door_count()))
        return n

    def door_name(self, n):
        return (self.conf.get("door%s_name" % n) or "").strip() or "Porte %s" % n

    def doors(self):
        return [{"n": i, "name": self.door_name(i)} for i in range(1, self.door_count() + 1)]


# --------------------------------------------------------------------------- SDK (port 8000)

SDK_STATUS = {1: "ring", 2: "onCall"}


class SdkDevice(BaseDevice):
    """Portier en SDK. Par défaut 100 % événementiel : aucune requête périodique vers le portier.
    - sonnerie / fin d'appel : alarmes poussées par le portier (types 17 / 18) ;
    - en communication : décroché depuis Jeedom ou page Parler active ;
    - en ligne / hors ligne : exceptions poussées par le SDK (heartbeat interne de 30 s).
    Option « status_poll » > 0 : relit en plus l'état d'appel toutes les N s (utile si l'on décroche
    depuis un moniteur intérieur ou Hik-Connect et que l'on veut le voir dans Jeedom)."""
    protocol = "sdk"
    OFFLINE_DELAY = 45

    def __init__(self, conf):
        super().__init__(conf)
        self.session = None
        self.lock = threading.RLock()
        self.ring_until = 0
        self.call_until = 0
        self.cs_mode = None       # "sdk" ou "isapi" (ISAPI via SDK), seulement si status_poll > 0
        self.next_poll = 0
        self.lost_since = 0
        self.lost_reason = ""
        self.reconnects = 0
        self.last_stats = time.time()

    def start(self):
        self.thread(self.loop, "sdk")
        LOG.info("[%s] Démarré en SDK sur %s:%s", self.id, self.conf["ip"], self.conf.get("sdk_port") or 8000)

    def shutdown(self):
        super().shutdown()
        with self.lock:
            if self.session:
                self.session.logout()
                self.session = None

    def conf_int(self, key, default, minimum=0):
        try:
            return max(minimum, int(self.conf.get(key) if self.conf.get(key) not in (None, "") else default))
        except ValueError:
            return default

    def ring_time(self):
        return self.conf_int("ring_time", 90, 5)

    def poll_interval(self):
        return self.conf_int("status_poll", 0, 0)

    def connect(self):
        import hiksdk
        s = hiksdk.SdkSession(get_sdk(), self.conf["ip"], self.conf.get("sdk_port") or 8000,
                              self.conf.get("username") or "admin", self.conf.get("password") or "",
                              self.on_alarm, self.on_exception)
        s.login()
        with self.lock:
            self.session = s
        LOG.info("[%s] Codec interphonie : %s", self.id, s.audio_codec()[1])
        if s.alarm_handle < 0:
            LOG.warning("[%s] Alarmes non armées : la sonnerie ne sera pas détectée. Réglez « Interrogation "
                        "de l'état d'appel » sur 2 à 5 s", self.id)

    def sess(self):
        with self.lock:
            if self.session is None or self.session.user_id < 0:
                raise RuntimeError("Portier non connecté (SDK)")
            return self.session

    def drop_session(self):
        with self.lock:
            if self.session:
                self.session.logout()
            self.session = None
        self.cs_mode = None

    def on_exception(self, exc_type):
        """Le portier ferme régulièrement son canal d'alarme inactif et le SDK le rouvre dans la seconde :
        ce n'est pas une panne. On ne passe « hors ligne » que si la liaison n'est pas revenue après
        OFFLINE_DELAY secondes (vérifié dans la boucle)."""
        import hiksdk
        if exc_type in hiksdk.EXC_LOST:
            if not self.lost_since:
                self.lost_since = time.time()
            self.lost_reason = "%s (0x%x)" % (hiksdk.EXC_LOST[exc_type], exc_type)
            LOG.debug("[%s] SDK : %s", self.id, self.lost_reason)
        elif exc_type in hiksdk.EXC_BACK:
            downtime = time.time() - self.lost_since if self.lost_since else 0
            self.lost_since = 0
            self.reconnects += 1
            if self.online is False:
                LOG.info("[%s] SDK : %s après %.0f s", self.id, hiksdk.EXC_BACK[exc_type], downtime)
                self.set_online(True)
            else:
                LOG.debug("[%s] SDK : %s (reconnexion rapide, %.1f s)", self.id, hiksdk.EXC_BACK[exc_type], downtime)
        else:
            LOG.debug("[%s] Exception SDK 0x%x", self.id, exc_type)

    def check_link(self):
        """Appelée chaque seconde : hors ligne seulement si la coupure dure."""
        if self.lost_since:
            down = time.time() - self.lost_since
            if down >= self.OFFLINE_DELAY and self.online is not False:
                LOG.warning("[%s] Liaison perdue depuis %.0f s (%s)", self.id, down, self.lost_reason)
                self.set_online(False)
        if time.time() - self.last_stats >= 3600:
            if self.reconnects:
                LOG.info("[%s] %s reconnexion(s) rapide(s) du canal d'alarme sur la dernière heure (normal)",
                         self.id, self.reconnects)
            self.reconnects = 0
            self.last_stats = time.time()

    def loop(self):
        delay = 5
        errors = 0
        while not self.stopped():
            if self.session is None:
                try:
                    self.connect()
                    delay = 5
                    errors = 0
                    self.lost_since = 0
                    self.set_online(True)
                    if self.last_status is None:
                        self.set_status("idle")
                except Exception as exc:  # noqa: BLE001
                    LOG.error("[%s] %s", self.id, exc)
                    self.set_online(False)
                    code = getattr(exc, "code", 0)
                    # Mauvais identifiants : on ralentit fortement pour ne pas verrouiller le compte
                    self.stop.wait(300 if code in (1, 153) else delay)
                    delay = min(60, delay * 2)
                    continue
            self.check_link()
            # Le SDK se reconnecte seul ; si la liaison reste perdue plus de 2 min, on refait un login complet
            if self.lost_since and time.time() - self.lost_since > 120:
                LOG.warning("[%s] Liaison perdue depuis 2 min : nouvelle connexion", self.id)
                self.drop_session()
                self.lost_since = 0
                continue
            # Lecture périodique optionnelle de l'état d'appel
            interval = self.poll_interval()
            if interval and time.time() >= self.next_poll:
                self.next_poll = time.time() + interval
                try:
                    self.polled = self.read_polled_status()
                    errors = 0
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    LOG.debug("[%s] Etat d'appel : %s", self.id, exc)
                    if errors >= 5:
                        LOG.warning("[%s] Etat d'appel illisible (%s), nouvelle connexion", self.id, exc)
                        self.drop_session()
                        errors = 0
                        continue
            elif not interval:
                self.polled = None
            self.set_status(self.compute_status())
            self.stop.wait(1)       # tic local, aucune requête réseau

    def compute_status(self):
        now = time.time()
        polled = getattr(self, "polled", None)
        if polled in ("ring", "onCall"):
            return polled
        if self.talk is not None or now < self.call_until:
            return "onCall"
        if now < self.ring_until:
            return "ring"
        return "idle"

    def detect_mode(self):
        s = self.sess()
        try:
            s.call_status()
            return "sdk"
        except Exception as exc:  # noqa: BLE001
            LOG.info("[%s] Etat d'appel SDK indisponible (%s)", self.id, exc)
        data = json.loads(s.isapi("GET", "/ISAPI/VideoIntercom/callStatus?format=json").decode(errors="ignore"))
        if "CallStatus" in data:
            return "isapi"
        raise RuntimeError("état d'appel non fourni par ce firmware")

    def read_polled_status(self):
        if self.cs_mode is None:
            self.cs_mode = self.detect_mode()
            LOG.info("[%s] Interrogation de l'état d'appel : %s, toutes les %s s", self.id, self.cs_mode, self.poll_interval())
        s = self.sess()
        if self.cs_mode == "sdk":
            return SDK_STATUS.get(s.call_status(), "idle")
        data = json.loads(s.isapi("GET", "/ISAPI/VideoIntercom/callStatus?format=json").decode(errors="ignore"))
        return data.get("CallStatus", {}).get("status", "idle")

    def on_alarm(self, command, info, length):
        import hiksdk
        label, kind = hiksdk.parse_alarm(command, info, length)
        if command == hiksdk.COMM_ISAPI_ALARM and label.startswith("ISAPI "):
            ev = parse_event(label[6:])
            if ev:
                if ev.get("type", "").lower() in IGNORED_EVENTS:
                    return
                label = format_event(ev)
                if kind is None and "ring" in json.dumps(ev).lower():
                    kind = "ring"
        # Toute alarme reçue prouve que la liaison est vivante
        self.lost_since = 0
        if self.online is False:
            self.set_online(True)
        if kind == "ring":
            self.ring_until = time.time() + self.ring_time()
        elif kind == "end":
            self.ring_until = 0
            self.call_until = 0
            self.polled = None
        elif "Ouverture porte" in label:
            self.ring_until = 0
        self.set_status(self.compute_status())
        self.emit_event(label)

    # ---------------------------------------------------------------- Actions
    def call_signal(self, cmd):
        via = self.sess().call_signal(cmd)
        LOG.info("[%s] Signal d'appel %s envoyé (%s)", self.id, cmd, via)
        self.ring_until = 0
        self.polled = None
        # Décroché : « En communication » jusqu'à Raccrocher / fin d'appel (180 s max par sécurité)
        self.call_until = time.time() + self.conf_int("call_time", 180, 10) if cmd == "answer" else 0
        self.set_status(self.compute_status())

    def open_door(self, door=None):
        n = self.door(door)
        via = self.sess().open_door(n)
        LOG.info("[%s] %s (sortie %s) ouverte (%s)", self.id, self.door_name(n), n, via)

    def snapshot(self):
        url = (self.conf.get("snapshot_url") or "").strip()
        if url:
            return fetch_snapshot_url(url)
        ch = self.conf.get("sdk_snapshot_channel") or None
        return self.sess().snapshot(ch)

    def capabilities(self):
        s = self.sess()
        out = ["Série %s, type %s, canaux %s (début %s), voix début %s" % (
            s.info.serial(), s.info.wDevType, s.info.byChanNum, s.info.byStartChan, s.info.byStartDTalkChan)]
        out.append("Codec interphonie : %s" % s.audio_codec()[1])
        try:
            out.append("Etat d'appel brut : %s" % s.call_status())
        except Exception as exc:  # noqa: BLE001
            out.append("Etat d'appel : %s" % exc)
        for url in ("/ISAPI/System/deviceInfo", "/ISAPI/VideoIntercom/capabilities",
                    "/ISAPI/System/TwoWayAudio/channels"):
            try:
                out.append("%s :\n%s" % (url, s.isapi("GET", url).decode(errors="ignore")))
            except Exception as exc:  # noqa: BLE001
                out.append("%s : %s" % (url, exc))
        return "\n".join(out)

    def new_talk_session(self, ws):
        return talk.SdkTalkSession(self, ws)


# --------------------------------------------------------------------------- ISAPI HTTP

class IsapiDevice(BaseDevice):
    protocol = "isapi"

    def __init__(self, conf):
        super().__init__(conf)
        scheme = "https" if str(conf.get("https", "0")) == "1" else "http"
        self.base = "%s://%s:%s" % (scheme, conf["ip"], conf.get("port") or 80)
        self.auth = HTTPDigestAuth(conf.get("username") or "admin", conf.get("password") or "")
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = False

    def start(self):
        self.thread(self.poll_loop, "poll")
        if str(self.conf.get("alertstream", "1")) == "1":
            self.thread(self.stream_loop, "stream")
        LOG.info("[%s] Démarré en ISAPI sur %s", self.id, self.base)

    def shutdown(self):
        super().shutdown()
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    def request(self, method, path, timeout=6, **kw):
        r = requests.request(method, self.base + path, auth=self.auth, verify=False,
                             timeout=(3, timeout), **kw)
        if r.status_code < 200 or r.status_code >= 300:
            raise RuntimeError("%s HTTP %s %s" % (path, r.status_code,
                                                  re.sub(r"<[^>]+>", " ", r.text)[:150].strip()))
        if b"<statusCode>" in r.content[:600] and b"<statusCode>1<" not in r.content[:600]:
            m = re.search(rb"<statusString>([^<]*)<", r.content)
            raise RuntimeError("%s : %s" % (path, (m.group(1).decode() if m else "erreur ISAPI")))
        return r

    def call_signal(self, cmd_type):
        self.request("PUT", "/ISAPI/VideoIntercom/callSignal?format=json",
                     data=json.dumps({"CallSignal": {"cmdType": cmd_type}}),
                     headers={"Content-Type": "application/json"})

    def open_door(self, door=None):
        self.request("PUT", "/ISAPI/AccessControl/RemoteControl/door/%s" % self.door(door),
                     data="<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>",
                     headers={"Content-Type": "application/xml"})

    def snapshot(self):
        url = (self.conf.get("snapshot_url") or "").strip()
        if url:
            return fetch_snapshot_url(url)
        channel = self.conf.get("snapshot_channel") or "101"
        try:
            return self.request("GET", "/ISAPI/Streaming/channels/%s/picture" % channel).content
        except RuntimeError:
            return self.request("GET", "/ISAPI/Streaming/channels/%s/picture?snapShotImageType=JPEG"
                                "&videoResolutionWidth=1280&videoResolutionHeight=720&imageQuality=best" % channel).content

    def capabilities(self):
        out = []
        for url in ("/ISAPI/System/deviceInfo", "/ISAPI/VideoIntercom/capabilities",
                    "/ISAPI/VideoIntercom/callStatus?format=json", "/ISAPI/System/TwoWayAudio/channels",
                    "/ISAPI/Event/notification/subscribeEventCap"):
            try:
                r = requests.get(self.base + url, auth=self.auth, verify=False, timeout=(3, 6))
                out.append("%s -> HTTP %s :\n%s" % (url, r.status_code, r.text[:3000]))
            except Exception as exc:  # noqa: BLE001
                out.append("%s : %s" % (url, exc))
        return "\n".join(out)

    def audio_open(self):
        """Retourne (canal, sessionId ou None, codec)."""
        channel, codec = "1", ""
        try:
            xml = self.request("GET", "/ISAPI/System/TwoWayAudio/channels").text
            m = re.search(r"<id>\s*(\d+)\s*</id>", xml)
            channel = m.group(1) if m else "1"
            m = re.search(r"<audioCompressionType>\s*([^<]+?)\s*</audioCompressionType>", xml)
            codec = m.group(1) if m else ""
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[%s] Lecture TwoWayAudio/channels impossible : %s", self.id, exc)
        try:
            self.request("PUT", "/ISAPI/System/TwoWayAudio/channels/%s/close" % channel)
        except Exception:  # noqa: BLE001
            pass
        r = self.request("PUT", "/ISAPI/System/TwoWayAudio/channels/%s/open" % channel)
        m = re.search(r"<sessionId>\s*([^<]+?)\s*</sessionId>", r.text)
        return channel, (m.group(1) if m else None), codec

    def audio_close(self, channel, session_id):
        qs = "?sessionId=%s" % session_id if session_id else ""
        self.request("PUT", "/ISAPI/System/TwoWayAudio/channels/%s/close%s" % (channel, qs))

    def new_talk_session(self, ws):
        return talk.TalkSession(self, ws)

    def poll_loop(self):
        errors = 0
        while not self.stopped():
            try:
                r = self.session.get(self.base + "/ISAPI/VideoIntercom/callStatus",
                                     params={"format": "json"}, timeout=(3, 5))
                data = r.json() if r.status_code == 200 and r.content[:1] == b"{" else None
                if data and "CallStatus" in data:
                    errors = 0
                    self.set_online(True)
                    self.set_status(data["CallStatus"].get("status", "inconnu"))
                else:
                    errors += 1
                    if errors in (1, 30):
                        LOG.warning("[%s] callStatus refusé (HTTP %s) : %s — essayez le protocole SDK",
                                    self.id, r.status_code, re.sub(r"\s+", " ", r.text)[:200])
            except Exception as exc:  # noqa: BLE001
                errors += 1
                LOG.debug("[%s] callStatus erreur : %s", self.id, exc)
            if errors >= 5:
                self.set_online(False)
            wait = ARGS.poll if errors < 5 else min(30, ARGS.poll * errors)
            self.stop.wait(wait)

    def stream_loop(self):
        while not self.stopped():
            try:
                with self.session.get(self.base + "/ISAPI/Event/notification/alertStream",
                                      stream=True, timeout=(5, 120)) as r:
                    if r.status_code != 200:
                        LOG.warning("[%s] alertStream HTTP %s", self.id, r.status_code)
                        self.stop.wait(30)
                        continue
                    m = re.search(r'boundary="?([^";]+)"?', r.headers.get("Content-Type", ""))
                    boundary = ("--" + (m.group(1) if m else "boundary")).encode()
                    LOG.info("[%s] alertStream connecté", self.id)
                    buffer = b""
                    for chunk in r.iter_content(chunk_size=1024):
                        if self.stopped():
                            return
                        if not chunk:
                            continue
                        buffer += chunk
                        while True:
                            start = buffer.find(boundary)
                            if start < 0:
                                break
                            end = buffer.find(boundary, start + len(boundary))
                            if end < 0:
                                break
                            self.handle_part(buffer[start + len(boundary):end])
                            buffer = buffer[end:]
                        if len(buffer) > 512 * 1024:
                            buffer = buffer[-65536:]
            except Exception as exc:  # noqa: BLE001
                LOG.debug("[%s] alertStream coupé : %s", self.id, exc)
            self.stop.wait(5)

    def handle_part(self, part):
        sep = part.find(b"\r\n\r\n")
        if sep < 0:
            return
        headers = part[:sep].decode(errors="ignore").lower()
        body = part[sep + 4:].strip()
        if "image/" in headers or not body:
            return
        text = body.decode(errors="ignore")
        event = parse_event(text)
        if not event or event.get("type", "").lower() in IGNORED_EVENTS:
            return
        self.emit_event(format_event(event), text)


def fetch_snapshot_url(url):
    """Image externe (ex. Frigate : http://<frigate>:5000/api/<camera>/latest.jpg)."""
    r = requests.get(url, timeout=(3, 6), verify=False)
    if r.status_code != 200 or not r.content.startswith(b"\xff\xd8"):
        raise RuntimeError("URL d'image : HTTP %s, %s octets" % (r.status_code, len(r.content)))
    return r.content


def parse_event(text):
    text = text.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        ev = {"type": data.get("eventType", "inconnu"), "state": data.get("eventState")}
        acs = data.get("AccessControllerEvent") or {}
        if acs:
            ev["major"] = acs.get("majorEventType")
            ev["minor"] = acs.get("subEventType")
            ev["door"] = acs.get("doorNo")
        return ev
    if "<" in text:
        def tag(name):
            m = re.search(r"<(?:\w+:)?%s>([^<]*)</" % name, text)
            return m.group(1).strip() if m else None
        return {"type": tag("eventType") or "inconnu", "state": tag("eventState"),
                "major": tag("majorEventType"), "minor": tag("subEventType"),
                "door": tag("doorNo")}
    return None


def format_event(event):
    label = event["type"]
    for k in ("state", "major", "minor", "door"):
        if event.get(k) not in (None, ""):
            label += " %s=%s" % (k, event[k])
    return label


# --------------------------------------------------------------------------- Socket

def make_device(conf):
    if (conf.get("protocol") or "sdk") == "isapi":
        return IsapiDevice(conf)
    return SdkDevice(conf)


def sync(equipments):
    with DEVICES_LOCK:
        wanted = {}
        for conf in equipments:
            try:
                conf["id"] = int(conf["id"])
            except (KeyError, ValueError):
                continue
            wanted[conf["id"]] = conf
        for dev_id in list(DEVICES):
            dev = DEVICES[dev_id]
            if dev_id not in wanted or make_device(dict(wanted[dev_id])).key() != dev.key():
                LOG.info("[%s] Arrêt", dev_id)
                dev.shutdown()
                del DEVICES[dev_id]
        for dev_id, conf in wanted.items():
            if dev_id in DEVICES:
                DEVICES[dev_id].update_conf(conf)
            else:
                dev = make_device(conf)
                DEVICES[dev_id] = dev
                dev.start()


def do_action(msg):
    with DEVICES_LOCK:
        dev = DEVICES.get(int(msg.get("id", 0)))
    if dev is None:
        return {"ok": False, "message": "Equipement inconnu du démon (sauvegardez-le ou relancez le démon)"}
    cmd = msg.get("cmd")
    if cmd in ("answer", "hangUp", "reject"):
        dev.call_signal(cmd)
    elif cmd == "open":
        dev.open_door(msg.get("door"))
    elif cmd == "refresh":
        return {"ok": True, "callStatus": dev.last_status, "online": dev.online}
    elif cmd == "capabilities":
        text = dev.capabilities()
        LOG.info("[%s] Capacités :\n%s", dev.id, text)
        return {"ok": True, "message": text}
    else:
        return {"ok": False, "message": "Commande inconnue %s" % cmd}
    return {"ok": True}


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        data = b""
        self.request.settimeout(5)
        try:
            while True:
                chunk = self.request.recv(8192)
                if not chunk:
                    break
                data += chunk
        except Exception:  # noqa: BLE001
            pass
        try:
            msg = json.loads(data.decode())
        except ValueError:
            LOG.error("Message socket invalide")
            return
        if msg.get("apikey") != ARGS.apikey:
            LOG.error("Apikey invalide sur la socket")
            return
        reply = {"ok": True}
        try:
            if msg.get("action") == "sync":
                sync(msg.get("equipments", []))
            elif msg.get("action") == "cmd":
                reply = do_action(msg)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Action %s : %s", msg.get("cmd", msg.get("action")), exc)
            reply = {"ok": False, "message": str(exc)}
        try:
            self.request.sendall(json.dumps(reply).encode())
        except Exception:  # noqa: BLE001
            pass


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# --------------------------------------------------------------------------- Main

def shutdown(*_):
    LOG.info("Arrêt du démon")
    STOP.set()


def main():
    global ARGS
    p = argparse.ArgumentParser()
    p.add_argument("--loglevel", default="error")
    p.add_argument("--socketport", type=int, default=55120)
    p.add_argument("--callback", required=True)
    p.add_argument("--apikey", required=True)
    p.add_argument("--pid", required=True)
    p.add_argument("--poll", type=float, default=1)
    p.add_argument("--talkport", type=int, default=55121)
    p.add_argument("--cert", default="")
    p.add_argument("--key", default="")
    p.add_argument("--sdkdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hiksdk"))
    ARGS = p.parse_args()

    levels = {"debug": logging.DEBUG, "info": logging.INFO, "notice": logging.INFO,
              "warning": logging.WARNING, "error": logging.ERROR, "none": logging.CRITICAL}
    logging.basicConfig(level=levels.get(ARGS.loglevel.lower(), logging.ERROR),
                        format="[%(asctime)s][%(levelname)s] %(threadName)s : %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    with open(ARGS.pid, "w") as f:
        f.write(str(os.getpid()))

    server = Server(("127.0.0.1", ARGS.socketport), Handler)
    threading.Thread(target=server.serve_forever, name="socket", daemon=True).start()
    LOG.info("Démon démarré, socket 127.0.0.1:%s", ARGS.socketport)

    def get_device(eq_id):
        with DEVICES_LOCK:
            return DEVICES.get(eq_id)

    if ARGS.talkport > 0:
        try:
            talk.start_server(ARGS.talkport, ARGS.cert, ARGS.key, get_device)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Serveur Parler impossible : %s", exc)

    while not STOP.is_set():
        STOP.wait(1)

    server.shutdown()
    with DEVICES_LOCK:
        for dev in DEVICES.values():
            if dev.talk is not None and talk.LOOP is not None:
                try:
                    import asyncio
                    asyncio.run_coroutine_threadsafe(dev.talk.stop(), talk.LOOP).result(3)
                except Exception:  # noqa: BLE001
                    pass
            dev.shutdown()
    if SDK is not None:
        SDK.cleanup()
    try:
        os.remove(ARGS.pid)
    except OSError:
        pass


if __name__ == "__main__":
    main()
