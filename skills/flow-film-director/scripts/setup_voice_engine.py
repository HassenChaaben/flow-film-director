"""Voice engine setup & diagnostics for Flow Film Director.

Audits the 3 voice engines. All of them run on this computer; no voice audio is sent to any cloud service.
1. Voicebox (free, open-source local voice studio by Jamie Pine) - the default
2. RVC (free, local human performance conversion)
3. Local zero-shot (Chatterbox in ~/.flow-film/voice-venv, PyTorch CPU or CUDA)

Usage:
  python setup_voice_engine.py --audit
  python setup_voice_engine.py --set-voicebox-port 17493     (saved in ~/.flow-film/voicebox.json)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engines import local_engine, rvc_engine, voicebox_engine  # noqa: E402,F401


def audit_engines():
    print("=" * 70)
    print("        FLOW FILM DIRECTOR - VOICE ENGINES DIAGNOSTICS")
    print("=" * 70)

    # 1. Voicebox (local open-source studio)
    vb_status = voicebox_engine.check_voicebox_ready()
    print("\n[1] Voicebox Local Voice Studio (default, free, on this computer)")
    if vb_status["ok"]:
        print(f"  Status:         ONLINE ({vb_status['url']})")
        print(f"  Profiles:       {vb_status.get('profile_count', 0)} voice profile(s) loaded")
        print("  Features:       Local zero-shot cloning, Kokoro & Qwen3-TTS, Whisper STT.")
    else:
        print("  Status:         STANDBY / NOT RUNNING")
        print("  Info:           Start the Voicebox desktop app (GitHub project jamiepine/voicebox).")
        print(f"                  The skill looks for it on this computer, port {voicebox_engine.get_port()}.")

    # 2. RVC (human performance transfer)
    rvc_status = rvc_engine.check_rvc_ready()
    print("\n[2] RVC Engine (free, local timbre transfer)")
    if rvc_status["ok"]:
        print(f"  Status:         READY (Device: {rvc_status['device'].upper()})")
        print(f"  CUDA GPU:       {'AVAILABLE' if rvc_status['cuda'] else 'CPU Fallback'}")
        print("  Workflow:       Record lines on phone -> converts timbre to character.")
    else:
        print(f"  Status:         UNAVAILABLE ({rvc_status.get('error')})")

    # 3. Local zero-shot engine (Chatterbox)
    try:
        import torch
        cuda = torch.cuda.is_available()
        print("\n[3] Local Engine (Chatterbox in ~/.flow-film/voice-venv)")
        print(f"  Status:         READY (PyTorch {torch.__version__}, CUDA: {cuda})")
        print("  Workflow:       Offline text-to-speech & local voice conversion.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[3] Local Engine: STANDBY ({e})")

    print("\n" + "=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="Run diagnostic check on all voice engines")
    ap.add_argument("--set-voicebox-port", type=int,
                    help=f"Port of the local Voicebox app (default {voicebox_engine.DEFAULT_PORT}); host is always this computer")
    args = ap.parse_args()

    if args.set_voicebox_port:
        voicebox_engine.set_port(args.set_voicebox_port)
        print(f"Voicebox port set to {args.set_voicebox_port} (saved in {voicebox_engine.CONFIG})")

    audit_engines()


if __name__ == "__main__":
    main()
