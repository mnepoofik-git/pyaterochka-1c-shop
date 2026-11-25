"""Данные учебного производителя и правила создания заказа."""
import csv
import json
import math
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOODS = "Catalog_Номенклатура"
PARTNERS = "Catalog_Контрагенты"
KINDS = "Catalog_ВидыЦен"
STORES = "Catalog_СтруктурныеЕдиницы"
ORGS = "Catalog_Организации"
STATES = "Catalog_СостоянияЗаказовПокупателей"
ORDER = "Document_ЗаказПокупателя"
STOCK = "AccumulationRegister_Запасы"
PRICE = "InformationRegister_ЦеныНоменклатуры"
EMPTY = str(uuid.UUID(int=0))


def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:officepro:practicum2:" + name))


def entry(name, key):
    return {"Ref_Key": uid(key), "Description": name, "DeletionMark": False}


def catalog():
    names = {PARTNERS: ["ОфисПро Трейд"], STORES: ["Основной склад"],
             KINDS: ["Цена закупочная", "Цена розничная"], ORGS: ["ОфисПро Производство"],
             STATES: ["Не подтвержден", "Подтвержден", "В работе", "Выполнен", "Закрыт", "В производстве"]}
    data = {k: [entry(n, k + n) for n in ns] for k, ns in names.items()}
    goods, stock, prices = [], [], []
    folders = {}
    with (HERE / "catalog.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            path, parent = "", EMPTY
            for level in ("Группа", "Подгруппа", "Подподгруппа"):
                name = row[level]
                if not name:
                    continue
                path += "/" + name
                if path not in folders:
                    folder = dict(entry(name, path), Parent_Key=parent, IsFolder=True, Артикул="")
                    folders[path] = folder["Ref_Key"]
                    goods.append(folder)
                parent = folders[path]
            article = row["Артикул"]
            item = dict(entry(row["Наименование"], article), Parent_Key=parent, IsFolder=False, Артикул=article)
            goods.append(item)
            key = item["Ref_Key"]
            stock.append(dict(Номенклатура_Key=key, СтруктурнаяЕдиница_Key=data[STORES][0]["Ref_Key"],
                              КоличествоBalance=int(row["Остаток"])))
            for kind in data[KINDS]:
                column = kind["Description"]
                prices.append(dict(Номенклатура_Key=key, ВидЦен_Key=kind["Ref_Key"],
                                   Характеристика_Key=EMPTY, Цена=float(row[column])))
    data.update({GOODS: goods, STOCK: stock, PRICE: prices})
    return data


DATA = catalog()
PRODUCTS = {x["Ref_Key"]: x for x in DATA[GOODS] if not x["IsFolder"]}
BUYER = DATA[PARTNERS][0]
LINE_FIELDS = {"LineNumber": "Int32", "Номенклатура": "Guid", "Номенклатура_Type": "String",
               "Количество": "Decimal", "Цена": "Decimal", "Сумма": "Decimal", "Всего": "Decimal"}
ORDER_FIELDS = {"Ref_Key": "Guid", "Date": "DateTime", "Контрагент_Key": "Guid",
                "Комментарий": "String", "СуммаДокумента": "Decimal", "СостояниеЗаказа": "Guid",
                "СостояниеЗаказа_Type": "String", "Запасы": "Collection(StandardODATA.OrderLine)"}


class Problem(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def amount(value, label):
    if type(value) not in (float, int) or not 0 < value <= 10**9 or not math.isfinite(value):
        raise Problem("Проверьте поле «" + label + "». Требуется положительное число до 1 млрд.")
    return Decimal(str(value))


def order(body):
    if not isinstance(body, dict) or body.get("Контрагент_Key") != BUYER["Ref_Key"]:
        raise Problem("Укажите UID контрагента «ОфисПро Трейд» из этого сервиса.")
    date = body.get("Date")
    try:
        datetime.fromisoformat(date)
        key = str(uuid.UUID(body["Ref_Key"])) if "Ref_Key" in body else str(uuid.uuid4())
    except (AttributeError, TypeError, ValueError):
        raise Problem("Проверьте дату в формате ISO и Ref_Key заказа.")
    rows = body.get("Запасы")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise Problem("В заказе должно быть от 1 до 500 строк.")
    lines, total = [], Decimal(0)
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get("Номенклатура"), str) or row["Номенклатура"] not in PRODUCTS:
            raise Problem(f"Строка {number}. Укажите UID товара производителя.")
        if row.get("Номенклатура_Type", "StandardODATA." + GOODS) != "StandardODATA." + GOODS:
            raise Problem(f"Строка {number}. Проверьте тип номенклатуры.")
        qty, price = (amount(row.get(k), k) for k in ("Количество", "Цена"))
        subtotal = (qty * price).quantize(Decimal("0.01"))
        total += subtotal
        lines.append(dict(LineNumber=number, Номенклатура=row["Номенклатура"],
                          Номенклатура_Type="StandardODATA." + GOODS, Количество=float(qty),
                          Цена=float(price), Сумма=float(subtotal), Всего=float(subtotal)))
    return dict(Ref_Key=key, Date=date, Контрагент_Key=BUYER["Ref_Key"], Запасы=lines,
                Комментарий=str(body.get("Комментарий", "")), СуммаДокумента=float(total),
                СостояниеЗаказа=DATA[STATES][0]["Ref_Key"], СостояниеЗаказа_Type="StandardODATA." + STATES)


def init_db(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, body TEXT NOT NULL)")


def save(path, doc):
    with sqlite3.connect(path) as db:
        try:
            db.execute("INSERT INTO orders VALUES (?,?)", (doc["Ref_Key"], json.dumps(doc, ensure_ascii=False)))
        except sqlite3.IntegrityError:
            raise Problem("Заказ с таким Ref_Key уже есть. Прочитайте его по UID.", 409)


def orders(path):
    with sqlite3.connect(path) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM orders ORDER BY rowid")]


def change_state(path, key, state):
    known = {r["Description"]: r["Ref_Key"] for r in DATA[STATES]}
    if not isinstance(state, str) or state not in known:
        raise Problem("Выберите состояние из справочника производителя.")
    with sqlite3.connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        found = db.execute("SELECT body FROM orders WHERE id=?", (key,)).fetchone()
        if not found:
            raise Problem("В учебной базе нет заказа с таким UID.", 404)
        doc = json.loads(found[0])
        doc["СостояниеЗаказа"] = known[state]
        db.execute("UPDATE orders SET body=? WHERE id=?", (json.dumps(doc, ensure_ascii=False), key))
    return doc
