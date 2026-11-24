# OpenCode on Android — Termux + proot-distro (Ubuntu)

Run [OpenCode](https://opencode.ai) v2 as a daily coding agent on a phone: Termux
plus a `proot-distro` Ubuntu userland, any OpenAI-compatible provider, and a
small MCP set. Everything here is what actually works on aarch64 Android after
weeks of use, including the failure modes that cost the most time.

Tested on: Android 16 (OnePlus NE2213, kernel `6.17.0-PRoot-Distro`, aarch64),
Termux from F-Droid, proot-distro Ubuntu 26.04, OpenCode v2.4.1.

## 1. Base install

```sh
# In Termux (not proot)
pkg update
pkg install proot-distro termux-api
proot-distro install ubuntu
proot-distro login ubuntu
```

Inside the Ubuntu prompt:

```sh
apt-get update
apt-get install -y curl git ripgrep jq python3 python3-venv build-essential \
  fd-find bat delta entr
curl -fsSL https://opencode.ai/v2/install | bash
```

Debian/Ubuntu ship the last three under different binary names, and OpenCode looks
for the upstream ones, so symlink them once:

```sh
ln -sf /usr/bin/fdfind      /usr/local/bin/fd
ln -sf /usr/bin/batcat      /usr/local/bin/bat
ln -sf /usr/bin/singledelta /usr/local/bin/delta
```

Without `fd` and `ripgrep` on `PATH`, the agent falls back to slower traversal and
spends more tokens per search — the cheapest single improvement available on a phone.

Node.js comes from Termux itself (`pkg install nodejs`) and is on `PATH` inside
proot, which is convenient: `npx` and global npm packages work, while Ubuntu
glibc Python is used for anything with binary wheels. See
[docs/termux-vs-proot.md](docs/termux-vs-proot.md) for why that split matters.

## 2. Configure the agent in a project directory

`/root` is a home directory, and OpenCode's file picker refuses to index one:

```text
level=WARN message="failed to initialize fff" error="... in a file system root or home directories"
```

Work in a real project dir instead:

```sh
mkdir -p ~/work/myproject && cd ~/work/myproject
opencode
```

## 3. Providers without models.dev entries

OpenCode ships a catalog from [models.dev](https://models.dev). Regional
gateways are usually absent from it, so they must be declared as custom
providers. This example is a native V2 declaration for
[NeuroAPI](https://neuroapi.host) (Russian gateway, ruble billing, ~113 models):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "neuroapi/qwen3.8-flash",
  "providers": {
    "neuroapi": {
      "name": "NeuroAPI",
      "env": ["NEUROAPI_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "https://neuroapi.host/v1",
        "apiKey": "{env:NEUROAPI_API_KEY}",
        "chunkTimeout": false
      },
      "models": {
        "qwen3.7-flash": {
          "modelID": "qwen3.7-flash",
          "name": "Qwen 3.7 Flash",
          "capabilities": {
            "tools": true,
            "input": ["text", "image", "video"],
            "output": ["text"]
          },
          "limit": { "context": 1000000, "output": 64000 },
          "compatibility": { "maxTokensField": "max_completion_tokens" }
        }
      }
    }
  }
}
```

Full working config: [config/opencode.sample.json](config/opencode.sample.json).

Keep the key in the environment (`~/.bashrc`, `~/.profile`), never in the file —
`{env:VAR}` substitution is supported in `settings`.

## 4. Regenerate the model list for free

`GET /v1/models` returns display names, descriptions and token limits, and costs
no completion tokens. `scripts/neuroapi-sync.py` turns that response into the
native V2 `providers.neuroapi` block, marks image/video/TTS/embedding endpoints
as non-chat so they never appear in `/models`, and applies the request
compatibility flags the gateway needs:

```sh
export NEUROAPI_API_KEY=...
python3 scripts/neuroapi-sync.py --dry-run   # inspect
python3 scripts/neuroapi-sync.py             # rewrite opencode.json
```

Adapt the classifier and default limits at the top of the script for any other
OpenAI-compatible gateway.

## 5. Multi-model routing: pay for judgement, not for volume

A phone agent dies by a thousand steps, not by one expensive answer. The
coordinator runs every step of the session, so it must be cheap; specialists run
a bounded number of steps each, so they can afford to be strong. That split is
the whole idea — see [config/routing.sample.json](config/routing.sample.json).

```jsonc
{
  "model": "neuroapi/qwen3.7-flash",          // session default
  "small_model": "neuroapi/qwen3.7-flash",    // titles, summaries, compaction
  "subagent_depth": 2,                        // 1 (default) forbids nesting
  "agents": {
    "build":      { "model": "neuroapi/qwen3.8-omni-flash" },
    "worker":     { "model": "neuroapi/glm-5.3-flash",    "mode": "subagent", "steps": 15 },
    "coder":      { "model": "neuroapi/claude-sonnet-5-5","mode": "subagent", "steps": 4  },
    "architect":  { "model": "neuroapi/gemini-3.8-flash", "mode": "subagent", "steps": 4,
                    "permissions": [{ "action": "edit", "resource": "*", "effect": "deny" }] },
    "explore":    { "model": "neuroapi/qwen3.7-flash",    "steps": 6,
                    "permissions": [{ "action": "edit", "resource": "*", "effect": "deny" },
                                    { "action": "shell", "resource": "*", "effect": "deny" }] }
  }
}
```

Three things matter more than which models you pick:

- **`steps` is the real budget.** A subagent starts with a clean, short context,
  so a frontier model at 4 steps costs less than a cheap one left to wander for 40.
  Cap every specialist.
- **`compaction.keep.tokens` decides your rate tier.** Many gateways multiply the
  input price once a request crosses a context threshold (3× past 32K tokens on
  NeuroAPI, 6× past 256K). Agent sessions cross it immediately: system prompt plus
  tool schemas plus history. Keeping requests under the threshold saves more than
  switching models does.
- **Fill in `cost` per model.** It drives the picker, the stats, and the ceiling
  plugin below. Gateways that bill in a non-USD currency will not appear in
  models.dev, so compute the array yourself from the gateway's published ratios —
  including its tier multipliers, which are published explicitly and need no guessing.

## 6. Plugins: the runtime is newer than its own typings

OpenCode v2 plugins can enforce a hard price ceiling across *every* provider,
including ones you never declared by hand. On this phone the ceiling plugin
disabled 34 over-priced models in two providers it knew nothing about — coverage
that hand-editing the config had missed.

The trap: `@opencode-ai/plugin` ships `.d.ts` for a different version than the
server runs. The bundled typings describe 9 context domains; the v2.4.1 server
actually provides 26, including `model`, `session`, `tool`, `permission` and
`generate`, while omitting `catalog` that the typings promise. Writing a plugin
from the typings produces code that crashes the server on load.

So probe first, and never let a plugin throw:

```ts
import { writeFileSync } from "node:fs"
export default {
  id: "ctx-probe",
  async setup(ctx: unknown) {
    const c = ctx as Record<string, unknown>
    const domains: Record<string, string[]> = {}
    for (const k of Object.keys(c ?? {})) {
      const v = c[k]
      domains[k] = v && typeof v === "object" ? Object.keys(v as object) : [`<${typeof v}>`]
    }
    writeFileSync("/tmp/opencode/ctx-probe.json",
      JSON.stringify({ at: new Date().toISOString(), keys: Object.keys(c ?? {}), domains }, null, 2))
  },
}
```

`opencode reload`, then read the file. Plugin `console.log` does **not** reach
`opencode.log`, which is why the probe writes a file — and why an uncaught error
inside a transform looks like a silent server restart instead of a failure.

Full working ceiling plugin, the three ways to crash the server from a plugin, and
what the extra domains unlock (per-request model swaps, output-token caps, custom
compaction, pre-flight cost estimation): [docs/plugins.md](docs/plugins.md).

## 7. MCP servers: install them, do not `npx -y` them

`npx -y pkg` re-resolves the package on every start. On a phone that showed up
as 25-30 seconds before `opencode mcp list` reported `connected`. Install once,
call the binaries:

```sh
npm i -g @modelcontextprotocol/server-memory @mokei/mcp-fetch
```

```jsonc
{
  "mcp": {
    "timeout": { "catalog": 60000, "execution": 120000 },
    "servers": {
      "memory": {
        "type": "local",
        "command": ["mcp-server-memory"],
        "environment": { "MEMORY_FILE_PATH": "~/.local/share/opencode/memory.json" }
      },
      "fetch": { "type": "local", "command": ["mcp-fetch"] }
    }
  }
}
```

Two notes that save real time:

- `MEMORY_FILE_PATH` must be set, otherwise the graph is written to `memory.json`
  in whatever directory OpenCode happened to start in.
- `sequential-thinking` is not worth it: OpenCode reasons natively, and the MCP
  wrapper only burns context and startup time. Prefer `"disabled": true`.

Keep the total at two or three local servers. Each one is a Node process with
its own tool catalog in every request; on a phone in proot that is RAM, CPU and
tokens at once.

## 8. Gotchas

See [docs/gotchas.md](docs/gotchas.md). The short list:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `400 Не удалось обработать параметры запроса` on Qwen 3.7 Flash only | endpoint rejects `max_tokens` | `compatibility.maxTokensField: "max_completion_tokens"` |
| `400 invalid_text_request` with tools | gateway rejects `anyOf`/union JSON-schema types | keep one type per tool property |
| `403 Access denied by security policy` from OpenRouter | network-level block | route to another provider, keep it as fallback |
| `Rate limit exceeded: free-models-per-day` | OpenRouter free tier is 20 req/day on a fresh key | paid credits, or a paid gateway |
| `Operation timed out after 10s` fetching models.dev | slow mobile DNS | harmless, catalog stays cached |
| Sessions pinned to a deleted model fail with `Model unavailable` | the gateway retired that model id | re-select in `/models` |

## 9. Battery and network reality check

- Termux kills background jobs when the screen is off unless you acquire a wake
  lock (`termux-wake-lock`) or run the session under `tmux`.
- Long streaming responses over cellular die on idle TCP; keep
  `chunkTimeout: false` or set it generously, and expect to retry.
- Compaction matters more than on a desktop: a 1M-context default with a small
  `compaction.keep.tokens` budget keeps sessions cheap.

## License

MIT.
