"""Подмножество запросов модуля Б и описание опубликованных полей."""
import operator
import re
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from model import DATA, GOODS, KINDS, ORDER, STOCK, PRICE, PARTNERS, LINE_FIELDS, ORDER_FIELDS, Problem

PAGE = 7
SCHEMA = {name: {key: ("Guid" if key.endswith("_Key") else
                       {str: "String", bool: "Boolean", int: "Decimal", float: "Decimal"}[type(value)])
                 for key, value in rows[0].items()} for name, rows in DATA.items()}
SCHEMA[ORDER] = ORDER_FIELDS
ACTIONS = {STOCK: "Balance", PRICE: "SliceLast"}
KEYS = {STOCK: ["Номенклатура_Key", "СтруктурнаяЕдиница_Key"],
        PRICE: ["Номенклатура_Key", "Характеристика_Key", "ВидЦен_Key"]}

# Navigation properties used in the five practicum sessions.
NAV = {
    GOODS: {"Parent": (GOODS, "Parent_Key")},
    STOCK: {"Номенклатура": (GOODS, "Номенклатура_Key")},
    PRICE: {"Номенклатура": (GOODS, "Номенклатура_Key"), "ВидЦен": (KINDS, "ВидЦен_Key")},
    ORDER: {"Контрагент": (PARTNERS, "Контрагент_Key")},
}
INDEX = {name: {r["Ref_Key"]: r for r in records if "Ref_Key" in r} for name, records in DATA.items()}


def related(name, row, field):
    target, key = NAV[name][field]
    return INDEX[target].get(row[key])


def metadata():
    edm = "http://schemas.microsoft.com/ado/2009/11/edm"
    meta = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
    edmx = "http://schemas.microsoft.com/ado/2007/06/edmx"
    for prefix, ns in [("", edm), ("m", meta), ("edmx", edmx)]:
        ET.register_namespace(prefix, ns)
    sub = ET.SubElement
    root = ET.Element(f"{{{edmx}}}Edmx", Version="1.0")
    services = sub(root, f"{{{edmx}}}DataServices", {f"{{{meta}}}DataServiceVersion": "3.0"})
    schema = sub(services, f"{{{edm}}}Schema", Namespace="StandardODATA")
    def props(element, fields, keys=()):
        for field, typ in fields.items():
            typename = typ if typ.startswith("Collection(") else "Edm." + typ
            sub(element, "Property", Name=field, Type=typename, Nullable=str(field not in keys).lower())
    props(sub(schema, "ComplexType", Name="OrderLine"), LINE_FIELDS)
    for name, fields in SCHEMA.items():
        entity = sub(schema, "EntityType", Name=name)
        key = sub(entity, "Key")
        keys = KEYS.get(name, ["Ref_Key"])
        for field in keys:
            sub(key, "PropertyRef", Name=field)
        props(entity, fields, keys)
        for prop, (target, _) in NAV.get(name, {}).items():
            link = name + "_" + prop
            sub(entity, "NavigationProperty", Name=prop, Relationship="StandardODATA." + link,
                FromRole="Source", ToRole="Target")
            assoc = sub(schema, "Association", Name=link)
            sub(assoc, "End", Role="Source", Type="StandardODATA." + name, Multiplicity="*")
            sub(assoc, "End", Role="Target", Type="StandardODATA." + target, Multiplicity="0..1")
    container = sub(schema, "EntityContainer", {f"{{{meta}}}IsDefaultEntityContainer": "true"}, Name="OfficePro")
    for name in SCHEMA:
        sub(container, "EntitySet", Name=name, EntityType="StandardODATA." + name)
    for name, props in NAV.items():
        for prop, (target, _) in props.items():
            link = name + "_" + prop
            aset = sub(container, "AssociationSet", Name=link, Association="StandardODATA." + link)
            sub(aset, "End", Role="Source", EntitySet=name)
            sub(aset, "End", Role="Target", EntitySet=target)
    for name, action in ACTIONS.items():
        func = sub(container, "FunctionImport", Name=action, IsBindable="true", IsSideEffecting="false",
                   ReturnType=f"Collection(StandardODATA.{name})")
        sub(func, "Parameter", Name="bindingParameter", Type="StandardODATA." + name)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def opt_number(params, key, default):
    if key not in params:
        return default
    val = params[key]
    if not re.fullmatch(r"[0-9]{1,10}", val):
        raise Problem(key + " ожидает целое неотрицательное число.")
    return int(val)


def match_filter(name, rows, expr, fields):
    # Each step consumes a complete literal, including doubled quotes inside strings.
    term = re.compile(r"(\w+(?:/Description)?)\s+(eq|ne|lt|le|gt|ge)\s+(?:((?:guid)?'(?:[^']|'')*')|(true|false)|(-?\d+(?:\.\d+)?))", re.I)
    pos = 0
    while pos < len(expr):
        m = term.match(expr, pos)
        if not m:
            raise Problem("Проверьте имя поля и выражение $filter.")
        field, op, string, boolean, number = m.groups()
        path = field.split("/")
        nested = len(path) == 2 and path[0] in NAV.get(name, {})
        if not nested and field not in fields:
            raise Problem("Неизвестное поле фильтра " + field)
        typ = "String" if nested else fields[field]
        if string and typ in ("Guid", "String", "DateTime"):
            val = string[string.index("'")+1:-1].replace("''", "'")
        elif boolean and typ == "Boolean":
            val = boolean.lower() == "true"
        elif number and typ in ("Decimal", "Int32"):
            val = float(number)
        else:
            raise Problem("Тип значения в $filter не соответствует полю " + field)
        compare = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
                   "le": operator.le, "gt": operator.gt, "ge": operator.ge}[op.lower()]
        if nested:
            rows = [r for r in rows if related(name, r, path[0]) and compare(related(name, r, path[0])["Description"], val)]
        else:
            rows = [r for r in rows if compare(r[field], val)]
        pos = m.end()
        if pos < len(expr):
            join = re.match(r"\s+and\s+", expr[pos:], re.I)
            if not join:
                raise Problem("Условия отбора соединяются через and.")
            pos += join.end()
            if pos == len(expr):
                raise Problem("После and требуется условие.")
    return rows


def read(name, rows, params, address, key=None):
    supported = {"$format", "$filter", "$select", "$expand", "$orderby", "$top", "$skip"}
    if name == STOCK and params.get("Dimensions") == "Номенклатура":
        supported.add("Dimensions")  # One practice warehouse and one balance per SKU.
    unknown = params.keys() - supported
    if unknown or params.get("$format", "json") != "json":
        raise Problem("Неизвестный параметр или формат. Для ответа укажите $format=json.")
    fields = SCHEMA[name]
    if key is not None:
        rows = [r for r in rows if r.get("Ref_Key") == key]
        if not rows:
            raise Problem("Объект с таким UID не найден.", 404)
    rows = match_filter(name, rows, params.get("$filter", "").strip(), fields)
    if "$orderby" in params:
        order = params["$orderby"].split()
        if len(order) not in (1, 2) or order[0] not in fields or (len(order) == 2 and order[1] not in ("asc", "desc")) or fields[order[0]].startswith("Collection"):
            raise Problem("Укажите поле и направление asc или desc в $orderby.")
        rows = sorted(rows, key=lambda r: r[order[0]], reverse=order[-1] == "desc")
    expand = [x.strip() for x in params.get("$expand", "").split(",") if x.strip()]
    if any(prop not in NAV.get(name, {}) for prop in expand):
        raise Problem("Проверьте имя связи для $expand.")
    selected = [s.strip() for s in params["$select"].split(",")] if "$select" in params else list(fields)
    if any(k not in fields and k not in expand for k in selected):
        raise Problem("Неизвестное поле в $select.")
    skip = opt_number(params, "$skip", 0)
    top = opt_number(params, "$top", len(rows))
    size = min(top, PAGE)
    values = []
    for row in rows[skip:skip + size]:
        item = {k: row[k] for k in selected if k in row}
        for prop in expand:
            item[prop] = related(name, row, prop)
        values.append(item)
    if key is not None:
        if not values:
            raise Problem("Запись с таким отбором не найдена.", 404)
        return values[0]
    result = {"value": values}
    if top > size and skip + size < len(rows):
        more = dict(params)
        more["$skip"] = skip + size
        if "$top" in params:
            more["$top"] = top - size
        result["odata.nextLink"] = address + "?" + urlencode(more)
    return result
