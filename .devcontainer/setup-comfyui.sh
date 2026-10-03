#!/bin/bash
# Idempotent ComfyUI environment bootstrap for the codespace (postCreateCommand).
# - Installs/updates ComfyUI + CPU PyTorch + requirements
# - Downloads approved checkpoints/LoRAs (skips files already present & valid)
# - Generates DESIGN MODE + QUALITY MODE workflows into user/default/workflows/
# - Starts ComfyUI on private port 8188, verifies health + model visibility
# - Pushes a verification marker back to the branch
set -u
export DEBIAN_FRONTEND=noninteractive
LOG="$HOME/comfyui-setup.log"
echo "=== bootstrap start $(date -u) ===" | tee "$LOG"

sudo apt-get update -qq >>"$LOG" 2>&1
sudo apt-get install -y -qq python3-venv git curl >>"$LOG" 2>&1

# ---- ComfyUI install / update ----
if [ ! -d "$HOME/comfyui/.git" ]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$HOME/comfyui" >>"$LOG" 2>&1
else
  git -C "$HOME/comfyui" pull --ff-only >>"$LOG" 2>&1 || true
fi
cd "$HOME/comfyui"
if [ ! -d venv ]; then python3 -m venv venv; fi
./venv/bin/pip install -q --upgrade pip >>"$LOG" 2>&1
./venv/bin/pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu >>"$LOG" 2>&1
./venv/bin/pip install -q -r requirements.txt >>"$LOG" 2>&1
echo "ComfyUI ready: $(git -C "$HOME/comfyui" rev-parse --short HEAD)" | tee -a "$LOG"

# ---- Model downloads (idempotent: skip present+valid files) ----
mkdir -p models/checkpoints models/loras
CIVITAI="https://civitai.com/api/download/models"
fetch() { # $1=url $2=dest $3=expected_bytes
  local url="$1" dest="$2" expected="$3" got
  if [ -f "$dest" ]; then
    got="$(stat -c%s "$dest")"
    if [ "$got" = "$expected" ]; then echo "OK cached: $dest" | tee -a "$LOG"; return 0; fi
    echo "size mismatch ($got != $expected), re-downloading: $dest" | tee -a "$LOG"
  fi
  echo "downloading: $dest" | tee -a "$LOG"
  curl -sSL -C - -o "$dest" "$url" >>"$LOG" 2>&1
  got="$(stat -c%s "$dest")"
  if [ "$got" != "$expected" ]; then
    echo "ERROR size mismatch after download: $dest got=$got want=$expected" | tee -a "$LOG"; return 1
  fi
  echo "OK downloaded: $dest" | tee -a "$LOG"
}
CKPT=models/checkpoints
LORA=models/loras
fetch "$CIVITAI/15640"  "$CKPT/uberRealisticPornMerge_v13.safetensors" 2132648310
fetch "$CIVITAI/501240" "$CKPT/realisticVisionV60B1_v51HyperVAE_418901.safetensors" 2132625894
fetch "$CIVITAI/143906" "$CKPT/epicrealism_naturalSinRC1VAE.safetensors" 2132625612
fetch "$CIVITAI/26552"  "$LORA/URPMv1.3_LORA_296.safetensors" 349290513
fetch "$CIVITAI/8401"   "$LORA/UberVag_LORA_V1.0.safetensors" 151111100
fetch "$CIVITAI/70227"  "$LORA/FaceBeauty_qinglong_V3.safetensors" 13649414
fetch "$CIVITAI/406794" "$LORA/dynamic_shot_42_rim_light.safetensors" 37867368
fetch "$CIVITAI/26428"  "$LORA/windV3.safetensors" 37870819
fetch "$CIVITAI/88830"  "$LORA/Volumetric Lighting-000018.safetensors" 151110944
# Detail Tweaker XL (SDXL) intentionally has NO slot in SD 1.5 workflows.

# ---- Generate DESIGN MODE + QUALITY MODE workflows ----
mkdir -p user/default/workflows
python3 <<'PYEOF' >>"$LOG" 2>&1
import json, random, os
WFDIR = os.path.expanduser("~/comfyui/user/default/workflows")
RV_HYPER = "realisticVisionV60B1_v51HyperVAE_418901.safetensors"
LORAS = ["URPMv1.3_LORA_296.safetensors", "UberVag_LORA_V1.0.safetensors",
         "FaceBeauty_qinglong_V3.safetensors", "dynamic_shot_42_rim_light.safetensors",
         "windV3.safetensors", "Volumetric Lighting-000018.safetensors"]
POS = ("beautiful adult woman, 25 years old, natural beauty, portrait photograph, "
       "detailed eyes, long hair, soft cinematic lighting, realistic skin texture, "
       "elegant outfit, shallow depth of field, photorealistic, high detail")
NEG = ("low quality, blurry, distorted, deformed, bad anatomy, malformed hands, "
       "extra fingers, missing fingers, extra limbs, duplicate, poorly drawn face, "
       "crossed eyes, text, watermark")

def build(ckpt, steps, cfg, seed):
    wf = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}}}
    prev = "1"
    for i, lora in enumerate(LORAS, start=2):
        wf[str(i)] = {"class_type": "LoraLoader",
                      "inputs": {"model": [prev, 0], "clip": [prev, 1],
                                 "lora_name": lora, "strength_model": 0, "strength_clip": 0}}
        prev = str(i)
    last = prev
    n = len(LORAS)
    wf[str(n+2)] = {"class_type": "CLIPTextEncode", "inputs": {"text": POS, "clip": [last, 1]}}
    wf[str(n+3)] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": [last, 1]}}
    wf[str(n+4)] = {"class_type": "EmptyLatentImage",
                    "inputs": {"width": 512, "height": 512, "batch_size": 1}}
    wf[str(n+5)] = {"class_type": "KSampler",
                    "inputs": {"model": [last, 0], "positive": [str(n+2), 0],
                               "negative": [str(n+3), 0], "latent_image": [str(n+4), 0],
                               "seed": seed, "steps": steps, "cfg": cfg,
                               "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1}}
    wf[str(n+6)] = {"class_type": "VAEDecode", "inputs": {"samples": [str(n+5), 0], "vae": ["1", 2]}}
    wf[str(n+7)] = {"class_type": "SaveImage",
                    "inputs": {"images": [str(n+6), 0], "filename_prefix": "design"}}
    return wf

design = build(RV_HYPER, steps=8, cfg=3, seed=random.randint(0, 2**32 - 1))
quality = build(RV_HYPER, steps=25, cfg=5, seed=random.randint(0, 2**32 - 1))
open(os.path.join(WFDIR, "design-mode.json"), "w").write(json.dumps(design, indent=2))
open(os.path.join(WFDIR, "quality-mode.json"), "w").write(json.dumps(quality, indent=2))
print("workflows written: design-mode.json (8 steps, CFG 3), quality-mode.json (25 steps, CFG 5)")
PYEOF

# ---- Start ComfyUI (private port 8188) ----
pkill -f "comfyui/venv/bin/python" 2>/dev/null || true
sleep 2
cd "$HOME/comfyui"
nohup ./venv/bin/python main.py --cpu --port 8188 > "$HOME/comfyui-server.log" 2>&1 &
for i in $(seq 1 30); do
  sleep 10
  if curl -s -o /dev/null --max-time 5 http://127.0.0.1:8188/; then break; fi
done

# ---- Verify health + model visibility through ComfyUI ----
python3 <<'PYEOF' > /workspaces/agent-os/comfyui-setup-done.txt 2>>"$LOG"
import json, urllib.request
def get(p):
    with urllib.request.urlopen('http://127.0.0.1:8188' + p, timeout=30) as r:
        return json.load(r)
print("=== comfyui environment ready ===")
ss = get('/system_stats')['system']
print(f"comfyui_version={ss['comfyui_version']} ram_total={ss['ram_total']} ram_free={ss['ram_free']}")
ckpt_opts = get('/object_info/CheckpointLoaderSimple')['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
lora_opts = get('/object_info/LoraLoader')['LoraLoader']['input']['required']['lora_name'][0]
print("checkpoints visible to ComfyUI:")
for c in sorted(ckpt_opts): print("  -", c)
print("loras visible to ComfyUI:")
for l in sorted(lora_opts): print("  -", l)
expected_ckpt = {"uberRealisticPornMerge_v13.safetensors",
                 "realisticVisionV60B1_v51HyperVAE_418901.safetensors",
                 "epicrealism_naturalSinRC1VAE.safetensors"}
expected_lora = {"URPMv1.3_LORA_296.safetensors", "UberVag_LORA_V1.0.safetensors",
                 "FaceBeauty_qinglong_V3.safetensors", "dynamic_shot_42_rim_light.safetensors",
                 "windV3.safetensors", "Volumetric Lighting-000018.safetensors"}
print("all expected checkpoints visible:", expected_ckpt <= set(ckpt_opts))
print("all expected loras visible:", expected_lora <= set(lora_opts))
print("workflows:", __import__('os').listdir(__import__('os').path.expanduser("~/comfyui/user/default/workflows")))
PYEOF
echo "--- server log tail ---" >> /workspaces/agent-os/comfyui-setup-done.txt
tail -3 "$HOME/comfyui-server.log" >> /workspaces/agent-os/comfyui-setup-done.txt

cd /workspaces/agent-os
git add comfyui-setup-done.txt
git -c user.email=muse-agent@local -c user.name="muse-agent" commit -m "ComfyUI environment ready marker" >>"$LOG" 2>&1 || true
git push origin HEAD:comfyui-codespace >>"$LOG" 2>&1 || true
echo "=== bootstrap done ===" | tee -a "$LOG"
