# -*- coding: utf-8 -*-
"""Codec G.711 µ-law / A-law en pur Python (tables précalculées, sans audioop)."""

from array import array
import sys


_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)


def _lin2ulaw(s):
    pcm = s >> 2  # 14 bits, référence ITU / Sun
    if pcm < 0:
        pcm = -pcm
        mask = 0x7F
    else:
        mask = 0xFF
    if pcm > 8159:
        pcm = 8159
    pcm += 0x21
    seg = 8
    for i, end in enumerate(_SEG_UEND):
        if pcm <= end:
            seg = i
            break
    if seg >= 8:
        return 0x7F ^ mask
    return ((seg << 4) | ((pcm >> (seg + 1)) & 0x0F)) ^ mask


def _ulaw2lin(u):
    u = ~u & 0xFF
    sign = u & 0x80
    exp = (u >> 4) & 0x07
    mant = u & 0x0F
    s = (((mant << 3) + 0x84) << exp) - 0x84
    return -s if sign else s


_SEG_END = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)


def _lin2alaw(s):
    if s >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        s = -s - 1
    if s > 32767:
        s = 32767
    pcm = s >> 3
    seg = 8
    for i, end in enumerate(_SEG_END):
        if pcm <= end:
            seg = i
            break
    if seg >= 8:
        aval = 0x7F
    else:
        aval = seg << 4
        aval |= (pcm >> 1) & 0x0F if seg < 2 else (pcm >> seg) & 0x0F
    return aval ^ mask


def _alaw2lin(a):
    a ^= 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t += 0x108
        t <<= seg - 1
    return t if (a & 0x80) else -t


# Tables : index = échantillon 16 bits non signé (s & 0xFFFF)
_ENC = {
    "ulaw": bytes(_lin2ulaw(i - 65536 if i > 32767 else i) for i in range(65536)),
    "alaw": bytes(_lin2alaw(i - 65536 if i > 32767 else i) for i in range(65536)),
}
_DEC = {
    "ulaw": [_ulaw2lin(i) for i in range(256)],
    "alaw": [_alaw2lin(i) for i in range(256)],
}
SILENCE = {"ulaw": 0xFF, "alaw": 0xD5}


def encode(pcm16le, law):
    """PCM 16 bits little-endian -> G.711."""
    samples = array("h")
    samples.frombytes(pcm16le[: len(pcm16le) - (len(pcm16le) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    table = _ENC[law]
    return bytes(table[s & 0xFFFF] for s in samples)


def decode(data, law):
    """G.711 -> PCM 16 bits little-endian."""
    table = _DEC[law]
    out = array("h", [table[b] for b in data])
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()
