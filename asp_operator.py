#!/usr/bin/env python3
"""Operator CLI: list agents and change their governance state with source=operator.

Operator decisions take precedence over self-reports and guardrails, and the
running agent enforces them in its PreToolUse hook within a couple of seconds.

Examples:
  python asp_operator.py list
  python asp_operator.py quarantine urn:agent:demo:supplier-desk --reason suspected-prompt-injection
  python asp_operator.py sandbox urn:agent:demo:supplier-desk
  python asp_operator.py release urn:agent:demo:supplier-desk
"""

import argparse
import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from asp_client import AspClient, unique_seq_start
from keychain import keychain_secret

ACTIONS = {
    "quarantine": "quarantined",
    "sandbox": "sandboxed",
    "review": "under-review",
    "release": "normal",
}


def list_agents(server, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(f"{server.rstrip('/')}/v1/agents", headers=headers), timeout=3) as response:
            agents = json.loads(response.read())
    except URLError as err:
        raise SystemExit(f"status server not reachable: {err.reason}")
    if not agents:
        print("no agents")
    for agent in agents:
        tasks = ", ".join(f"{k}={v}" for k, v in agent.get("tasks", {}).items()) or "-"
        print(f"{agent['agentId']}\n  lifecycle={agent['lifecycle']} health={agent['health']} "
              f"governance={agent['governance']} (by {agent['governanceSetBy']}) tasks: {tasks}")


def main():
    parser = argparse.ArgumentParser(description="ASP operator CLI")
    parser.add_argument("action", choices=["list", *ACTIONS])
    parser.add_argument("agent_id", nargs="?")
    parser.add_argument("--reason", default="operator-decision")
    parser.add_argument("--server", default=os.environ.get("ASP_SERVER", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    args.token = args.token or os.environ.get("ASP_TOKEN") or keychain_secret("asp-token")

    if args.action == "list":
        return list_agents(args.server, args.token)
    if not args.agent_id:
        parser.error("agent_id is required for this action")

    client = AspClient(args.server, args.agent_id, args.token, source="operator", seq_start=unique_seq_start())
    current = client.snapshot()
    if current is None:
        raise SystemExit(f"unknown agent or server not reachable: {args.agent_id}")
    status = client.state_change("governance", current["governance"], ACTIONS[args.action], args.reason)
    print(f"{args.agent_id}: governance {current['governance']} -> {ACTIONS[args.action]} (HTTP {status})")


if __name__ == "__main__":
    main()
