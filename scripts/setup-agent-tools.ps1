#!/usr/bin/env pwsh
# Windows/PowerShell counterpart to setup-agent-tools.sh.
# Installs the agent-context tooling this repo's .mcp.json and
# .claude/skills/graphify/ expect: engram (memory), graphify (knowledge
# graph), headroom (tool-output compression). Safe to re-run.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

Write-Host "==> graphify (knowledge graph)"
uv tool install --quiet graphifyy
if ($LASTEXITCODE -ne 0) { uv tool upgrade graphifyy }

Write-Host "==> headroom (context compression, MCP-only -- no proxy/wrap)"
# ponytail: [mcp] alone is missing fastapi upstream (packaging bug in headroom-ai);
# [proxy] pulls it in. Drop once headroom-ai fixes the mcp extra's deps.
uv tool install --quiet "headroom-ai[mcp,proxy]"
if ($LASTEXITCODE -ne 0) { uv tool upgrade headroom-ai }

Write-Host "==> engram (persistent memory)"
$engram = Get-Command engram -ErrorAction SilentlyContinue
if ($engram) {
    Write-Host "    already installed: $(engram version 2>&1)"
} else {
    $arch = if ([System.Environment]::Is64BitOperatingSystem -and $env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/Gentleman-Programming/engram/releases/latest"
    $version = $release.tag_name.TrimStart("v")
    $assetName = "engram_${version}_windows_${arch}.zip"
    $asset = $release.assets | Where-Object { $_.name -eq $assetName }
    if (-not $asset) {
        Write-Error "Could not find $assetName in latest release. Install manually: https://github.com/Gentleman-Programming/engram/releases"
        exit 1
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zipPath = Join-Path $tmp "engram.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $tmp -Force

    $binDir = Join-Path $env:USERPROFILE ".local\bin"
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    Move-Item -Path (Join-Path $tmp "engram.exe") -Destination (Join-Path $binDir "engram.exe") -Force
    Remove-Item -Recurse -Force $tmp

    Write-Host "    installed to $binDir\engram.exe"
    if ($env:PATH -notlike "*$binDir*") {
        Write-Host "    add $binDir to your PATH (same dir uv tool uses for shims)"
    }
}

Write-Host "==> registering graphify skill for this project"
graphify install --project

Write-Host "==> building initial knowledge graph (code-only, no LLM key needed)"
graphify . --code-only
graphify cluster-only .

Write-Host ""
Write-Host "Done. Restart Claude Code (or reload MCP servers) to pick up .mcp.json."
Write-Host ""
Write-Host "Optional: set GEMINI_API_KEY / ANTHROPIC_API_KEY / etc. and re-run"
Write-Host "``graphify . && graphify cluster-only .`` to also index docs/papers with"
Write-Host "semantic extraction (not required -- code-only graph works without a key)."
