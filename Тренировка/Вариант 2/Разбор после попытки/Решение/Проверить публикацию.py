"""Независимая сверка учебной публикации УНФ с исходным Excel варианта 2."""
import argparse
import base64
from getpass import getpass
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

def main():
    here = Path(__file__).resolve().parent
    case = here.parent.parent
    sys.path.insert(0, str(case / "Сервис"))
    from prepare import read_rows, display_name
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8080/unf_production/odata/standard.odata/")
    parser.add_argument("--book", type=Path, default=case / "Исходники/Данные.xlsx")
    parser.add_argument("--order-b", help="UID заказа из вкладки POST")
    parser.add_argument("--order-g", help="UID заказа, отправленного из Трейда")
    parser.add_argument("--user", default="odata_user", help="Имя пользователя обмена")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    url = urlsplit(args.base)
    if url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.scheme not in {"http","https"}:
        parser.error("Укажите локальный адрес учебной публикации.")
    base = args.base.rstrip("/") + "/"
    password = getpass("Пароль пользователя обмена: ")
    auth = "Basic " + base64.b64encode(f"{args.user}:{password}".encode()).decode("ascii")
    def get(resource, params=None, authorized=True):
        target = base + quote(resource, safe="/$(),'") + ("?" + urlencode(params, safe="$",quote_via=quote) if params else "")
        req = Request(target, headers={"Authorization": auth} if authorized else {})
        with urlopen(req, timeout=90) as resp:
            return resp.read()
    def check(ok, info):
        if not ok: raise ValueError(info)
    def records(resource, **params):
        items=[]
        while True:
            result = json.loads(get(resource, {"$format":"json","$skip":len(items),"$top":16,**params}))
            page = result["value"]; items.extend(page)
            if not page or len(page)<16 and not(result.get("odata.nextLink") or result.get("@odata.nextLink")):return items
    rows = read_rows(args.book)
    wanted={r["Артикул"]:r for r in rows}
    try: get("",authorized=False)
    except HTTPError as exc: check(exc.code==401,f"Без пароля HTTP {exc.code}")
    else: raise ValueError("Корень доступен без пароля")
    get("")
    metadata = ElementTree.fromstring(get("$metadata"))
    names = {node.get("Name") for node in metadata.findall(".//{*}EntitySet")}
    resources = {"Catalog_Номенклатура","Catalog_Контрагенты","Catalog_ВидыЦен","Catalog_СтруктурныеЕдиницы","Catalog_СостоянияЗаказовПокупателей","Document_ЗаказПокупателя","AccumulationRegister_ЗапасыНаСкладах","InformationRegister_ЦеныНоменклатуры"}
    check(resources <= names, f"Ресурсы отсутствуют: {resources-names}")
    goods=records("Catalog_Номенклатура", **{"$select":"Ref_Key,Parent_Key,Description,Артикул,IsFolder","$orderby":"Ref_Key"})
    by_id={g["Ref_Key"]:g for g in goods}
    expected_paths = {tuple(v for v in (r["Группа"],r["Подгруппа"],r["Подподгруппа"]) if v) for r in rows}
    folders = {p[:i] for p in expected_paths for i in range(1,len(p)+1)}
    actual_folders={}; articles={}
    for g in goods:
        p=g["Parent_Key"]; path=[]; seen=set()
        while p in by_id:
            check(p not in seen,"Цикл папок");seen.add(p)
            parent=by_id[p];path.insert(0,parent["Description"]);p=parent["Parent_Key"]
        if g["IsFolder"]:
            pp=tuple(path+[g["Description"]])
            if pp[:1] in folders:
                check(pp not in actual_folders,f"Дубликат папки {pp}");actual_folders[pp]=g["Ref_Key"]
        elif tuple(path[:1]) in folders:
            art=g["Артикул"]
            check(art in wanted and art not in articles,f"Лишний или повторный артикул {art}")
            row=wanted[art]
            check(g["Description"]==display_name(row) and path==[row[k] for k in ("Группа","Подгруппа","Подподгруппа") if row[k]],f"Имя/папка {art}")
            articles[art]=g
    check(set(actual_folders)==folders and set(articles)==set(wanted),"Неполное дерево или каталог")
    group_id=actual_folders[("Бумажная продукция","Блокноты")]
    sample=records("Catalog_Номенклатура",**{"$filter":f"Parent_Key eq guid'{group_id}' and IsFolder eq false","$select":"Ref_Key,Description,Артикул","$orderby":"Description asc"})
    check({r["Артикул"] for r in sample}=={r["Артикул"] for r in rows if r["Подгруппа"]=="Блокноты"},"Неверный отбор")
    check(all({"Ref_Key","Description","Артикул"} <= set(r) and "Parent_Key" not in r for r in sample),"Ошибка $select")
    desc=records("Catalog_Номенклатура",**{"$filter":f"Parent_Key eq guid'{group_id}' and IsFolder eq false","$select":"Description","$orderby":"Description desc"})
    check([r["Description"] for r in sample]==[r["Description"] for r in reversed(desc)],"Ошибка $orderby")
    kinds={r["Ref_Key"]:r["Description"] for r in records("Catalog_ВидыЦен") if r["Description"] in {"Закупочная","Розничная"}}
    amounts={}
    for r in records("AccumulationRegister_ЗапасыНаСкладах/Balance"):
        k=r["Номенклатура_Key"];amounts[k]=amounts.get(k,0)+Decimal(str(r["КоличествоBalance"]))
    prices={}
    for r in records("InformationRegister_ЦеныНоменклатуры/SliceLast"):
        if r["ВидЦен_Key"] in kinds and r.get("Характеристика_Key")=="00000000-0000-0000-0000-000000000000":
            prices[r["Номенклатура_Key"], kinds[r["ВидЦен_Key"]]]=Decimal(str(r["Цена"]))
    for art,g in articles.items():
        k=g["Ref_Key"];row=wanted[art]
        check(amounts.get(k,0)==Decimal(row["Остаток"]),f"Остаток {art}")
        for kind,column in [("Закупочная","Цена закупочная"),("Розничная","Цена розничная")]:
            check(prices[k,kind]==Decimal(row[column]),f"{kind}: {art}")
    result={"HTTP без пароля":401,"HTTP с паролем":200,"Ресурсов проверено":len(resources),"Карточки":len(articles),"Папки":len(folders),"Остаток":int(sum(amounts.get(g["Ref_Key"],0) for g in articles.values())),"Цены":len(articles)*2,"Фильтр Блокноты":len(sample),"Размер страницы":16}
    for label,uid,date,expected,total in [("Б",args.order_b,"2026-12-01",{"1002":(3,65),"5001":(2,85)},365),("Г",args.order_g,"2026-12-02",{"1002":(4,65),"6002":(1,220)},480)]:
        if not uid: continue
        import uuid
        uid=str(uuid.UUID(uid))
        resource=f"Document_ЗаказПокупателя(guid'{uid}')"
        doc=json.loads(get(resource,{"$format":"json"}))
        partner=json.loads(get(resource+"/Контрагент",{"$format":"json"}))
        check(doc["Ref_Key"]==uid and doc["Date"][:10]==date and partner["Description"]=="ОфисПро Трейд" and Decimal(str(doc["СуммаДокумента"]))==total,f"Шапка заказа {label}")
        got={r["Номенклатура"]:(r["Количество"],r["Цена"]) for r in doc["Запасы"]}
        check(len(doc["Запасы"])==len(expected) and got=={articles[a]["Ref_Key"]:line for a,line in expected.items()},f"Строки заказа {label}")
        expanded=records("Document_ЗаказПокупателя",**{"$filter":f"Ref_Key eq guid'{uid}'","$select":"Ref_Key,Контрагент","$expand":"Контрагент"})
        check(len(expanded)==1 and expanded[0]["Контрагент"]["Description"]==partner["Description"],"Связанный контрагент не совпал")
        result["Заказ "+label]={"UID":uid,"Дата":date,"Сумма":total,"Строки":len(got)}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.json: args.json.write_text(text+"\n",encoding="utf-8")
    print(text)
if __name__=="__main__":
    main()
