"""Подмножество запросов модуля Б и описание опубликованных полей."""
import operator
import re
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from model import BUYER, DATA, ORDER, STOCK, PRICE, PARTNERS, LINE_FIELDS, ORDER_FIELDS, Problem

PAGE = 100
SCHEMA = {name: {key: ("Guid" if key.endswith("_Key") else
                       {str: "String", bool: "Boolean", int: "Decimal", float: "Decimal"}[type(value)])
                 for key, value in rows[0].items()} for name, rows in DATA.items()}
SCHEMA[ORDER] = ORDER_FIELDS
ACTIONS = {STOCK: "Balance", PRICE: "SliceLast"}
KEYS = {STOCK: ["Номенклатура_Key", "СтруктурнаяЕдиница_Key"],
        PRICE: ["Номенклатура_Key", "Характеристика_Key", "ВидЦен_Key"]}


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
        if name == ORDER:
            sub(entity, "NavigationProperty", Name="Контрагент", Relationship="StandardODATA.OrderPartner",
                FromRole="Orders", ToRole="Partner")
    assoc = sub(schema, "Association", Name="OrderPartner")
    for role, name, count in [("Orders", ORDER, "*"), ("Partner", PARTNERS, "1")]:
        sub(assoc, "End", Role=role, Type="StandardODATA." + name, Multiplicity=count)
    container = sub(schema, "EntityContainer", {f"{{{meta}}}IsDefaultEntityContainer": "true"}, Name="OfficePro")
    for name in SCHEMA:
        sub(container, "EntitySet", Name=name, EntityType="StandardODATA." + name)
    aset = sub(container, "AssociationSet", Name="OrderPartners", Association="StandardODATA.OrderPartner")
    for role, name in [("Orders", ORDER), ("Partner", PARTNERS)]:
        sub(aset, "End", Role=role, EntitySet=name)
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


def match_filter(rows, expr, fields):
    # Each step consumes a complete literal, including doubled quotes inside strings.
    term = re.compile(r"(\w+)\s+(eq|ne|lt|le|gt|ge)\s+(?:((?:guid)?'(?:[^']|'')*')|(true|false)|(-?\d+(?:\.\d+)?))", re.I)
    pos = 0
    while pos < len(expr):
        m = term.match(expr, pos)
        if not m or m[1] not in fields:
            raise Problem("Проверьте имя поля и выражение $filter.")
        field, op, string, boolean, number = m.groups()
        typ = fields[field]
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
    unknown = params.keys() - supported
    if unknown or params.get("$format", "json") != "json":
        raise Problem("Неизвестный параметр или формат. Для ответа укажите $format=json.")
    fields = SCHEMA[name]
    if key is not None:
        rows = [r for r in rows if r.get("Ref_Key") == key]
        if not rows:
            raise Problem("Объект с таким UID не найден.", 404)
    rows = match_filter(rows, params.get("$filter", "").strip(), fields)
    if "$orderby" in params:
        order = params["$orderby"].split()
        if len(order) not in (1, 2) or order[0] not in fields or (len(order) == 2 and order[1] not in ("asc", "desc")) or fields[order[0]].startswith("Collection"):
            raise Problem("Укажите поле и направление asc или desc в $orderby.")
        rows = sorted(rows, key=lambda r: r[order[0]], reverse=order[-1] == "desc")
    expand = params.get("$expand")
    if expand is not None and (name != ORDER or expand != "Контрагент"):
        raise Problem("Доступная связь заказа для $expand — Контрагент.")
    selected = [s.strip() for s in params["$select"].split(",")] if "$select" in params else list(fields)
    if any(k not in fields and not (expand and k == expand) for k in selected):
        raise Problem("Неизвестное поле в $select.")
    skip = opt_number(params, "$skip", 0)
    top = opt_number(params, "$top", len(rows))
    size = min(top, PAGE)
    values = [{k: r[k] for k in selected if k in r} for r in rows[skip:skip + size]]
    if expand:
        for r in values:
            r[expand] = BUYER
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
