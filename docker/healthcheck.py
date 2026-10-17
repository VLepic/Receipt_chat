import json
import subprocess
from urllib.request import urlopen


def main() -> int:
    try:
        result = subprocess.run(
            ["/usr/bin/supervisorctl", "-c", "/app/docker/supervisord.conf", "status"],
            capture_output=True, text=True, timeout=4,
        )
        states = {parts[0]: parts[1] for line in result.stdout.splitlines() if len(parts := line.split()) >= 2}
        if result.returncode or any(states.get(name) != "RUNNING" for name in ("backend", "ocr-worker", "nginx")):
            return 1
        with urlopen("http://127.0.0.1:8080/api/health", timeout=4) as response:
            return 0 if json.load(response).get("status") == "ok" else 1
    except (OSError, ValueError, subprocess.SubprocessError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
