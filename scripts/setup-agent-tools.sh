#!/usr/bin/env bash
# Installs the agent-context tooling this repo's .mcp.json and
# .claude/skills/graphify/ expect: engram (memory), graphify (knowledge
# graph), headroom (tool-output compression). Safe to re-run.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

echo "==> graphify (knowledge graph)"
uv tool install --quiet graphifyy || uv tool upgrade graphifyy

echo "==> headroom (context compression, MCP-only — no proxy/wrap)"
# ponytail: [mcp] alone is missing fastapi upstream (packaging bug in headroom-ai);
# [proxy] pulls it in. Drop once headroom-ai fixes the mcp extra's deps.
uv tool install --quiet "headroom-ai[mcp,proxy]" || uv tool upgrade headroom-ai

echo "==> engram (persistent memory)"
if command -v engram >/dev/null 2>&1; then
  echo "    already installed: $(engram version 2>&1 || true)"
elif command -v brew >/dev/null 2>&1; then
  brew install gentleman-programming/tap/engram
else
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$arch" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "Unsupported arch: $arch — install manually: https://github.com/Gentleman-Programming/engram/releases" >&2; exit 1 ;;
  esac
  case "$os" in
    Linux) plat=linux ;;
    Darwin) plat=darwin ;;
    *) echo "Unsupported OS: $os — install manually: https://github.com/Gentleman-Programming/engram/releases" >&2; exit 1 ;;
  esac
  version="$(curl -fsSL https://api.github.com/repos/Gentleman-Programming/engram/releases/latest | grep -m1 '"tag_name"' | sed -E 's/.*"v?([^"]+)".*/\1/')"
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/Gentleman-Programming/engram/releases/download/v${version}/engram_${version}_${plat}_${arch}.tar.gz" -o "$tmp/engram.tar.gz"
  tar -xzf "$tmp/engram.tar.gz" -C "$tmp"
  mkdir -p "$HOME/.local/bin"
  mv "$tmp/engram" "$HOME/.local/bin/engram"
  chmod +x "$HOME/.local/bin/engram"
  rm -rf "$tmp"
  echo "    installed to ~/.local/bin/engram — make sure it's on your PATH"
fi

echo "==> registering graphify skill for this project"
graphify install --project

echo "==> building initial knowledge graph (code-only, no LLM key needed)"
graphify . --code-only
graphify cluster-only .

cat <<'EOF'

Done. Restart Claude Code (or reload MCP servers) to pick up .mcp.json.

Optional: set GEMINI_API_KEY / ANTHROPIC_API_KEY / etc. and re-run
`graphify . && graphify cluster-only .` to also index docs/papers with
semantic extraction (not required — code-only graph works without a key).
EOF
