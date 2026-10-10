# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Speak MCP over stdio to a server started as `python SERVER.pyz`, as Claude Desktop would:
initialize, then call the `add` tool. Exits 0 and prints the answer if it works."""

import json
import subprocess
import sys


def main() -> int:
    python, bundle = sys.argv[1], sys.argv[2]
    server = subprocess.Popen(
        [python, bundle], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert server.stdin is not None and server.stdout is not None

    def send(message: dict) -> None:
        server.stdin.write(json.dumps(message) + "\n")
        server.stdin.flush()

    def answer() -> dict:
        while True:
            line = server.stdout.readline()
            if not line:
                raise SystemExit("the server closed its output")
            message = json.loads(line)
            if "id" in message:
                return message

    client = {"name": "bundleup-gauntlet", "version": "1"}
    params = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": client}
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
    print("server:", answer()["result"]["serverInfo"]["name"])
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    call = {"name": "add", "arguments": {"a": 2, "b": 3}}
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call})
    result = answer()["result"]
    text = result["content"][0]["text"]
    print("add(2, 3) =", text)
    server.stdin.close()
    server.wait(timeout=30)
    return 0 if text.strip() == "5" else 1


if __name__ == "__main__":
    raise SystemExit(main())
