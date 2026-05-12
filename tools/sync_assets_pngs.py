"""Re-embed toolbar PNGs from exe/actions into src/assets.py (maintainer one-off)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = ROOT / "exe" / "actions"
ASSETS = ROOT / "src" / "assets.py"

MAPPING = [
    ("kill_icon", "kill.png"),
    ("killall_icon", "killall.png"),
    ("scan_easy_icon", "scan_easy.png"),
    ("scan_hard_icon", "scan_hard.png"),
    ("settings_icon", "settings.png"),
    ("unkillall_icon", "unkillall.png"),
]


def main():
    lines = ASSETS.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        done = False
        for var, fname in MAPPING:
            if line.startswith(f"{var} = "):
                data = (ACTIONS / fname).read_bytes()
                nl = "\n" if line.endswith("\n") else ""
                out.append(f"{var} = {repr(data)}{nl}")
                print(f"{fname}: {len(data)} bytes")
                done = True
                break
        if not done:
            out.append(line)
    ASSETS.write_text("".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
