# -*- coding: utf-8 -*-
"""Serveur HTTPS + WebSocket « Parler » : pont entre le micro de la tablette et le
two-way audio ISAPI du portier (G.711, 8 kHz mono)."""

import asyncio
import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import ssl
import threading
import time

from aiohttp import web, WSMsgType

import g711

LOG = logging.getLogger("hikinterphoned.talk")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
LOOP = None
_get_device = None


# --------------------------------------------------------------------------- Digest HTTP brut

def parse_challenge(header):
    header = re.sub(r"^\s*Digest\s+", "", header, flags=re.I)
    return {k.lower(): (v1 or v2)
            for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', header)}


def digest_authorization(user, password, method, uri, chal):
    realm, nonce = chal.get("realm", ""), chal.get("nonce", "")
    qop = chal.get("qop", "")
    algo = chal.get("algorithm", "MD5")
    md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731
    ha1 = md5("%s:%s:%s" % (user, realm, password))
    if algo.upper() == "MD5-SESS":
        cnonce0 = os.urandom(8).hex()
        ha1 = md5("%s:%s:%s" % (ha1, nonce, cnonce0))
    ha2 = md5("%s:%s" % (method, uri))
    parts = ['username="%s"' % user, 'realm="%s"' % realm, 'nonce="%s"' % nonce, 'uri="%s"' % uri]
    if "auth" in [q.strip() for q in qop.split(",")]:
        nc, cnonce = "00000001", os.urandom(8).hex()
        resp = md5("%s:%s:%s:%s:auth:%s" % (ha1, nonce, nc, cnonce, ha2))
        parts += ["qop=auth", "nc=%s" % nc, 'cnonce="%s"' % cnonce]
    else:
        resp = md5("%s:%s:%s" % (ha1, nonce, ha2))
    parts.append('response="%s"' % resp)
    if chal.get("opaque"):
        parts.append('opaque="%s"' % chal["opaque"])
    if chal.get("algorithm"):
        parts.append("algorithm=%s" % chal["algorithm"])
    return "Digest " + ", ".join(parts)


async def read_head(reader):
    status = (await reader.readline()).decode(errors="ignore").strip()
    headers = {}
    while True:
        line = (await reader.readline()).decode(errors="ignore")
        if line in ("\r\n", "\n", ""):
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    code = int(status.split()[1]) if len(status.split()) > 1 and status.split()[1].isdigit() else 0
    return code, status, headers


class RawHik:
    """Connexions HTTP brutes (requête qui reste ouverte) avec Digest."""

    def __init__(self, conf):
        self.host = conf["ip"]
        self.port = int(conf.get("port") or 80)
        self.https = str(conf.get("https", "0")) == "1"
        self.user = conf.get("username") or "admin"
        self.password = conf.get("password") or ""

    async def connect(self):
        ctx = None
        if self.https:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return await asyncio.wait_for(asyncio.open_connection(self.host, self.port, ssl=ctx), 5)

    def head(self, method, path, auth=None, extra=None):
        lines = ["%s %s HTTP/1.1" % (method, path), "Host: %s:%s" % (self.host, self.port)]
        if auth:
            lines.append("Authorization: " + auth)
        for k, v in (extra or {}).items():
            lines.append("%s: %s" % (k, v))
        return ("\r\n".join(lines) + "\r\n\r\n").encode()

    async def challenge(self, method, path):
        reader, writer = await self.connect()
        try:
            writer.write(self.head(method, path, extra={"Content-Length": "0"}))
            await writer.drain()
            code, _, headers = await asyncio.wait_for(read_head(reader), 5)
            if code == 401 and "www-authenticate" in headers:
                return parse_challenge(headers["www-authenticate"])
            return None
        finally:
            writer.close()

    async def open(self, method, path, extra=None):
        chal = await self.challenge(method, path)
        auth = digest_authorization(self.user, self.password, method, path, chal) if chal else None
        reader, writer = await self.connect()
        writer.write(self.head(method, path, auth, extra))
        await writer.drain()
        return reader, writer


# --------------------------------------------------------------------------- Session audio

class TalkSession:
    def __init__(self, dev, ws):
        self.dev = dev
        self.ws = ws
        self.raw = RawHik(dev.conf)
        self.channel = "1"
        self.session_id = None
        self.law = "ulaw"
        self.up_writer = None
        self.down_writer = None
        self.tasks = []
        self.ready = False
        self.closed = False

    async def notify(self, payload):
        try:
            if not self.ws.closed:
                await self.ws.send_str(json.dumps(payload))
        except Exception:  # noqa: BLE001
            pass

    async def start(self):
        self.channel, self.session_id, codec = await asyncio.to_thread(self.dev.audio_open)
        c = (codec or "").lower()
        if "alaw" in c:
            self.law = "alaw"
        elif "ulaw" in c or c == "":
            self.law = "ulaw"
        else:
            await asyncio.to_thread(self.dev.audio_close, self.channel, self.session_id)
            raise RuntimeError("Codec %s non géré : passe le two-way audio du portier en G.711" % codec)
        qs = "?sessionId=%s" % self.session_id if self.session_id else ""
        path = "/ISAPI/System/TwoWayAudio/channels/%s/audioData%s" % (self.channel, qs)
        cl = "0" if str(self.dev.conf.get("audio_cl", "0")) == "0" else "999999999"
        up_reader, self.up_writer = await self.raw.open("PUT", path, {
            "Content-Type": "application/octet-stream", "Content-Length": cl, "Connection": "keep-alive"})
        self.tasks.append(asyncio.ensure_future(self.watch_up(up_reader)))
        if str(self.dev.conf.get("audio_listen", "1")) == "1":
            down_reader, self.down_writer = await self.raw.open("GET", path, {"Connection": "keep-alive"})
            self.tasks.append(asyncio.ensure_future(self.downlink(down_reader)))
        self.ready = True
        LOG.info("[%s] Session audio ouverte (canal %s, %s, session %s)",
                 self.dev.id, self.channel, self.law, self.session_id)
        return codec or "G.711ulaw"

    async def watch_up(self, reader):
        try:
            code, status, _ = await read_head(reader)
            LOG.info("[%s] audioData PUT : %s", self.dev.id, status)
            if code and code != 200:
                await self.notify({"type": "error", "message": "Envoi audio refusé : %s" % status})
        except Exception:  # noqa: BLE001
            pass

    async def downlink(self, reader):
        try:
            code, status, headers = await read_head(reader)
            LOG.info("[%s] audioData GET : %s", self.dev.id, status)
            if code != 200:
                await self.notify({"type": "warning", "message": "Écoute indisponible : %s" % status})
                return
            chunked = "chunked" in headers.get("transfer-encoding", "").lower()
            while not self.closed:
                if chunked:
                    size_line = (await reader.readline()).strip()
                    if not size_line:
                        continue
                    size = int(size_line.split(b";")[0], 16)
                    if size == 0:
                        break
                    data = await reader.readexactly(size)
                    await reader.readline()
                else:
                    data = await reader.read(1024)
                    if not data:
                        break
                if not self.ws.closed:
                    await self.ws.send_bytes(g711.decode(data, self.law))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.debug("[%s] Fin écoute : %s", self.dev.id, exc)

    async def send_pcm(self, pcm):
        if not self.ready or self.closed:
            return
        try:
            self.up_writer.write(g711.encode(pcm, self.law))
            await self.up_writer.drain()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[%s] Envoi audio interrompu : %s", self.dev.id, exc)
            await self.notify({"type": "error", "message": "Connexion audio perdue"})
            await self.stop()

    async def stop(self):
        if self.closed:
            return
        self.closed = True
        self.ready = False
        for t in self.tasks:
            t.cancel()
        for w in (self.up_writer, self.down_writer):
            if w:
                try:
                    w.close()
                except Exception:  # noqa: BLE001
                    pass
        try:
            await asyncio.to_thread(self.dev.audio_close, self.channel, self.session_id)
        except Exception:  # noqa: BLE001
            pass
        if self.dev.talk is self:
            self.dev.talk = None
        LOG.info("[%s] Session audio fermée", self.dev.id)
        await self.notify({"type": "audio", "state": "off"})


# --------------------------------------------------------------------------- Session audio SDK

class SdkTalkSession:
    """Interphonie via le SDK (NET_DVR_StartVoiceCom_MR_V30) : trames G.711 de 160 octets / 20 ms."""

    FRAME = 160

    def __init__(self, dev, ws):
        self.dev = dev
        self.ws = ws
        self.loop = asyncio.get_event_loop()
        self.handle = -1
        self.law = "ulaw"
        self.buf = bytearray()
        self.buf_lock = threading.Lock()
        self.closed = False
        self.ready = False
        self.sender = None
        self.rx_frames = 0
        self.tx_frames = 0
        self._cb = None

    async def notify(self, payload):
        try:
            if not self.ws.closed:
                await self.ws.send_str(json.dumps(payload))
        except Exception:  # noqa: BLE001
            pass

    def _on_voice(self, handle, data, size, flag, user):
        # flag 1 = données envoyées par le portier (déjà encodées)
        if flag != 1 or self.closed or not size:
            return
        try:
            raw = ctypes.string_at(data, size)
            self.rx_frames += 1
            pcm = g711.decode(raw, self.law)
            asyncio.run_coroutine_threadsafe(self._send_ws(pcm), self.loop)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("[%s] Réception audio : %s", self.dev.id, exc)

    async def _send_ws(self, pcm):
        if not self.ws.closed and not self.closed:
            try:
                await self.ws.send_bytes(pcm)
            except Exception:  # noqa: BLE001
                pass

    def _open(self):
        import hiksdk
        sess = self.dev.sess()
        enc, label = sess.audio_codec()
        if enc == 2:
            self.law = "alaw"
        elif enc not in (1,):
            LOG.warning("[%s] Codec interphonie %s : G.711ulaw utilisé. Réglez le portier en G.711 si le son est mauvais",
                        self.dev.id, label)
        # Si ça sonne, on décroche d'abord : sinon le portier garde le haut-parleur pour la sonnerie.
        # On se base sur l'horodatage de la sonnerie (ring_until) et non sur last_status, qui passe
        # à « onCall » dès que la session audio est créée.
        auto = str(self.dev.conf.get("auto_answer", "1")) == "1"
        now = time.time()
        ringing = now < getattr(self.dev, "ring_until", 0)
        answered = now < getattr(self.dev, "call_until", 0)
        if auto and ringing and not answered:
            try:
                LOG.info("[%s] Ça sonne : décroché automatique avant l'interphonie", self.dev.id)
                self.dev.call_signal("answer")
                time.sleep(float(self.dev.conf.get("answer_delay") or 1.0))
            except Exception as exc:  # noqa: BLE001
                LOG.warning("[%s] Décrocher avant l'interphonie : %s", self.dev.id, exc)
        elif auto:
            LOG.debug("[%s] Pas de décroché auto (sonnerie=%s, déjà décroché=%s)", self.dev.id, ringing, answered)
        self._cb = hiksdk.VoiceDataCallBack(self._on_voice)
        chan = int(self.dev.conf.get("voice_channel") or (sess.info.byStartDTalkChan or 1))
        self.handle = sess.voice_start(chan, self._cb)
        self.sess = sess
        return label

    async def start(self):
        label = await asyncio.to_thread(self._open)
        self.ready = True
        self.sender = threading.Thread(target=self._send_loop, name="voice-%s" % self.dev.id, daemon=True)
        self.sender.start()
        LOG.info("[%s] Interphonie SDK ouverte (handle %s, %s)", self.dev.id, self.handle, self.law)
        return label

    def _send_loop(self):
        silence = bytes([g711.SILENCE[self.law]]) * self.FRAME
        nxt = time.perf_counter()
        fails = 0
        while not self.closed:
            with self.buf_lock:
                if len(self.buf) >= self.FRAME:
                    frame = bytes(self.buf[:self.FRAME])
                    del self.buf[:self.FRAME]
                else:
                    frame = silence
            if self.sess.voice_send(self.handle, frame):
                self.tx_frames += 1
                fails = 0
            else:
                fails += 1
                if fails == 1 or fails % 250 == 0:
                    code, msg = self.sess.sdk.last_error()
                    LOG.warning("[%s] Envoi audio SDK refusé (%s %s)", self.dev.id, code, msg)
                if fails >= 100:
                    asyncio.run_coroutine_threadsafe(self.notify({"type": "error", "message": "Le portier refuse l'audio"}), self.loop)
                    asyncio.run_coroutine_threadsafe(self.stop(), self.loop)
                    return
            nxt += 0.020
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.perf_counter()

    async def send_pcm(self, pcm):
        if not self.ready or self.closed:
            return
        data = g711.encode(pcm, self.law)
        with self.buf_lock:
            self.buf.extend(data)
            if len(self.buf) > 4000:          # > 0,5 s de retard : on rattrape
                del self.buf[:len(self.buf) - 1600]

    async def stop(self):
        if self.closed:
            return
        self.closed = True
        self.ready = False
        if self.handle >= 0:
            h, self.handle = self.handle, -1
            await asyncio.to_thread(self.sess.voice_stop, h)
        if self.dev.talk is self:
            self.dev.talk = None
        LOG.info("[%s] Interphonie SDK fermée (envoyé %s trames, reçu %s)", self.dev.id, self.tx_frames, self.rx_frames)
        await self.notify({"type": "audio", "state": "off"})


# --------------------------------------------------------------------------- Vidéo live (RTSP -> MJPEG)

class VideoHub:
    """Un seul ffmpeg par portier, partagé entre les pages ouvertes, arrêté 10 s après le dernier spectateur.
    RTSP H.264 du portier -> MJPEG (multipart) lisible directement par une balise <img>."""

    BOUNDARY = "hikframe"

    def __init__(self, dev):
        self.dev = dev
        self.proc = None
        self.frame = None
        self.seq = 0
        self.viewers = 0
        self.cond = asyncio.Condition()
        self.reader_task = None
        self.stop_handle = None
        self.last_error = ""

    def source(self):
        c = self.dev.conf
        url = (c.get("rtsp_url") or "").strip()
        if url:
            return url
        from urllib.parse import quote
        path = (c.get("rtsp_path") or "/Streaming/Channels/102").strip()
        if not path.startswith("/"):
            path = "/" + path
        return "rtsp://%s:%s@%s:%s%s" % (quote(c.get("username") or "admin", safe=""),
                                          quote(c.get("password") or "", safe=""),
                                          c["ip"], c.get("rtsp_port") or 554, path)

    def command(self):
        c = self.dev.conf
        src = self.source()
        fps = int(c.get("video_fps") or 12)
        width = int(c.get("video_width") or 0)
        quality = int(c.get("video_quality") or 6)        # 2 (meilleur) .. 31
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
        if src.startswith("rtsp"):
            cmd += ["-rtsp_transport", "tcp", "-timeout", "5000000"]
        else:
            cmd += ["-re"]
        cmd += ["-fflags", "nobuffer", "-flags", "low_delay", "-analyzeduration", "500000", "-probesize", "500000",
                "-i", src, "-an"]
        vf = "fps=%d" % fps
        if width:
            vf += ",scale=%d:-2" % width
        cmd += ["-vf", vf, "-q:v", str(quality), "-f", "mjpeg", "pipe:1"]
        return cmd

    async def _run(self):
        backoff = 1
        while self.viewers > 0:
            cmd = self.command()
            safe = [re.sub(r"(rtsps?://)[^@/\s]*@", r"\1***@", x) for x in cmd]
            LOG.info("[%s] Vidéo : démarrage ffmpeg (%s)", self.dev.id, " ".join(safe[-12:]))
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            except FileNotFoundError:
                self.last_error = "ffmpeg absent (relancez l'installation des dépendances)"
                LOG.error("[%s] %s", self.dev.id, self.last_error)
                return
            err_task = asyncio.ensure_future(self.proc.stderr.read())
            buf = bytearray()
            got = 0
            try:
                while True:
                    chunk = await self.proc.stdout.read(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        s = buf.find(b"\xff\xd8")
                        if s < 0:
                            buf.clear()
                            break
                        e = buf.find(b"\xff\xd9", s + 2)
                        if e < 0:
                            if s:
                                del buf[:s]
                            break
                        frame = bytes(buf[s:e + 2])
                        del buf[:e + 2]
                        got += 1
                        backoff = 1
                        async with self.cond:
                            self.frame = frame
                            self.seq += 1
                            self.cond.notify_all()
                    if len(buf) > 4 * 1024 * 1024:
                        buf.clear()
            finally:
                if self.proc.returncode is None:
                    self.proc.kill()
                await self.proc.wait()
                err = (await err_task).decode(errors="ignore").strip()
            if self.viewers <= 0:
                break
            self.last_error = re.sub(r"(rtsps?://)[^@/\s]*@", r"\1***@", err)[-300:] or "flux interrompu"
            LOG.warning("[%s] Vidéo : ffmpeg arrêté après %s images : %s", self.dev.id, got, self.last_error)
            await asyncio.sleep(backoff)
            backoff = min(30, backoff * 2)
        self.proc = None
        LOG.info("[%s] Vidéo : arrêt", self.dev.id)

    def join(self):
        self.viewers += 1
        if self.stop_handle:
            self.stop_handle.cancel()
            self.stop_handle = None
        if self.reader_task is None or self.reader_task.done():
            self.reader_task = asyncio.ensure_future(self._run())

    def leave(self):
        self.viewers -= 1
        if self.viewers <= 0:
            self.viewers = 0
            loop = asyncio.get_event_loop()
            self.stop_handle = loop.call_later(10, self._stop_now)

    def _stop_now(self):
        self.stop_handle = None
        if self.viewers <= 0 and self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()


def video_hub(dev):
    hub = getattr(dev, "video_hub", None)
    if hub is None:
        hub = VideoHub(dev)
        dev.video_hub = hub
    return hub


# --------------------------------------------------------------------------- Web

def device_from(request):
    try:
        eq_id = int(request.query.get("eq", ""))
    except ValueError:
        raise web.HTTPForbidden()
    dev = _get_device(eq_id)
    token = request.query.get("token", "")
    if not dev or not dev.conf.get("token") or not hmac.compare_digest(token, str(dev.conf["token"])):
        raise web.HTTPForbidden()
    return dev


NO_CACHE = {"Cache-Control": "no-store"}


async def page(request):
    device_from(request)
    return web.FileResponse(os.path.join(WEB_DIR, "talk.html"), headers=NO_CACHE)


async def snapshot(request):
    dev = device_from(request)
    try:
        data = await asyncio.to_thread(dev.snapshot)
    except Exception as exc:  # noqa: BLE001
        now = time.time()
        if now - getattr(dev, "_snap_err_log", 0) > 60:
            dev._snap_err_log = now
            LOG.warning("[%s] Image du portier : %s", dev.id, exc)
        raise web.HTTPBadGateway(text=str(exc))
    return web.Response(body=data, content_type="image/jpeg", headers=NO_CACHE)


async def mjpeg(request):
    dev = device_from(request)
    if str(dev.conf.get("video_live", "1")) != "1":
        raise web.HTTPNotFound(text="vidéo live désactivée")
    hub = video_hub(dev)
    hub.join()
    resp = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=%s" % VideoHub.BOUNDARY,
        "Cache-Control": "no-store", "Pragma": "no-cache", "Connection": "close"})
    await resp.prepare(request)
    last = 0
    try:
        while True:
            async with hub.cond:
                try:
                    await asyncio.wait_for(hub.cond.wait_for(lambda: hub.seq != last), 2)
                except asyncio.TimeoutError:
                    # Pas d'image : on vérifie que le navigateur est toujours là (sinon on libère ffmpeg)
                    if request.transport is None or request.transport.is_closing():
                        break
                    if hub.reader_task is None or hub.reader_task.done():
                        break
                    continue
                frame, last = hub.frame, hub.seq
            await resp.write(("--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                              % (VideoHub.BOUNDARY, len(frame))).encode() + frame + b"\r\n")
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        hub.leave()
    return resp


async def action(request):
    dev = device_from(request)
    cmd = request.query.get("cmd", "")
    try:
        if cmd in ("answer", "hangUp", "reject"):
            await asyncio.to_thread(dev.call_signal, cmd)
        elif cmd == "open":
            await asyncio.to_thread(dev.open_door, request.query.get("door"))
        else:
            raise web.HTTPBadRequest()
    except web.HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"ok": False, "message": str(exc)})
    return web.json_response({"ok": True})


async def websocket(request):
    dev = device_from(request)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)
    dev.listeners.add(ws)
    await ws.send_str(json.dumps({"type": "status", "callStatus": dev.last_status,
                                  "name": dev.conf.get("name", ""), "doors": dev.doors()}))
    session = None
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                if session is not None:
                    await session.send_pcm(msg.data)
            elif msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                cmd = data.get("cmd")
                if cmd == "audio_start":
                    if session is not None:
                        await session.stop()
                    if dev.talk is not None:
                        await dev.talk.notify({"type": "warning", "message": "Audio repris par une autre tablette"})
                        await dev.talk.stop()
                    session = dev.new_talk_session(ws)
                    dev.talk = session
                    try:
                        codec = await session.start()
                        await ws.send_str(json.dumps({"type": "audio", "state": "on", "codec": codec}))
                    except Exception as exc:  # noqa: BLE001
                        LOG.error("[%s] Ouverture audio impossible : %s", dev.id, exc)
                        await session.stop()
                        session = None
                        await ws.send_str(json.dumps({"type": "error", "message": "Audio : %s" % exc}))
                elif cmd == "audio_stop" and session is not None:
                    await session.stop()
                    session = None
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        dev.listeners.discard(ws)
        if session is not None:
            await session.stop()
    return ws


async def broadcast(dev, payload):
    text = json.dumps(payload)
    for ws in list(dev.listeners):
        try:
            await ws.send_str(text)
        except Exception:  # noqa: BLE001
            dev.listeners.discard(ws)


def notify_threadsafe(dev, payload):
    if LOOP is not None and dev.listeners:
        asyncio.run_coroutine_threadsafe(broadcast(dev, payload), LOOP)


def start_server(port, certfile, keyfile, get_device):
    """Lance le serveur dans un thread dédié avec sa propre boucle asyncio."""
    global _get_device
    _get_device = get_device
    ready = threading.Event()

    def run():
        global LOOP
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_get("/talk", page)
        app.router.add_get("/ws", websocket)
        app.router.add_get("/snapshot", snapshot)
        app.router.add_get("/mjpeg", mjpeg)
        app.router.add_post("/action", action)
        ctx = None
        if certfile and os.path.exists(certfile):
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(certfile, keyfile)
        else:
            LOG.warning("Pas de certificat : page Parler en HTTP (micro refusé par le navigateur)")
        runner = web.AppRunner(app, access_log=None)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", port, ssl_context=ctx).start())
        LOOP = loop
        LOG.info("Page Parler sur %s://<ip>:%s/talk", "https" if ctx else "http", port)
        ready.set()
        loop.run_forever()

    threading.Thread(target=run, name="talk", daemon=True).start()
    ready.wait(10)
