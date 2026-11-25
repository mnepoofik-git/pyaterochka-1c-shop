"""Подготовка каталога эмулятора из Данные.xlsx практикума. Только стандартная библиотека."""
import csv
import io
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
HEAD = "Категория|Группа|Подгруппа|Подподгруппа|Артикул|Наименование|Штрихкод|Цвет|Размер|Материал|Остаток|Цена закупочная|Цена розничная".split("|")


def workbook(path):
    if path.is_dir():
        files = list(path.glob("*.xlsx")) or list(path.glob("*.zip"))
        if len(files) != 1:
            raise ValueError("Укажите сам файл Данные.xlsx или Материалы.zip.")
        path = files[0]
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [n for n in archive.namelist() if n.lower().endswith(".xlsx")]
            if len(candidates) != 1:
                raise ValueError("В архиве должна быть одна исходная книга.")
            return io.BytesIO(archive.read(candidates[0]))
    return path


def read_rows(path):
    with zipfile.ZipFile(workbook(path)) as book:
        def strings(node):
            return "".join(x.text or "" for x in node.findall(".//{*}t"))
        shared = [strings(x) for x in ET.fromstring(book.read("xl/sharedStrings.xml"))] if "xl/sharedStrings.xml" in book.namelist() else []
        rows = []
        for row in ET.fromstring(book.read("xl/worksheets/sheet1.xml")).findall(".//{*}row"):
            record = {}
            for cell in row.findall("{*}c"):
                col = re.match(r"[A-Z]+", cell.get("r"))[0]
                value = cell.findtext("{*}v", "")
                if cell.get("t") == "s":
                    value = shared[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = strings(cell)
                record[col] = value.strip()
            line = [record.get(chr(65+i), "") for i in range(len(HEAD))]
            if any(line):
                rows.append(line)
    if not rows or rows[0] != HEAD:
        raise ValueError("Столбцы не соответствуют Данные.xlsx практикума.")
    records = [dict(zip(HEAD, row)) for row in rows[1:]]
    if len(records) != 38 or len({r["Артикул"] for r in records}) != 38:
        raise ValueError("Для варианта 2 нужны 38 разных артикулов.")
    return records


def display_name(row):
    return " ".join(row[f] for f in ("Наименование","Цвет","Размер","Материал") if row[f])


def prepare(path):
    records = read_rows(path)
    target = HERE / "catalog.csv"
    payload = io.StringIO(newline="")
    writer = csv.DictWriter(payload, HEAD)
    writer.writeheader()
    for row in records:
        writer.writerow(dict(row, Наименование=display_name(row)))
    target.write_bytes(payload.getvalue().encode("utf-8"))
    return len(records)


if __name__ == "__main__":
    try:
        n = prepare(Path(sys.argv[1]) if len(sys.argv) == 2 else HERE.parent / "Исходники" / "Данные.xlsx")
        print(f"Подготовлено товаров: {n}. Запустите server.py.")
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        sys.exit(f"Ошибка подготовки: {error}")
