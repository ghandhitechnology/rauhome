#!/usr/bin/env python3
"""WALL-E Eye Server"""
import json, os, time, subprocess
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock

DASH_DIR = Path(__file__).parent.parent / "dashboard"
UI_DIR = Path(__file__).parent.parent / "ui"
state = {"emotion": "idle", "text": "", "timestamp": time.time()}
chat_log = []
control_queue = []
lock = Lock()
MAX_LOG = 50

class WalleHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        d = DASH_DIR if DASH_DIR.exists() else UI_DIR
        super().__init__(*a, directory=str(d), **kw)
    def do_GET(self):
        if self.path == "/api/emotion":
            with lock: self._json(state)
        elif self.path == "/api/log":
            with lock: self._json({"log": chat_log[-MAX_LOG:]})
        elif self.path == "/api/control":
            with lock: self._json({"command": control_queue.pop(0) if control_queue else None})
        elif self.path == "/api/status":
            self._json(self._status())
        elif self.path == "/" or self.path == "":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()
    def do_POST(self):
        if self.path == "/api/emotion":
            d = json.loads(self._body())
            with lock:
                state.update(emotion=d.get("emotion","idle"), text=d.get("text",""), timestamp=time.time())
                if state["text"]:
                    chat_log.append({"role":"wall-e","text":state["text"],"emotion":state["emotion"],"time":time.strftime("%H:%M:%S")})
            self._json({"ok":True})
        elif self.path == "/api/log":
            d = json.loads(self._body())
            with lock:
                chat_log.append({"role":d.get("role","user"),"text":d.get("text",""),"time":time.strftime("%H:%M:%S")})
            self._json({"ok":True})
        elif self.path == "/api/control":
            d = json.loads(self._body())
            with lock: control_queue.append(d)
            self._json({"ok":True})
        else:
            self._err(404,"not found")
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()
    def _status(self):
        import urllib.request
        s = {"eye_server":True,"voice_pipeline":False,"ollama":False,"elevenlabs":False,"timestamp":time.time()}
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/tags"),timeout=2)
            s["ollama"] = True
        except: pass
        try:
            r = subprocess.run(["pgrep","-f","voice-pipeline"],capture_output=True,timeout=2)
            s["voice_pipeline"] = r.returncode == 0
        except: pass
        env = Path(__file__).parent.parent / ".env"
        if env.exists():
            for line in open(env):
                parts = line.split("=",1)
                if "ELEVENLABS" in line and len(parts)>1 and len(parts[1].strip()) > 10:
                    s["elevenlabs"] = True
                    break
        return s
    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length",0)))
    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def _err(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(json.dumps({"error":msg}).encode())
    def log_message(self, *a): pass

def main():
    port = 8765
    srv = HTTPServer(("127.0.0.1",port), WalleHandler)
    print(f"Eye Server: http://127.0.0.1:{port}")
    try: srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
if __name__ == "__main__":
    main()
