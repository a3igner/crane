#!/usr/bin/env python3
"""Create the crane repo on GitHub and push."""
import subprocess, os, sys, json, urllib.request

token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_TOKEN", "")

# Create repo
req = urllib.request.Request(
    "https://api.github.com/user/repos",
    data=json.dumps({
        "name": "crane",
        "description": "CRANE: Cluster-Reactive Adaptive News Ensemble — A CPU-native sentiment engine that reads news, predicts markets, and adapts to regime shifts without a GPU.",
        "homepage": "https://tradeflags.com",
        "private": False,
        "auto_init": False,
    }).encode(),
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    print(f"Repository created: {data.get('html_url', 'unknown')}")
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    if e.code == 422 and "already exists" in body.get("message", ""):
        print("Repository already exists - proceeding with push")
    else:
        print(f"Error: {e.code} - {body.get('message', '')}")
        sys.exit(1)

# Set up git remote and push
os.chdir("/home/a3/crane")
subprocess.run(["git", "remote", "add", "origin", 
    f"https://a3igner:{token}@github.com/a3igner/crane.git"], 
    capture_output=True)

result = subprocess.run(["git", "push", "-u", "origin", "main"], 
    capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(result.stderr[:500])
if result.returncode == 0:
    print("\nSUCCESS! Repository pushed to https://github.com/a3igner/crane")
else:
    print(f"\nPush failed with code {result.returncode}")
