#!/bin/bash
# Runs inside the codespace at creation (postCreateCommand).
# Installs ComfyUI (CPU), downloads the URPM checkpoint + 3 LoRAs from Civitai,
# starts the server on 8188, then pushes a verification marker back to the branch.
set -e
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv git curl

cd ~
if [ ! -d comfyui ]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git comfyui
fi
cd ~/comfyui
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
./venv/bin/pip install -q -r requirements.txt

mkdir -p models/checkpoints models/loras
curl -sSL -o models/checkpoints/uberRealisticPornMerge_v13.safetensors https://civitai.com/api/download/models/15640
curl -sSL -o models/loras/URPMv1.3_LORA_296.safetensors https://civitai.com/api/download/models/26552
curl -sSL -o models/loras/UberVag_LORA_V1.0.safetensors https://civitai.com/api/download/models/8401
curl -sSL -o models/loras/add-detail-xl.safetensors https://civitai.com/api/download/models/135867

# Start ComfyUI (CPU-only: codespaces have no GPU tier)
nohup ./venv/bin/python main.py --cpu --port 8188 > ~/comfyui-server.log 2>&1 &
for i in $(seq 1 30); do
  sleep 10
  if curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/; then break; fi
done

{
  echo "=== comfyui setup done $(date -u) ==="
  echo "--- /system_stats (first 600 chars) ---"
  curl -s --max-time 10 http://127.0.0.1:8188/system_stats | head -c 600; echo
  echo "--- model files ---"
  ls -la ~/comfyui/models/checkpoints/*.safetensors ~/comfyui/models/loras/*.safetensors
  echo "--- server log tail ---"
  tail -5 ~/comfyui-server.log
} > /workspaces/agent-os/comfyui-setup-done.txt

cd /workspaces/agent-os
git add comfyui-setup-done.txt
git -c user.email=muse-agent@local -c user.name="muse-agent" commit -m "ComfyUI setup complete marker" || true
git push origin HEAD:comfyui-codespace || true
