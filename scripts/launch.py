#!/usr/bin/env python3
"""Launch script for WALL-E voice chat.
Starts all required services and runs the voice pipeline.

Usage:
    python3 launch.py              # Full voice chat
    python3 launch.py --text-only  # Text chat mode (no audio)
    python3 launch.py --test       # Run test prompts
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def check_ollama() -> bool:
    """Check if Ollama is running and model is available."""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://127.0.0.1:11434/api/tags"],
            capture_output=True, text=True, timeout=5
        )
        return "qwen3:14b" in result.stdout or "qwen3:8b" in result.stdout
    except Exception:
        return False


def ensure_ollama_running():
    """Start Ollama if not running."""
    import json
    try:
        subprocess.run(
            ["curl", "-s", "http://127.0.0.1:11434/api/tags"],
            capture_output=True, text=True, timeout=3
        )
        print("✅ Ollama already running")
    except Exception:
        print("Starting Ollama...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        print("✅ Ollama started")


def text_chat_mode():
    """Simple text-only chat loop."""
    from test_chat import chat as wall_e_chat

    print("=" * 50)
    print("  WALL-E Text Chat")
    print("  Type 'quit' to exit, 'reset' to clear memory")
    print("=" * 50)
    print()

    messages = []

    while True:
        try:
            user_input = input("🧑 You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("\n🤖 WALL-E: *sad whir* ...bye... [SAD]")
                break
            if user_input.lower() == "reset":
                messages = []
                print("  ↻ Memory cleared")
                continue

            messages.append({"role": "user", "content": user_input})
            
            import json
            with open(PROJECT_ROOT / "prompts" / "system-prompt.md") as f:
                system = f.read()

            payload = {
                "model": "qwen3:14b",
                "messages": [
                    {"role": "system", "content": system},
                    *messages[-20:],  # Last 20 messages for context
                ],
                "stream": False,
                "options": {"temperature": 0.9, "top_p": 0.95, "num_predict": 80},
            }

            result = subprocess.run(
                ["curl", "-s", "http://127.0.0.1:11434/api/chat", "-d", json.dumps(payload)],
                capture_output=True, text=True,
            )
            data = json.loads(result.stdout)
            response = data.get("message", {}).get("content", "*confused beep* [CURIOUS]")
            
            messages.append({"role": "assistant", "content": response})
            print(f"🤖 WALL-E: {response}")
            print()

        except KeyboardInterrupt:
            print("\n\n🤖 WALL-E: *shutdown whir* ... [SAD]")
            break
        except Exception as e:
            print(f"  ⚠️ {e}")


def test_mode():
    """Run test prompts to verify character."""
    from test_chat import chat as wall_e_chat

    tests = [
        "Hello WALL-E!",
        "What do you think about all this trash?",
        "Have you seen EVA?",
        "What's your favorite treasure?",
        "There's a plant growing in the dirt!",
        "안녕 WALL-E! 심심해?",
    ]

    for msg in tests:
        print(f"\n🧑 You: {msg}")
        response = wall_e_chat(msg)
        print(f"🤖 WALL-E: {response}")
        print("-" * 40)


def main():
    ensure_ollama_running()

    if not check_ollama():
        print("❌ qwen3:14b not found. Pull it first:")
        print("   ollama pull qwen3:14b")
        sys.exit(1)

    if "--test" in sys.argv:
        test_mode()
    elif "--text-only" in sys.argv:
        text_chat_mode()
    else:
        # Default: try voice, fall back to text
        try:
            import sounddevice  # noqa
            print("🎤 Audio device found. Starting voice mode...")
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "voice-chat.py")],
                cwd=str(PROJECT_ROOT),
            )
        except ImportError:
            print("⚠️  No audio device. Falling back to text mode.")
            text_chat_mode()


if __name__ == "__main__":
    main()
