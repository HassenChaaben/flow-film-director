"""Interactive Voice Engine Setup & Diagnostics for Flow Film Director.

Audits and configures the 4 voice engines:
1. ElevenLabs (Broadcast Multilingual v2 & Instant Voice Cloning)
2. Voicebox (100% Free Local Open-Source Voice Studio & MCP Server by Jamie Pine)
3. RVC (100% Free Local Human Performance Conversion)
4. Local Zero-Shot (100% Free Local PyTorch/CUDA GPU Inference)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engines import elevenlabs_engine, rvc_engine, local_engine, voicebox_engine


def audit_engines():
    print("=" * 70)
    print("        FLOW FILM DIRECTOR — VOICE ENGINES DIAGNOSTICS")
    print("=" * 70)
    
    # 1. ElevenLabs
    el_auth = elevenlabs_engine.check_auth()
    print("\n[1] ElevenLabs Voice Studio (Cloud Multilingual v2)")
    if el_auth["ok"]:
        print(f"  Status:         ONLINE (Tier: {el_auth.get('tier', 'Active')})")
        print(f"  Quota:          {el_auth.get('character_count', 0)} / {el_auth.get('character_limit', 'unlimited')} chars used")
        print(f"  Instant Clone:  {'ENABLED' if el_auth.get('can_clone') else 'Check subscription'}")
    else:
        print(f"  Status:         NOT CONFIGURED ({el_auth['error']})")
        print("  Setup:          Set ELEVENLABS_API_KEY environment variable.")
        print("  Features:       Best-in-class Tunisian Arabic, French, and English.")

    # 2. Voicebox (Local Open-Source Studio)
    vb_status = voicebox_engine.check_voicebox_ready()
    print("\n[2] Voicebox Local Voice Studio (100% Free Open-Source & MCP)")
    if vb_status["ok"]:
        print(f"  Status:         ONLINE ({vb_status['url']})")
        print(f"  Profiles:       {vb_status.get('profile_count', 0)} voice profile(s) loaded")
        print(f"  MCP Server:     READY at {vb_status['url']}/mcp")
        print("  Features:       Local zero-shot cloning, Kokoro & Qwen3-TTS, Whisper STT.")
    else:
        print(f"  Status:         STANDBY / NOT RUNNING")
        print(f"  App / Source:   https://github.com/jamiepine/voicebox")
        print("  Info:           Run the Voicebox desktop app or server at http://127.0.0.1:17493.")
        print("  Features:       100% Free local alternative to ElevenLabs + WisprFlow with MCP.")

    # 3. RVC (Human Performance Transfer)
    rvc_status = rvc_engine.check_rvc_ready()
    print("\n[3] RVC Engine (100% Free Local Timbre Transfer)")
    if rvc_status["ok"]:
        print(f"  Status:         READY (Device: {rvc_status['device'].upper()})")
        print(f"  CUDA GPU:       {'AVAILABLE' if rvc_status['cuda'] else 'CPU Fallback'}")
        print("  Workflow:       Record lines on phone -> Converts timbre to character.")
    else:
        print(f"  Status:         UNAVAILABLE ({rvc_status.get('error')})")

    # 4. Local Zero-Shot Engine (Chatterbox / PerthNet)
    try:
        import torch
        cuda = torch.cuda.is_available()
        print("\n[4] Local Engine (Chatterbox / PerthNet in ~/.flow-film/voice-venv)")
        print(f"  Status:         READY (PyTorch {torch.__version__}, CUDA: {cuda})")
        print("  Workflow:       100% Free offline text-to-speech & local voice conversion.")
    except Exception as e:
        print(f"\n[4] Local Engine: STANDBY ({e})")
        
    print("\n" + "=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="Run diagnostic check on all voice engines")
    ap.add_argument("--set-key", help="Set ElevenLabs API key for current session")
    ap.add_argument("--set-voicebox-url", help="Set custom Voicebox URL (default: http://127.0.0.1:17493)")
    args = ap.parse_args()
    
    if args.set_key:
        os.environ["ELEVENLABS_API_KEY"] = args.set_key
        print("ElevenLabs API Key set for session.")
        
    if args.set_voicebox_url:
        os.environ["VOICEBOX_URL"] = args.set_voicebox_url
        print(f"Voicebox URL set to {args.set_voicebox_url}")
        
    audit_engines()


if __name__ == "__main__":
    main()
