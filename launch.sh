#!/bin/bash
# WALL-E Launch Script — Start all services with one command
# Usage:
#   bash launch.sh              # Full voice chat + eye server
#   bash launch.sh --text-only  # Text chat mode (no audio)
#   bash launch.sh --test       # Run test prompts only
#   bash launch.sh --eyes-only  # Just the eye UI server

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

echo "🟡 Checking prerequisites..."

# Check Ollama
if ! curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "  Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 3
fi

# Check model
MODEL="gemma3:4b"
if ! curl -s http://127.0.0.1:11434/api/tags | grep -q "$MODEL"; then
    echo "❌ Model $MODEL not found. Pull it first: ollama pull $MODEL"
    exit 1
fi
echo "  ✅ Ollama + $MODEL ready"

# Check venv
if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
    echo "❌ venv not found at $PROJECT_DIR/venv"
    exit 1
fi
source "$PROJECT_DIR/venv/bin/activate"

# Check kokoro models
MODELS_DIR="$PROJECT_DIR/models"
if [ ! -f "$MODELS_DIR/kokoro-v0_19.int8.onnx" ] || [ ! -f "$MODELS_DIR/voices.bin" ]; then
    echo "  ⚠️  Kokoro models not found — voice mode won't work"
    echo "  Download: curl -L -o models/kokoro-v0_19.int8.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.int8.onnx"
fi

echo ""

MODE="${1:---voice}"

case "$MODE" in
    --text-only)
        echo "🤖 Starting text chat mode..."
        python3 "$PROJECT_DIR/scripts/launch.py" --text-only
        ;;
    
    --test)
        echo "🧪 Running test prompts..."
        python3 "$PROJECT_DIR/scripts/test-chat.py" "Hello WALL-E!"
        python3 "$PROJECT_DIR/scripts/test-chat.py" "What do you think about all this trash?"
        python3 "$PROJECT_DIR/scripts/test-chat.py" "Have you seen EVA?"
        python3 "$PROJECT_DIR/scripts/test-chat.py" "Whoa, a green plant!"
        python3 "$PROJECT_DIR/scripts/test-chat.py" "안녕 WALL-E!"
        ;;
    
    --eyes-only)
        echo "👁️  Starting eye UI server only..."
        python3 "$PROJECT_DIR/scripts/eye-server.py"
        ;;
    
    --voice|*)
        echo "🔊 Starting full voice pipeline + eye server..."

        # Start eye server in background
        echo "  👁️  Eye server: http://127.0.0.1:8765"
        python3 "$PROJECT_DIR/scripts/eye-server.py" &
        EYE_PID=$!
        sleep 1

        # Start voice pipeline (foreground)
        echo "  🎤 Voice pipeline v2 starting (piper TTS + threaded)..."
        echo "=============================================="
        python3 "$PROJECT_DIR/scripts/voice-pipeline-v2.py"

        # Cleanup
        kill $EYE_PID 2>/dev/null || true
        ;;
esac
