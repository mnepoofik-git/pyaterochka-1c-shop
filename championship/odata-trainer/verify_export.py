"""Сверка выгрузки из своей базы с домашним Excel и предыдущей попыткой импорта."""
import argparse
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from uuid import UUID

from model import HERE

TRADE_STOCK = {"УЧ-0101":120, "УЧ-0102":85, "УЧ-0001":10, "УЧ-0002":45,
               "УЧ-0201":200, "УЧ-0301":5, "УЧ-0331":150, "УЧ-0061":0}


def load(path, required):
    with path.open(encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        delim = max([",",";","\t"], key=first.count)
        f.seek(0)
        reader = csv.DictReader(f,delimiter=delim)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Отсутствуют колонки: " + ", ".join(sorted(missing)))
        result = {}
        for n,row in enumerate(reader,2):
            article = row["Артикул"]
            if not article or article in result:
                raise ValueError(f"Строка {n}: пустой или повторный артикул {article!r}")
            result[article] = row
        return result


def number(value):
    return Decimal(str(value).replace(" ","").replace("\xa0","").replace(",", "."))


def run(args):
    common = ["Артикул","Наименование","Остаток","Цена закупочная"]
    if args.mode == "trade":
        extra = ["UID производителя","UID локальный","Наш остаток"]
    else:
        extra = ["Цена розничная","Группа","Подгруппа","Подподгруппа"]
    rows = load(args.file,common+extra)
    reference = load(HERE/"catalog.csv",common)
    prior = load(args.previous,["Артикул","UID производителя","UID локальный"]) if args.previous else None
    errors = []
    if rows.keys() != reference.keys():
        errors.append("Проверьте состав артикулов. Пропущено %d, лишних %d." %
                      (len(reference.keys()-rows.keys()),len(rows.keys()-reference.keys())))
    if prior is not None and rows.keys() != prior.keys():
        errors.append("Состав артикулов изменился между двумя выгрузками.")
    seen = {"UID производителя":set(),"UID локальный":set()}
    for article in sorted(reference.keys() & rows.keys()):
        row, ref = rows[article], reference[article]
        for col in common[1:] + ([] if args.mode == "trade" else extra):
            if col in {"Остаток","Цена закупочная","Цена розничная"}:
                same = number(row[col]) == number(ref[col])
            else:
                same = row[col] == ref[col]
            if not same: errors.append(f"{article} · {col}: {row[col]!r}, ожидается {ref[col]!r}")
        if args.mode == "trade":
            for col, values in seen.items():
                value = UUID(row[col])
                if value.int == 0 or value in values: errors.append(f"{article} · {col}: пустой или повторный UID")
                values.add(value)
                if prior is not None and article in prior and value != UUID(prior[article][col]):
                    errors.append(f"{article} · {col} изменился после повторной загрузки")
            if article in TRADE_STOCK and number(row["Наш остаток"]) != TRADE_STOCK[article]:
                errors.append(f"{article} · наш остаток должен быть {TRADE_STOCK[article]}")
    if errors:
        print("\n".join(errors[:20]))
        print(f"Расхождений: {len(errors)}. Показаны первые 20.")
        return 1
    print(f"OK · {len(rows)} товаров. Проверены наименования, остатки производителя и цены.")
    if args.mode=="trade":
        print("Проверены уникальность локальных и внешних UID и восемь остатков Трейда.")
        if prior is not None: print("Обе ссылки стабильны между выгрузками для всех товаров.")
    else: print("Проверены три уровня групп и розничные цены.")
    return 0


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["production","trade"])
    p.add_argument("file",type=Path)
    p.add_argument("--previous",type=Path,help="первая выгрузка Трейда для проверки повторной загрузки")
    args=p.parse_args()
    if args.previous and args.mode!="trade": p.error("--previous применяется в режиме trade")
    try:
        sys.exit(run(args))
    except (ValueError, OSError, InvalidOperation, TypeError, csv.Error) as e:
        sys.exit("Проверьте значения и формат CSV: "+str(e))
