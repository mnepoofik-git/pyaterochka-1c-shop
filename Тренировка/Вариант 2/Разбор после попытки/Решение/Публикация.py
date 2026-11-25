"""Локальная HTTP-публикация учебной базы производителя на платформе 1С 8.5."""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", type=Path, help="Каталог ibcmd и ibsrv")
    parser.add_argument("database", type=Path, help="Каталог базы с файлом 1Cv8.1CD")
    args = parser.parse_args()
    database = args.database.resolve()
    if not (database / "1Cv8.1CD").is_file():
        parser.error("В указанном каталоге нет файла 1Cv8.1CD")
    suffix = ".exe" if os.name == "nt" else ""
    control = args.platform.resolve() / ("ibcmd" + suffix)
    server = args.platform.resolve() / ("ibsrv" + suffix)
    if not control.is_file() or not server.is_file():
        parser.error("Укажите каталог установленной платформы с ibcmd и ibsrv")
    with tempfile.TemporaryDirectory(prefix="officepro-odata-") as temporary:
        config = Path(temporary) / "server.yml"
        subprocess.run([str(control), "server", "config", "init",
                        "--address=127.0.0.1", "--port=8080",
                        "--http-base=/unf_production", "--db-path=" + str(database),
                        "--out=" + str(config)], check=True)
        with config.open("a", encoding="utf-8") as stream:
            stream.write("\n  odata:\n    publish: true\n")
        print("OData → http://localhost:8080/unf_production/odata/standard.odata/", flush=True)
        process = subprocess.Popen([str(server), "--config=" + str(config),
                                    "--data=" + temporary, "--disable-ssh", "--disable-direct"])
        try:
            return process.wait()
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
            return process.wait()

if __name__ == "__main__":
    raise SystemExit(main())
