#!/usr/bin/env python3
"""validate.py — health check for Bray Music Studio deployment."""
import subprocess
import sys
import json

PASS = "✓"
FAIL = "✗"
results = []

def check(label, fn):
    try:
        msg = fn()
        print(f"  {PASS} {label}{': ' + msg if msg else ''}")
        results.append(True)
    except Exception as e:
        print(f"  {FAIL} {label}: {e}")
        results.append(False)


def container_running(name):
    out = subprocess.check_output(["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
                                   text=True).strip()
    if name not in out:
        raise RuntimeError(f"Container '{name}' not running")
    return "running"


def http_get(url, timeout=5):
    import urllib.request
    req = urllib.request.urlopen(url, timeout=timeout)
    code = req.getcode()
    if code != 200:
        raise RuntimeError(f"HTTP {code}")
    return f"HTTP {code}"


def json_get(url, timeout=5):
    import urllib.request, json
    data = json.loads(urllib.request.urlopen(url, timeout=5).read())
    return json.dumps(data)[:60]


import os, json as _json
from pathlib import Path

OUTPUTS = Path("/home/bobray/ace-step/outputs")

print("\nBray Music Studio — Deployment Validation")
print("=" * 44)
check("ace-step container running",   lambda: container_running("ace-step"))
check("bray-music-ui container running", lambda: container_running("bray-music-ui"))
check("ACE-Step Gradio API responding", lambda: http_get("http://localhost:7860/gradio_api/info"))
check("UI serving HTML",               lambda: http_get("http://localhost:7861/"))
check("Health endpoint OK",            lambda: json_get("http://localhost:7861/health"))
check("Outputs dir writable",          lambda: "ok" if os.access(OUTPUTS, os.W_OK) else (_ for _ in ()).throw(RuntimeError("not writable")))
check("history.json valid JSON",       lambda: (_json.loads((OUTPUTS / "history.json").read_text()) if (OUTPUTS / "history.json").exists() else []) and "ok")
check("covers dir exists",             lambda: "ok" if (OUTPUTS / "covers").exists() else (_ for _ in ()).throw(RuntimeError("missing")))

print()
failed = results.count(False)
if failed:
    print(f"  {FAIL} {failed} check(s) failed")
    sys.exit(1)
else:
    print(f"  {PASS} All {len(results)} checks passed — deployment looks good!")
    sys.exit(0)
