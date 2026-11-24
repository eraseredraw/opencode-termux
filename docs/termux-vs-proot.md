# Termux binary prefix vs proot Ubuntu userland

Two Linux-flavoured `PATH`s share one shell, which confuses package choices:

```text
PATH=/root/.opencode/bin:/usr/local/sbin:...:/sbin:/bin:/data/data/com.termux/files/usr/bin
```

Termux's prefix is appended *last* here, but on a default `proot-distro login`
session `/data/data/com.termux/files/usr/bin` is often inherited and can shadow
Ubuntu's `/usr/bin`. Verify which runtime answers before installing anything:

```sh
command -v node npx python3 pip3 rg jq
python3 -V; /usr/bin/python3 -V 2>/dev/null
```

## Why the split matters

| Need | Use | Because |
| --- | --- | --- |
| Node runtime, `npx`, global npm bins, OpenCode MCP servers | Termux (`pkg install nodejs`) | works unchanged inside proot, no glibc surprises |
| Anything with binary wheels: `chromadb`, `numpy`, `tokenizers`, ONNX | Ubuntu (`apt install python3 python3-venv`) | Termux ships an Android/bionic Python; manylinux `aarch64` wheels are glibc-only and fail to install or to import |
| Native builds (`rg`, `jq`, `openssl`, `git`) | Ubuntu (`apt-get install ...`) | matches the distro OpenCode assumes, and `apt` tracks security updates |
| Android hardware access: clipboard, notification, battery, camera, SMS, telephony, location | Termux `termux-api` | proot cannot reach Android APIs by itself; Termux is the bridge |

So the practical rule: `apt` for the userland, `pkg` for the phone, and one
`python3 -m venv` per Python project — never `pip install` into Termux's system
Python.

```sh
# Termux side
pkg install termux-api nodejs git
# Ubuntu side
apt-get install -y python3 python3-venv python3-pip build-essential ripgrep jq
python3 -m venv ~/.venv/app && ~/.venv/app/bin/pip install mempalace
```

`pip` refuses a globally managed interpreter (`externally-managed-environment`).
In a venv that goes away and wheels land in a path you can delete.

## Android storage from inside proot

`proot-distro` mounts the shared storage somewhere under the Android tree; the
location differs by device, so probe rather than assume:

```sh
for p in /mnt/sdcard /sdcard /storage/emulated/0; do
  [ -d "$p/Download" ] && echo "$p works" && ls "$p/Download" | head -3
done
```

Use it for one-off imports and exports only. Keep the agent's real state —
sessions, SQLite catalog, memory files — under `$HOME`, which lives inside the
Ubuntu rootfs and is backed up as a whole:

```sh
proot-distro backup ubuntu --output ~/ubuntu-backup.tar.gz
```

## Wake lock and long sessions

Termux suspends when the screen is off, killing streaming responses mid-turn:

```sh
termux-wake-lock                    # keep the device awake
tmux new -s oc -d 'cd ~/work/app && opencode'   # survive detach/reattach
```

`termux-wake-lock` is a Termux binary, so run it in the Termux layer, not in
the Ubuntu session — that is the usual reason a "wake lock had no effect" bug is
filed.
