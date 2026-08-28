"""8 kHz mu-law helpers.

Both Plivo and Twilio stream G.711 mu-law, and Deepgram/Cartesia both speak it
natively, so audio normally passes straight through without transcoding. The
decode table exists for local energy measurement (silence detection and the
barge-in fallback), which needs linear samples.
"""

from __future__ import annotations

import math

BIAS = 0x84
CLIP = 32635

# Decoding is a 256-entry lookup, so it costs nothing on the hot path.
_MULAW_DECODE: list[int] = []
for _byte in range(256):
    _u = ~_byte & 0xFF
    _sign = _u & 0x80
    _exponent = (_u >> 4) & 0x07
    _mantissa = _u & 0x0F
    _sample = ((_mantissa << 3) + BIAS) << _exponent
    _sample -= BIAS
    _MULAW_DECODE.append(-_sample if _sign else _sample)


def mulaw_to_pcm(payload: bytes) -> list[int]:
    return [_MULAW_DECODE[byte] for byte in payload]


def pcm_to_mulaw(samples: list[int]) -> bytes:
    out = bytearray()
    for sample in samples:
        sign = 0x80 if sample < 0 else 0x00
        magnitude = min(abs(sample), CLIP) + BIAS
        exponent = 7
        mask = 0x4000
        while exponent > 0 and not magnitude & mask:
            mask >>= 1
            exponent -= 1
        mantissa = (magnitude >> (exponent + 3)) & 0x0F
        out.append(~(sign | (exponent << 4) | mantissa) & 0xFF)
    return bytes(out)


def rms_dbfs(payload: bytes) -> float:
    """Loudness of a mu-law frame in dBFS. Silence returns -100."""
    if not payload:
        return -100.0
    samples = mulaw_to_pcm(payload)
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0:
        return -100.0
    return 20 * math.log10(math.sqrt(mean_square) / 32768.0)


def frame_duration_ms(payload: bytes, sample_rate: int = 8000) -> float:
    """mu-law is one byte per sample."""
    return len(payload) / sample_rate * 1000
