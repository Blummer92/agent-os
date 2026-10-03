#!/bin/bash
# Idempotent: make sure ComfyUI is listening on 8188. Runs on every container start
# (postStartCommand), so the server comes back by itself after a stop/start cycle.
port_up() { curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/ 2>/dev/null; }
if port_up; then echo "comfyui already up"; exit 0; fi
if pgrep -f "comfyui/venv/bin/python" >/dev/null 2>&1; then
  echo "comfyui process present, waiting on port"
  for i in $(seq 1 18); do sleep 10; port_up && break; done
  exit 0
fi
if [ -x "$HOME/comfyui/venv/bin/python" ]; then
  cd "$HOME/comfyui"
  nohup ./venv/bin/python main.py --cpu --port 8188 > "$HOME/comfyui-server.log" 2>&1 &
  echo "comfyui launched"
else
  echo "comfyui not installed yet; postCreateCommand will handle it"
fi
