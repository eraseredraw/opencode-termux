# Gotchas: OpenCode + gateways on a phone

Every item below was reproduced, then fixed in configuration. Commands shown
assume you are inside the proot Ubuntu userland with the provider key exported.

## 1. A model fails with a generic 400 while its siblings work

**Symptom**

```text
AI_APICallError: Не удалось обработать параметры запроса.
Проверьте формат запроса и повторите попытку. (request id: ...)
```

Only `qwen3.7-flash` fails. `qwen3.7-plus` and `qwen3.7-max` in the same
provider work. An empty session with that model cannot even start, so the TUI
just shows the error and no output.

**Diagnosis**

Bypass OpenCode and hit the endpoint directly, one variable at a time:

```sh
# fails
curl -sS https://neuroapi.host/v1/chat/completions \
  -H "Authorization: Bearer $NEUROAPI_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.7-flash","messages":[{"role":"user","content":"say ok"}],"max_tokens":8}'

# works
curl -sS https://neuroapi.host/v1/chat/completions \
  -H "Authorization: Bearer $NEUROAPI_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.7-flash","messages":[{"role":"user","content":"say ok"}],"max_completion_tokens":8}'
```

The Alibaba-backed flash route only accepts `max_completion_tokens`. Any client
that sends `max_tokens` (the AI SDK `openai-compatible` package does) is
rejected before the model is even called, and the gateway reports it as a
malformed request rather than an unsupported parameter.

**Fix**

Per model, in native V2 config:

```jsonc
"qwen3.7-flash": {
  "compatibility": { "maxTokensField": "max_completion_tokens" }
}
```

OpenCode's own provider package already defaults to `max_completion_tokens`
except for providers known to need `max_tokens` (DeepSeek, Moonshot, Z.AI,
Together, Cerebras), so declaring the field explicitly is belt and braces for
custom gateways. If you are still on the legacy V1 `npm: "@ai-sdk/openai-compatible"`
form, this is the bug you will hit: the AI SDK always sends `max_tokens`.

## 2. `invalid_text_request` when tools are attached

**Symptom** the same model answers a plain prompt but 400s with
`invalid_text_request` once `tools` are present.

**Cause** the gateway validates tool parameter schemas strictly and rejects JSON
Schema union types:

```jsonc
{ "v": { "anyOf": [{ "type": "string" }, { "type": "integer" }] } }  // rejected
{ "v": { "type": "string" } }                                        // accepted
```

Many MCP servers publish exactly that shape from their Pydantic/Zod models.

**Fix** — pick one:

- run those MCP tools through OpenCode Code Mode, where nested schemas are not
  serialised into the request;
- replace the offending MCP server with one with flatter schemas;
- use a gateway whose route accepts unions.

Check before blaming the model:

```sh
curl -sS $BASE_URL/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"MODEL","max_completion_tokens":16,"messages":[{"role":"user","content":"hi"}],"tools":[{"type":"function","function":{"name":"x","description":"x","parameters":{"type":"object","properties":{"v":{"anyOf":[{"type":"string"},{"type":"integer"}]}}}}]}'
```

## 3. Provider answers 403 from one network, 200 from another

```text
{ "success": false, "error": "Access denied by security policy." }
```

OpenRouter blocks some mobile/VPN ASNs at the edge. Test both families and a
no-auth path so you know it is the network and not the key:

```sh
curl -4 -sSo /dev/null -w '%{http_code}\n' https://openrouter.ai/api/v1/models
curl -6 -sSo /dev/null -w '%{http_code}\n' https://openrouter.ai/api/v1/models
```

Keep the blocked provider configured as a fallback and point `model` at a
gateway that works today; switching networks then needs no config edit.

## 4. Free-tier ceilings on a phone

OpenRouter caps `:free` model requests per day on an unfunded account (this key
was limited to 20/day), and one long agent session can exhaust that before
lunch. The error is explicit:

```text
Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day
```

Different failure, same looking message family: `This request requires more
credits, or fewer max_tokens` means the balance cannot cover the *declared*
output budget. Lower `limit.output` for that model rather than adding money:
the gateway prices the worst case, not the actual completion.

## 5. MCP startup latency and stale credentials

`opencode mcp list` timing out, then connecting at 25-30 seconds, is `npx -y`
resolving packages over cellular at every launch. Install globally and call the
binaries (see README §5). Raise `mcp.timeout.catalog` above the default 5
seconds for the same reason.

The JSON memory server writes `memory.json` relative to the current directory
unless `MEMORY_FILE_PATH` is set. Without it, each project silently gets its
own memory store and the graph "loses" everything.

## 6. Home-directory workspace warnings

`fff`, the file picker used for fuzzy completion, refuses to index `/` or `$HOME`:

```text
failed to initialize fff: Failed to init file picker: Can not run certain FFF features
in a file system root or home directories. Consider smaller per-project directories.
```

Everything else still works, but `@` file completion is degraded. Run OpenCode
in `~/work/<project>` and keep `~/.config/opencode/AGENTS.md` for global
instructions.

## 7. models.dev timeouts

```text
Failed to fetch models.dev: Operation timed out after 10s
```

Cosmetic on slow DNS: the catalog from the last success is kept, and custom
providers declared in your config never depend on it. Fix the resolver (or wait
for a better signal) if the warning annoys you; do not chase it as a provider bug.

## 8. Sessions pinned to retired model ids

Gateways rename models continuously (`qwen3.6-flash` → gone in a month). Old
sessions keep their selection and then fail with `Model unavailable`. Re-select
in `/models`; re-running the sync script drops the dead ids from the catalog so
you cannot pick them again.

## 9. proot and file watching

PRoot does not deliver `inotify` events reliably, so config hot-reload can be
missed. After editing `opencode.json` and seeing no effect, confirm with:

```sh
opencode models | wc -l   # reflects providers in the file
```

and reload the TUI with `/reload` rather than assuming the watcher fired.
