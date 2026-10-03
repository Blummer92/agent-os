#!/bin/bash
# Wrapper for postStartCommand: ensure the server is up, then prove this hook ran.
bash .devcontainer/ensure-server.sh
{
  echo "postStartCommand ran at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname: $(hostname)"
  if curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/ 2>/dev/null; then
    echo "port 8188: LISTENING after ensure"
  else
    echo "port 8188: NOT listening after ensure"
  fi
} > /workspaces/agent-os/poststart-proof.txt 2>&1
cd /workspaces/agent-os
git add poststart-proof.txt
git -c user.email=muse-agent@local -c user.name="muse-agent" commit -m "postStartCommand proof" 2>/dev/null || true
git push origin HEAD:comfyui-codespace 2>/dev/null || true
