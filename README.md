# Rau Home — Offline WALL-E on Mac mini

Private deployment source for the offline household WALL-E prototype. This repository contains
only the local interface, prompts, and runtime scripts. It intentionally excludes timing history,
memories, generated caches, models, audio recordings, credentials, and other machine-local state.

## Original implementation notes

**머신**: Apple M4 · 16GB RAM · 178GB free · macOS 26.4  
**원칙**: 완전 로컬 · Mac Mini 단독 실행 (모니터/스피커/마이크 직접 연결)

---

## 아키텍처 (Phase 1→3)

```
┌──────────────────────────────────────────┐
│              Mac Mini (M4)                │
│                                           │
│  🎤 Mic ──→ faster-whisper (STT)         │
│              ↓                            │
│  🧠 Ollama qwen3:14b (LLM + Wall-E prompt)│
│              ↓                            │
│  🎵 kokoro-onnx (TTS) + SFX overlay       │
│              ↓                            │
│  🔊 Speaker ←── audio output              │
│                                           │
│  📹 Webcam ──→ mlx-vlm / ollama vision    │
│              ↓                            │
│              "Directive! *compacts*"      │
│                                           │
│  👁️ Three.js web UI (눈 + 표정)           │
│     → localhost:8765                      │
└──────────────────────────────────────────┘
```

## 모델 선택 (16GB 기준)

| 모델 | 사이즈 | 용도 | 상태 |
|---|---|---|---|
| `qwen3:14b` | ~9GB | 메인 LLM | 다운로드 중 |
| `faster-whisper` (tiny) | ~200MB | STT | ✅ 설치됨 |
| `kokoro-onnx` | ~400MB | TTS | 설치 중 |
| `mlx-community/Qwen2-VL-7B` | ~5GB | Vision | Phase 3 |

## Phase 진행

### Phase 1: LLM + 캐릭터 ✅ 진행 중
- [x] System Prompt 작성
- [ ] qwen3:14b pull 완료 → test-chat.py 실행
- [ ] 응답 퀄리티 확인 + 프롬프트 튜닝

### Phase 2: 음성 파이프라인 (3~5일)
- [ ] faster-whisper STT 연동
- [ ] kokoro-onnx TTS 연동
- [ ] Emotion tag → SFX 매핑
- [ ] Wall-E 비프음 SFX 다운로드
- [ ] 음성 루프: Mic → STT → LLM → TTS+SFX → Speaker

### Phase 3: Vision + UI (5~7일)
- [ ] 웹캠 → Vision 모델 → "trash or treasure?" 판단
- [ ] Three.js 눈 애니메이션 (감정 태그 연동)
- [ ] Web UI (localhost:8765)

### Phase 4: 정리
- [ ] 설정 파일 분리
- [ ] launch 스크립트 (ollama serve + python voice-loop.py + web UI)
- [ ] git push

---

## 핵심 디자인 결정

1. **TTS는 Kokoro지만 로봇 효과가 핵심** — pitch shift + ring modulation으로 Wall-E 목소리
2. **SFX pre-loading** — 자주 쓰는 비프음/압축음은 메모리에 미리 로딩
3. **Emotion tag 파싱** — LLM 응답 끝의 `[HAPPY]` → 해당 SFX + 눈 애니메이션
4. **한국어는 Whisper가 처리, LLM은 영어+비프로 응답** — Wall-E 본연의 캐릭터 유지

---

## 설치할 것들

```bash
# STT - MLX 최적화 (faster-whisper 대체 고려)
pip install mlx-whisper

# TTS - 로컬
pip install kokoro-onnx onnxruntime

# 오디오 I/O
pip install sounddevice numpy

# SFX
# → freesound.org에서 Wall-E sound pack 다운로드

# Vision
pip install mlx-vlm  # 또는 Ollama로 qwen2-vl:7b pull
```
