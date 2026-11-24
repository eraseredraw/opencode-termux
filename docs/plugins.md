# Плагины OpenCode на Termux: как не выстрелить себе в ногу

Практический вывод из настройки мульти-модельного роутинга. Всё проверено на
живом сервере OpenCode **2.4.1** в proot Ubuntu; команды и имена доменов
соответствуют именно этой версии.

## Главная ловушка: typings ≠ рантайм

`@opencode-ai/plugin` кладёт рядом с бинарем `.d.ts` файлы. Они описывают **другую**
версию, чем реально отдаёт сервер. На этом устройстве:

| источник | домены `PluginContext` |
| --- | --- |
| typings пакета 1.18.31 | `options, agent, aisdk, catalog, command, integration, plugin, reference, skill` (9) |
| сервер 2.4.1 (зонд) | `app, location, options, agent, aisdk, command, credential, event, experimental, generate, model, provider, integration, mcp, permission, plugin, reference, rpc, skill, storage, tool, vcs, websearch, worktree, session, shell` (26) |

Сервер новее typings: `catalog`, которого нет в `.d.ts`, в рантайме **отсутствует**,
зато есть `model`, `session`, `tool`, `permission`, `storage`, `generate`.

Документация opencode.ai описывает третий, тоже не совпадающий набор. Порядок
доверия: **зонд живого контекста → доки → typings**. Никогда не пиши плагин по
одному только `.d.ts`.

## Зонд: как узнать, что реально есть

`console.log` из плагина в `opencode.log` не попадает. Единственный надёжный канал —
файл. Положи `~/.config/opencode/plugins/ctx-probe/server.ts`:

```ts
import { writeFileSync } from "node:fs"

export default {
  id: "ctx-probe",
  async setup(ctx: unknown) {
    try {
      const c = ctx as Record<string, unknown>
      const domains: Record<string, string[]> = {}
      for (const key of Object.keys(c ?? {})) {
        const value = c[key]
        domains[key] = value && typeof value === "object"
          ? Object.keys(value as Record<string, unknown>)
          : [`<${typeof value}>`]
      }
      writeFileSync("/tmp/opencode/ctx-probe.json",
        JSON.stringify({ at: new Date().toISOString(), keys: Object.keys(c ?? {}), domains }, null, 2))
    } catch (error) {
      try { writeFileSync("/tmp/opencode/ctx-probe-error.txt", String(error)) } catch {}
    }
  },
}
```

```sh
opencode reload && sleep 3 && jq '.domains' /tmp/opencode/ctx-probe.json
```

Делай это после каждого апгрейда OpenCode — API плагинов ещё движется.

## Три способа убить сервер плагином

1. **Необработанный `throw` из transform.** Ошибка оборачивается в `Die(...)`,
   сервер пишет `disabled plugin after transform failure` и **перезапускается**.
   Признак: обрываются собственные shell-команды в активной сессии.
2. **Доступ к отсутствующему домену.** `ctx.catalog.transform` при отсутствии
   `catalog` → `TypeError: undefined is not an object` → пункт 1.
3. **Запись в readonly.** Объекты моделей в draft заморожены:
   `model.enabled = false` → `TypeError: Attempted to assign to readonly property`.
   Только мутаторы редактора: `editor.update(providerID, id, draft => { draft.enabled = false })`.

Правило: **весь `setup` внутри `try/catch`**, любой transform тоже. Плагин не имеет
права уронить хост.

## Рабочий пример: потолок цен

`~/.config/opencode/plugins/budget-guard/server.ts` — отключает модели дороже
порога, чтобы в них не мог провалиться ни один агент, ни случайный выбор в `/models`.

Ключевые моменты реализации:

```ts
import { define } from "@opencode-ai/plugin/v2/promise"
import { appendFileSync } from "node:fs"

const LOG = "/tmp/opencode/budget-guard.log"
function log(line: string) { try { appendFileSync(LOG, `${new Date().toISOString()} ${line}\n`) } catch {} }

export default define({
  id: "budget-guard",
  async setup(ctx: any) {
    const o = (ctx?.options ?? {}) as Record<string, unknown>
    const maxIn = typeof o.maxInputUsd === "number" ? o.maxInputUsd : 4
    const maxOut = typeof o.maxOutputUsd === "number" ? o.maxOutputUsd : 20
    const allow = new Set(Array.isArray(o.allow) ? o.allow.filter((x): x is string => typeof x === "string") : [])

    // Живой 2.4.1 даёт ctx.model; другие сборки — ctx.catalog. Бери то, что есть.
    const domain = ctx?.model?.transform ? ctx.model : ctx?.catalog?.transform ? ctx.catalog : null
    if (!domain) { log(`inactive: domains=${Object.keys(ctx ?? {}).join(",")}`); return }

    try {
      await domain.transform((editor: any) => {
        const models: any[] = typeof editor?.list === "function" ? [...(editor.list() ?? [])] : []
        if (!models.length && editor?.provider?.list) {
          for (const rec of editor.provider.list() ?? [])
            for (const m of rec?.models?.values ? rec.models.values() : []) models.push(m)
        }
        let off = 0
        for (const model of models) {
          const { id, providerID, cost } = model
          if (typeof id !== "string" || typeof providerID !== "string" || allow.has(id)) continue
          // Цена неизвестна — не караем вслепую, иначе скроем исправные модели.
          const list = Array.isArray(cost) ? cost : cost ? [cost] : []
          const worstIn = Math.max(0, ...list.map((c: any) => c?.input ?? 0))
          const worstOut = Math.max(0, ...list.map((c: any) => c?.output ?? 0))
          if (!worstIn && !worstOut) continue
          if (worstIn <= maxIn && worstOut <= maxOut) continue
          if (typeof editor?.update === "function" && model.enabled !== false) {
            editor.update(providerID, id, (d: any) => { d.enabled = false })
            off += 1
          }
        }
        log(`disabled ${off}/${models.length} models over in=$${maxIn}/out=$${maxOut}`)
      })
    } catch (error) { log(`error: ${String(error)}`) }
  },
})
```

Подключение и пороги:

```jsonc
{
  "plugins": [{
    "package": "./plugins/budget-guard",
    "options": {
      "maxInputUsd": 4.0,
      "maxOutputUsd": 20.0,
      "mode": "disable",
      "allow": ["neuroapi-модели-твоего-роутинга"]
    }
  }]
}
```

`allow` обязателен: whitelist тех моделей, на которые разложен роутинг, иначе
потолок отрежет собственного координатора.

Проверка, что сработало:

```sh
cat /tmp/opencode/budget-guard.log | tail -1
opencode api model.list | jq '[.data[] | select(.enabled)] | length'
```

## Что даёт заполненный `cost`

Потолок работает только если у модели известны цены. В блоке провайдера `cost`
принимает **массив тиров** — это ловит надбавку за длинный контекст, которая и есть
главная статья расхода агентных сессий:

```jsonc
"cost": [
  { "input": 0.061, "output": 0.264, "cache": { "read": 0.012, "write": 0 } },
  { "tier": { "type": "context", "size": 32000 },  "input": 0.203, "output": 0.814 },
  { "tier": { "type": "context", "size": 256000 }, "input": 0.407, "output": 1.627 }
]
```

Цены — **USD за 1M токенов**. Для шлюза с собственной валютой пересчитывай по
курсу и заполняй из каталога цен шлюза скриптом, а не руками: множители тиров
там публикуются явно (`token_pricing_tiers`), угадывать не нужно.

## Пути и загрузка

- Плагин без `package.json`: каталог с файлом `server.ts` (или `index.ts`) на корню.
- `"./plugins/x"` в конфиге разрешается **относительно каталога конфига**
  (`/root/.config/opencode/plugins/x`), не `~/.opencode/plugins/x`. Ошибка пути
  даёт `ENOENT ... stat '<path>'` в логе и тихую незагрузку.
- `opencode plugin list`, `opencode reload` — управление и проверка.
- Диагностика падений: `grep -iE 'failed to load plugin|after transform failure' ~/.local/share/opencode/log/opencode.log`.

## Что ещё открывается через живые домены (не проверено в бою, но API есть)

- `session.hook("experimental.model.resolve")` — подмена модели на запрос, `kind`
  различает primary/compaction/title. Настоящий динамический роутер «эскалировать
  сложное».
- `session.hook("context")` — `event.options.maxTokens`, `delete event.tools.write`
  до отправки: потолок вывода и read-only шаги.
- `session.hook("compaction")` — свой суммаризатор вместо модельного вызова.
- `generate.text({model, prompt})` — генерация без сессии и истории; возвращает
  `tokens` и `cost`, т.е. оценка стоимости задачи ДО её запуска.
- `tool.transform` / `permission.hook` — свои инструменты и гейтинг.
