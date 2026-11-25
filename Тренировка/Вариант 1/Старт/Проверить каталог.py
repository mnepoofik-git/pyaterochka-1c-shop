"""Проверка домашнего учебного архива без внешних библиотек."""
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def check(test, text):
    if not test:
        raise ValueError(text)


def verify():
    archive = Path(__file__).with_name("Учебный каталог ОфисПро — 500 товаров.zip")
    with ZipFile(archive) as files:
        check(files.testzip() is None, "Ошибка контрольной суммы ZIP")
        books = [n for n in files.namelist() if n.endswith(".xlsx")]
        check(len(books) == 1, "Ожидается одна книга каталога")
        with ZipFile(BytesIO(files.read(books[0]))) as book:
            sst = [s.findtext("{*}t","") for s in ET.fromstring(book.read("xl/sharedStrings.xml"))] if "xl/sharedStrings.xml" in book.namelist() else []
            sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
            rows = []
            for tr in sheet.findall(".//{*}row"):
                cells = {}
                for cell in tr.findall("{*}c"):
                    v = cell.findtext("{*}v", "")
                    cells[cell.get("r").rstrip("0123456789")] = sst[int(v)] if cell.get("t") == "s" else v
                rows.append(cells)
        headers, records = rows[0], rows[1:]
        check(headers.get("E") == "Артикул" and headers.get("K") == "Остаток", "Проверьте структуру листа")
        articles = [r["E"] for r in records]
        barcodes = [r["G"] for r in records]
        check(len(articles) == len(set(articles)) == len(set(barcodes)) == 500, "Проверьте количество строк и дубли")
        for r in records:
            s = r["G"]
            check(len(s)==13 and s.isascii() and s.isdigit() and sum(int(c)*(3 if i%2 else 1) for i,c in enumerate(s))%10==0, "Ошибочный EAN-13 у "+r["E"])
            check(Decimal(r["L"])>0 and Decimal(r["M"])>0, "Проверьте обе цены у "+r["E"])
        imgs = Counter(n for n in files.namelist() if n.startswith("images/") and n.endswith(".png"))
        check(imgs == Counter("images/"+a+".png" for a in articles),"Состав изображений расходится с артикулами")
        total = sum(Decimal(r["K"]) for r in records)
        check(total == 486150, "Проверьте сумму остатков домашнего набора")
        print("Проверено: 500 товаров, 500 уникальных EAN-13, 500 PNG по артикулу, 1 000 цен и 486 150 шт.")


if __name__ == "__main__":
    verify()
