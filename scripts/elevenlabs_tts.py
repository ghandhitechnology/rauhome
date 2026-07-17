#!/usr/bin/env python3
"""WALL-E ElevenLabs TTS."""
import os, numpy as np, time
from pathlib import Path
from typing import Optional, Tuple
from elevenlabs.client import ElevenLabs

PROJECT_ROOT = Path(__file__).parent.parent
VOICE_ID = 'TX3LPaxmHKxFdv7VOQHJ'
MODEL = 'eleven_flash_v2_5'
SR = 24000
_client = None

def _get_client():
    global _client
    if _client is None:
        env = PROJECT_ROOT / '.env'
        key = None
        for line in open(env):
            k = 'ELEVENLABS_API_KEY='
            if line.startswith(k):
                key = line[len(k):].strip().strip('"').strip("'")
                break
        if not key:
            key = os.environ.get('ELEVENLABS_API_KEY','')
        _client = ElevenLabs(api_key=key)
    return _client

def tts_elevenlabs(text, voice_id=None):
    if not text or not text.strip():
        return None
    if voice_id is None:
        voice_id = VOICE_ID
    try:
        c = _get_client()
        gen = c.text_to_speech.convert(voice_id=voice_id, text=text.strip(), model_id=MODEL, output_format='pcm_24000')
        raw = b''.join(gen)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return audio, SR
    except Exception as e:
        print(f'  E11 TTS err: {e}')
        return None

def warmup():
    print('  TTS (elevenlabs)...')
    t0 = time.perf_counter()
    r = tts_elevenlabs('warm')
    if r: print(f'  ElevenLabs warm ({((time.perf_counter()-t0)*1000):.0f}ms)')
