"""Локальный учебный сервис ОфисПро. Запуск: python3 trainer.py"""
import argparse
import base64
from getpass import getpass
import hmac
import json
import os
from pathlib import Path
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from model import DATA, HERE, ORDER, Problem, init_db, order, orders, save
from protocol import ACTIONS, SCHEMA, metadata, read

ROOT = "/unf_production/odata/standard.odata/"
ASSETS = {"": ("index.html", "text/html"), "app.js": ("app.js", "text/javascript"), "app.css": ("app.css", "text/css")}


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data, mime="application/json", extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        try:
            self.dispatch()
        except Problem as exc:
            extra = {"WWW-Authenticate": 'Basic realm="OfficePro"'} if exc.status == 401 else {}
            self.reply(exc.status, {"error": {"message": {"lang": "ru", "value": str(exc)}}}, extra=extra)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = handle_request

    def dispatch(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if self.command == "GET" and path[1:] in ASSETS:
            file, mime = ASSETS[path[1:]]
            return self.reply(200, (HERE / file).read_bytes(), mime)
        if path != ROOT.rstrip("/") and not path.startswith(ROOT):
            raise Problem("Проверьте путь к публикации.", 404)
        token = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(token, self.server.auth):
            raise Problem("Требуется верный логин и пароль учебного пользователя.", 401)
        resource = path[len(ROOT):].rstrip("/")
        if self.command == "POST":
            return self.create_order(resource)
        if not resource:
            return self.reply(200, {"value": [{"name": k, "url": k, "kind": "EntitySet"} for k in SCHEMA]})
        if resource == "$metadata":
            return self.reply(200, metadata(), "application/xml")
        if resource == "Training_Error500":
            raise Problem("Учебный сценарий. Производитель временно недоступен.", 500)
        parts = re.fullmatch(r"(\w+)(?:\(guid'([\da-fA-F-]{36})'\)|/(\w+)(?:\(\))?)?", resource)
        if not parts or parts[1] not in SCHEMA or (parts[3] and parts[3] != ACTIONS.get(parts[1])):
            raise Problem("Ресурс отсутствует в учебной публикации.", 404)
        name, key, _ = parts.groups()
        rows = orders(self.server.db) if name == ORDER else DATA[name]
        params = dict(parse_qsl(url.query, keep_blank_values=True))
        result = read(name, rows, params, ROOT + quote(resource), key.lower() if key else None)
        self.reply(200, result)

    def create_order(self, resource):
        if resource != ORDER:
            raise Problem("POST доступен для заказов покупателя.", 405)
        length = self.headers.get("Content-Length", "")
        if not length.isdecimal() or int(length) > 256000:
            raise Problem("Укажите размер JSON до 256 КБ.", 413)
        try:
            body = json.loads(self.rfile.read(int(length)).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise Problem("Тело запроса должно содержать JSON в UTF-8.")
        doc = order(body)
        save(self.server.db, doc)
        link = ROOT + quote(f"{ORDER}(guid'{doc['Ref_Key']}')")
        self.reply(201, doc, extra={"Location": link})


def main():
    parser = argparse.ArgumentParser(description="Тренажёр OData «ОфисПро»")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", type=Path, default=HERE / "orders.sqlite3")
    args = parser.parse_args()
    password = os.environ.get("OFFICEPRO_PASSWORD") or getpass("Задайте пароль для odata_user на этот запуск (ввод скрыт): ")
    if not password:
        sys.exit("Введите непустой учебный пароль.")
    try:
        http = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        sys.exit(f"Не удалось открыть порт {args.port}. Попробуйте --port 8081. {exc}")
    with http:
        init_db(args.db)
        http.db = args.db
        http.auth = b"Basic " + base64.b64encode(("odata_user:" + password).encode())
        print(f"Откройте http://127.0.0.1:{http.server_port}/  •  Остановка: Ctrl+C", flush=True)
        try:
            http.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
