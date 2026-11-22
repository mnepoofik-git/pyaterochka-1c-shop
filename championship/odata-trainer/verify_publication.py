"""Независимая сверка своей публикации УНФ или учебного производителя через GET."""
import argparse
import base64
from collections import Counter
from decimal import Decimal
from getpass import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from uuid import UUID
from xml.etree import ElementTree as ET

from model import GOODS, KINDS, PARTNERS, ORDER, PRICE, STOCK, STORES, STATES


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Endpoint:
    def __init__(self, url, user, password):
        parts = urlsplit(url)
        if (parts.scheme not in {"https","http"} or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError("Укажите корень OData без параметров и учётных данных в URL.")
        if parts.scheme == "http" and parts.hostname not in {"127.0.0.1","localhost","::1"}:
            raise ValueError("Для удалённого сервера укажите HTTPS. Локальный HTTP доступен через localhost.")
        self.root = url.rstrip("/") + "/"
        self.token = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.opener = build_opener(NoRedirect())

    def address(self, name, params=None):
        args = {"$format":"json", **(params or {})} if name != "$metadata" else {}
        return self.root + quote(name) + ("?" + urlencode(args) if args else "")

    def fetch(self, url, auth=True):
        if not url.startswith(self.root):
            raise ValueError("Ссылка на страницу вышла за пределы выбранной публикации.")
        req = Request(url, headers={"Authorization":self.token} if auth else {})
        with self.opener.open(req, timeout=10) as response:
            return response.read()

    def rows(self, name, **params):
        url = self.address(name, params)
        seen, rows = set(), []
        while url:
            if url in seen:
                raise ValueError("Публикация вернула повторную ссылку на страницу.")
            seen.add(url)
            doc = json.loads(self.fetch(url))
            page = doc["value"]
            if not isinstance(page, list):
                raise ValueError("Ожидался массив value.")
            rows.extend(page)
            more = doc.get("odata.nextLink") or doc.get("@odata.nextLink")
            url = urljoin(url, more) if more else None
        return rows


def require(test, message):
    if not test:
        raise ValueError(message)


def status(api, resource, expected, auth=True):
    try:
        api.fetch(api.address(resource), auth)
        code = 200
    except HTTPError as exc:
        code = exc.code
        exc.close()
    require(code == expected, f"получен HTTP {code}, ожидается {expected}")
    return f"HTTP {code}"


def check_metadata(api):
    meta = ET.fromstring(api.fetch(api.address("$metadata")))
    sets = {e.get("Name") for e in meta.findall(".//{*}EntitySet")}
    missing = {GOODS, PARTNERS, ORDER, PRICE, STOCK, KINDS, STATES, STORES} - sets
    require(not missing, "не опубликованы " + ", ".join(sorted(missing)))
    return "все восемь требуемых наборов присутствуют"


def check_catalog(api):
    fields = {"Ref_Key","Description","Артикул"}
    params = {"$filter":"IsFolder eq false and DeletionMark eq false","$select":",".join(sorted(fields))}
    rows = api.rows(GOODS, **params)
    require(bool(rows) and all({k for k in r if "odata." not in k} == fields for r in rows),
            "проверьте $select и наличие элементов каталога")
    require(len({r["Ref_Key"] for r in rows}) == len(rows),"повтор UID в выборке")
    up, down = (api.rows(GOODS, **dict(params, **{"$orderby":"Description "+direction})) for direction in ("asc","desc"))
    forward = [r["Description"] for r in up]
    require(len(set(forward)) > 1 and forward == [r["Description"] for r in reversed(down)]
            and Counter(r["Ref_Key"] for r in up) == Counter(r["Ref_Key"] for r in rows)
            and Counter(r["Ref_Key"] for r in down) == Counter(r["Ref_Key"] for r in rows),
            "сравните два порядка сортировки и полный состав выборок")
    return f"{len(rows)} товаров, поля и встречные сортировки сверены"


def check_group(api):
    all_rows = api.rows(GOODS, **{"$select":"Ref_Key,Description,Parent_Key,IsFolder"})
    folder = next((r for r in all_rows if r["IsFolder"] and r["Description"] == "Блокноты"), None)
    require(folder is not None, "папка «Блокноты» отсутствует")
    parent = folder["Ref_Key"]
    expected = Counter(r["Ref_Key"] for r in all_rows if r["Parent_Key"] == parent and not r["IsFolder"])
    result = api.rows(GOODS, **{"$filter":f"Parent_Key eq guid'{parent}' and IsFolder eq false"})
    require(expected and expected == Counter(r["Ref_Key"] for r in result),"выборка по Parent_Key расходится с деревом")
    return f"{len(result)} строк группы совпали с полным каталогом"


def check_register(api, path, field):
    rows = api.rows(path)
    require(rows and all("Номенклатура_Key" in r and field in r for r in rows), "пустой регистр или отсутствуют поля")
    detail = f"{len(rows)} строк"
    if path.startswith(STOCK):
        detail += ", сумма остатков " + str(sum(Decimal(str(r[field])) for r in rows))
    return detail


def check_order(api, key, fixture):
    doc = json.loads(api.fetch(api.address(f"{ORDER}(guid'{key}')", {"$expand":"Контрагент"})))
    require(doc["Ref_Key"].lower() == key and doc["Контрагент"]["Description"] == "ОфисПро Трейд",
            "проверьте UID и раскрытого покупателя")
    lines = doc.get("Запасы")
    require(isinstance(lines,list) and lines and all(Decimal(str(r["Количество"])) > 0 for r in lines),
            "проверьте табличную часть Запасы")
    if fixture:
        goods = api.rows(GOODS, **{"$filter":"IsFolder eq false", "$select":"Ref_Key,Артикул"})
        articles = {r["Ref_Key"]:r["Артикул"] for r in goods}
        actual = sorted((articles.get(r["Номенклатура"],""),Decimal(str(r["Количество"])),Decimal(str(r["Цена"]))) for r in lines)
        require(doc["Date"][:10] == "2027-01-15" and actual == [("УЧ-0001",2,83),("УЧ-0002",3,90)]
                and Decimal(str(doc["СуммаДокумента"])) == 436,"сверьте дату, артикулы, количества, цены и сумму задания Б")
    return f'{doc["Date"]} · {len(lines)} строк · сумма {doc["СуммаДокумента"]}'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8080/unf_production/odata/standard.odata/")
    p.add_argument("--user",default="odata_user")
    p.add_argument("--order",type=UUID,help="UID заказа, созданного из вашего клиента")
    p.add_argument("--exercise-order",action="store_true",help="сверить заказ по условиям упражнения Б")
    args = p.parse_args()
    if args.exercise_order and not args.order:
        p.error("--exercise-order требует --order с UID созданного заказа")
    api = Endpoint(args.url,args.user,os.environ.get("OFFICEPRO_PASSWORD") or getpass("Пароль учебного пользователя: "))
    checks = [
        ("Корень с учётными данными", lambda: status(api,"",200)),
        ("Корень без авторизации", lambda: status(api,"",401,False)),
        ("Состав публикации",lambda: check_metadata(api)),
        ("Несуществующий ресурс",lambda: status(api,"Catalog_НетТакого",404)),
        ("Товары, поля и сортировка",lambda:check_catalog(api)),
        ("Отбор по папке",lambda:check_group(api)),
        ("Остатки",lambda:check_register(api,STOCK+"/Balance","КоличествоBalance")),
        ("Цены",lambda:check_register(api,PRICE+"/SliceLast","Цена"))]
    if args.order:
        checks.append(("Заказ и $expand",lambda:check_order(api,str(args.order),args.exercise_order)))
    failed = 0
    for title, check in checks:
        try:
            print(f"OK · {title} · {check()}")
        except (OSError, URLError, ValueError, KeyError, TypeError, ET.ParseError, ArithmeticError) as exc:
            failed += 1
            print(f"ПРОВЕРЬТЕ · {title} · {exc}")
    if not args.order:
        print("Заказ пока не проверен. После POST из клиента запустите с --order UID.")
    return int(failed > 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyboardInterrupt) as exc:
        sys.exit(str(exc) or "Проверка прервана.")
