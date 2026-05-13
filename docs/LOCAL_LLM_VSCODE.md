# Using a local LLM in VS Code with the SysML v2 MCP server

This guide wires three things together:

1. A **local LLM runtime** (Ollama — easiest, runs Llama 3.x / Qwen / Mistral / etc. on CPU+GPU).
2. A **VS Code extension** that can talk to a local LLM *and* speak MCP.
3. The **SysML v2 MCP server** in this repo (`python -m mcp_server.server`).

Three viable extensions, ranked easiest → most flexible:

| Extension                | Local LLM | MCP support | Notes |
|--------------------------|-----------|-------------|-------|
| **Continue** (continue.dev) | ✅ | ✅ | Best chat + edit UX. Recommended. |
| **Cline**                | ✅ | ✅ | Agentic; rewrites files autonomously. |
| **GitHub Copilot Chat**  | ✅ (via `lm` API) | ✅ | Polished UI; needs Copilot license. |

---

## 1. Install Ollama and pull a model

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama pull llama3.1:8b-instruct-q4_K_M   # ~5 GB, fast on a laptop
# or, if you have 24+ GB VRAM:
ollama pull qwen2.5-coder:32b-instruct
ollama serve                              # exposes http://localhost:11434
```

Verify: `curl http://localhost:11434/api/tags`.

---

## 2A. Recommended path — Continue + Ollama + MCP

Install the **Continue** extension from the VS Code marketplace.

Open `~/.continue/config.json` (Continue creates it on first launch) and merge:

```jsonc
{
  "models": [
    {
      "title": "Llama 3.1 8B (local)",
      "provider": "ollama",
      "model": "llama3.1:8b-instruct-q4_K_M",
      "apiBase": "http://localhost:11434"
    }
  ],

  "experimental": {
    "modelContextProtocolServers": [
      {
        "name": "sysmlv2-core",
        "transport": {
          "type": "stdio",
          "command": "python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "/ABSOLUTE/PATH/TO/REQUIREMENT-FORMALISER",
          "env": { "PYTHONPATH": "/ABSOLUTE/PATH/TO/REQUIREMENT-FORMALISER" }
        }
      }
    ]
  }
}
```

Reload the window. In the Continue chat panel you'll now see your local
Llama 3.1 model **and** the 15 `sysml_*` tools. Try:

> Create a `PartDefinition` named `Vehicle` with a `mass` attribute, then validate.

---

## 2B. Alternative — Cline + Ollama + MCP

Install the **Cline** extension. Open its settings:

- **API Provider**: `Ollama`
- **Base URL**: `http://localhost:11434`
- **Model**: `llama3.1:8b-instruct-q4_K_M` (or a stronger coder model)

For MCP, click the *MCP Servers* icon in Cline's sidebar and edit
`~/Documents/Cline/MCP/cline_mcp_settings.json`:

```jsonc
{
  "mcpServers": {
    "sysmlv2-core": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/ABSOLUTE/PATH/TO/REQUIREMENT-FORMALISER",
      "env": { "PYTHONPATH": "/ABSOLUTE/PATH/TO/REQUIREMENT-FORMALISER" }
    }
  }
}
```

Reload. Cline will auto-discover the tools and use them in its agent loop.

---

## 2C. GitHub Copilot Chat (1.95+) — MCP + local model

Copilot Chat now supports MCP servers and "Bring Your Own Model" via
Ollama (preview).

- Settings → *GitHub Copilot › Chat › MCP: Enabled* → on.
- Add to your workspace `.vscode/mcp.json`:

```jsonc
{
  "servers": {
    "sysmlv2-core": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "${workspaceFolder}",
      "env": { "PYTHONPATH": "${workspaceFolder}" }
    }
  }
}
```

- Open the model picker in the chat panel → *Manage models* → add an
  Ollama endpoint (`http://localhost:11434`) and pick a pulled model.
- In Agent mode, the `sysml_*` tools become available to the chosen
  local model.

This file is the recommended one for this repo — it lives at
[.vscode/mcp.json](../.vscode/mcp.json) (bundled), so any Copilot
Chat / Continue / Cursor workspace that opens this folder picks the
server up automatically.

---

## 3. Sanity-check the server independently

```bash
# Run the MCP server directly and pipe a hand-crafted request:
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' \
  | python -m mcp_server.server | head
```

You should see two JSON-RPC responses — `serverInfo` then the 15-tool list.

---

## 4. Picking a model

For the modeling/code domain, smaller models often *don't* call tools
reliably. Recommended:

| GPU / RAM        | Model |
|------------------|-------|
| 8 GB unified RAM | `llama3.1:8b-instruct-q4_K_M` |
| 16 GB VRAM       | `qwen2.5-coder:14b-instruct` |
| 24 GB+ VRAM      | `qwen2.5-coder:32b-instruct` or `llama3.3:70b-instruct-q4_K_M` |

Tool-calling reliability is dramatically better on `qwen2.5-coder` and
`llama3.3` than on smaller models — worth the extra VRAM if you have it.
