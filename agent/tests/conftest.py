import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

os.environ.setdefault("CHAT_BURST_S", "0")  # tests send one message at a time; burst merging has its own test

ROOT = Path(__file__).resolve().parents[2]  # repo root (foundry project)
ANVIL_KEYS = [
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",  # deployer / platform / issuer
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",  # demo owner
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",  # agent
]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def chain_env(tmp_path_factory):
    if not (shutil.which("anvil") and shutil.which("forge")):
        pytest.skip("anvil/forge not installed")
    port = _free_port()
    rpc = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(["anvil", "--port", str(port), "--silent"], stdout=subprocess.DEVNULL)
    time.sleep(1.5)
    env = {**os.environ, "PRIVATE_KEY": ANVIL_KEYS[0], "OWNER_PRIVATE_KEY": ANVIL_KEYS[1],
           "AGENT_PRIVATE_KEY": ANVIL_KEYS[2], "ACCOUNT_SALT": "0x" + "11" * 32, "DEMO_GRACE": "600",
           "LATE_WINDOW": "120"}  # explicit: forge auto-loads .env (Sepolia uses 2700)
    run = lambda *a: subprocess.run(a, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    try:
        run("forge", "script", "script/Deploy.s.sol", "--rpc-url", rpc, "--broadcast")
        run("cast", "rpc", "evm_increaseTime", "200", "--rpc-url", rpc)
        run("cast", "rpc", "evm_mine", "--rpc-url", rpc)
        run("forge", "script", "script/Finish.s.sol", "--rpc-url", rpc, "--broadcast")
        dep = json.loads((ROOT / "deployments" / "31337.json").read_text())
        yield {"rpc": rpc, "dep": dep, "keys": ANVIL_KEYS, "run": run}
    finally:
        proc.terminate()
