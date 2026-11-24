# OpenCode на телефоне (Android) — инструкция для чайников

Ставим полноценный ИИ-агент для кода (OpenCode) прямо на Android.
Ничего installs не удаляй, просто копируй блоки по очереди и вставляй в Termux
(долгий тап → Paste, Enter).

Время: ~15 минут. Нужно: Wi-Fi, ~1,5 ГБ свободного места.

---

## Шаг 1. Termux (не из Google Play!)

Версия из Google Play древняя и сломанная. Скачай с F-Droid:

1. Открой <https://f-droid.org> → кнопка **Download F-Droid** → разреши
   «установка из неизвестных источников» → установи приложение F-Droid.
2. В F-Droid найди **Termux** → Install.

(Если F-Droid бесит — можно просто скачать APK:
<https://f-droid.org/repo/com.termux_1001.apk>, но через магазин обновления сами придут.)

## Шаг 2. Базовые пакеты

Открой Termux, вставь, дождись конца (первый блок — надолго, минуты 3):

```sh
termux-change-repo
```

(выбери любой зеркало из списка — кнопка OK; если не спрашивает, пропусти)

```sh
pkg update -y && pkg upgrade -y
pkg install -y proot-distro curl git nano
```

## Шаг 3. Ubuntu внутри Termux

```sh
proot-distro install ubuntu
proot-distro login ubuntu
```

После второй команды подсказка изменится (корень `root@localhost`).
Ты внутри Ubuntu. Дальше — тоже копипаст:

```sh
apt update && apt install -y curl git ca-certificates
```

## Шаг 4. OpenCode

```sh
curl -fsSL https://opencode.ai/v2/install | bash
```

Дописать PATH (иначе команда не найдётся при новом входе):

```sh
echo 'export PATH="$HOME/.opencode/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Проверка — должна показать версию:

```sh
opencode --version
```

## Шаг 5. Ключ к нейросети

Нужен API-ключ NeuroAPI (там есть бесплатные модели):

1. Зайди на <https://neuroapi.host>, зарегистрируйся, создай ключ
   (длинная строка `sk-...`).
2. Сохрани в файл, чтобы не вводить каждый раз:

```sh
mkdir -p ~/.config/opencode
nano ~/.config/opencode/key.txt
# вставь ключ, Ctrl+O → Enter (сохранить), Ctrl+X (выйти)
```

Если ключ уже есть у тебя (парня) — он пришлёт строку, просто вставь её в тот же файл.

## Шаг 6. Конфиг

Один блок, целиком в Termux:

```sh
cat > ~/.config/opencode/opencode.json <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "neuroapi/qwen3.8-flash",
  "update": "notify",
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
          "capabilities": { "tools": true, "input": ["text", "image"], "output": ["text"] },
          "limit": { "context": 262144, "output": 64000 },
          "compatibility": { "maxTokensField": "max_completion_tokens" }
        },
        "qwen3.8-flash": {
          "modelID": "qwen3.8-flash",
          "name": "Qwen 3.8 Flash",
          "capabilities": { "tools": true, "input": ["text", "image"], "output": ["text"] },
          "limit": { "context": 262144, "output": 64000 },
          "compatibility": { "maxTokensField": "max_completion_tokens" }
        }
      }
    }
  }
}
EOF
echo 'export NEUROAPI_API_KEY="$(cat ~/.config/opencode/key.txt)"' >> ~/.bashrc
source ~/.bashrc
```

## Шаг 7. Поехали

```sh
mkdir -p ~/project && cd ~/project
opencode
```

Появится интерфейс. Пиши вопросы как в чате — он читает/создаёт файлы в
`~/project`. Пример: «создай страничку-визитку index.html с котиком».

## Каждый день потом

```sh
proot-distro login ubuntu
cd ~/project
opencode
```

Можно добавить алиас в конце `~/.bashrc`, чтобы одной командой:

```sh
alias oc='cd ~/project && opencode'
```

---

## Важные мелочи

- **Не убивай Termux свайпом «закрыть все»** — агент умрётся посреди работы.
- Перед долгой задачей выполни (в Termux, не в Ubuntu):
  ```sh
  termux-wake-lock
  ```
  не мешает, если телефон уснёт во время работы.
- Настройки Android → Батарея → Termux → «Без ограничений» (иначе Android
  будет резать сеть во сне).
- Файлы проекта лежат внутри Ubuntu, чтобы скинуть их в обычную папку
  «Загрузки»: в Termux выполни `termux-setup-storage` (разрешит доступ),
  дальше `~/storage/shared/Download/`.

## Если что-то не так

| Симптом | Лечение |
| --- | --- |
| `opencode: command not found` | `source ~/.bashrc` или перезайди; проверь `ls ~/.opencode/bin` |
| Ошибки сети / `401` | ключ в `key.txt` без пробелов и кавычек; пересоздай ключ на neuroapi.host |
| `403 Access denied` у провайдера | сеть блокирует домен — попробуй другой Wi-Fi / мобильный интернет |
| Модель отвечает ошибкой параметров | в конфиге у модели должен стоять `"maxTokensField": "max_completion_tokens"` (см. шаг 6) |
| Всё упало / закончился смысл | `proot-distro remove ubuntu` и начать с шага 3 (конфиг и ключ останутся) |
| Мало места | Ubuntu жрёт ~1 ГБ: `pkg clean`, в Ubuntu `apt clean` |

## Честно про телефон

Это не замена компьютера: экран маленький, тяжёлые сборки греют батарею,
а при глубоком сне телефона сеть может отвалиться (долгая задача не доделается).
Идеальный сценарий: смотреть/править небольшие вещи в дороге. За длинными
задачами — на комп.
