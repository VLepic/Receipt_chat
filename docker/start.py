import os
import subprocess
import sys


def main() -> None:
    subprocess.run([sys.executable, "-m", "app.core.migrate_compat"], check=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    os.execv("/usr/bin/supervisord", ["supervisord", "-c", "/app/docker/supervisord.conf"])


if __name__ == "__main__":
    main()
