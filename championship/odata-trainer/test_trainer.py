"""Проверка HTTP-контракта учебного сервиса с отдельной временной БД."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen
import uuid
from xml.etree import ElementTree as ET

from model import BUYER, GOODS, ORDER, PRICE, STOCK, init_db
from verify_publication import Endpoint, check_catalog, check_group, check_metadata, check_order, check_register
from trainer import Handler, ROOT, ThreadingHTTPServer


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class HTTPChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.addCleanup(server.server_close)
        server.db = Path(temp.name) / "orders.sqlite3"
        init_db(server.db)
        server.auth = b"Basic " + base64.b64encode(b"odata_user:local-test")
        self.auth = server.auth.decode()
        self.root = f"http://127.0.0.1:{server.server_port}" + ROOT
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

    def fetch(self, path="", params=None, body=None, auth=True, absolute=False):
        url = urljoin(self.root, path) if absolute else self.root + quote(path)
        if params:
            url += "?" + urlencode(params)
        headers = {"Authorization": self.auth} if auth else {}
        request = Request(url, headers=headers, data=None if body is None else json.dumps(body).encode())
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.code, (ET.fromstring(raw) if "xml" in response.headers["Content-Type"] else json.loads(raw))

    def pages(self, path, params=None):
        status, data = self.fetch(path, params)
        rows = []
        count = 0
        while True:
            self.assertEqual(status, 200)
            rows.extend(data["value"])
            count += 1
            if "odata.nextLink" not in data:
                return rows, count
            status, data = self.fetch(data["odata.nextLink"], absolute=True)

    def test_publication(self):
        self.assertEqual(self.fetch(auth=False)[0], 401)
        self.assertEqual(len(self.fetch()[1]["value"]), 9)
        meta = self.fetch("$metadata")[1]
        self.assertEqual(len(meta.findall(".//{*}EntitySet")), 9)
        self.assertTrue(meta.findall(".//{*}NavigationProperty[@Name='Контрагент']"))
        for path, code in [("отсутствует", 404), ("Training_Error500", 500)]:
            self.assertEqual(self.fetch(path)[0], code)
        for params in [{"$select":"Ошибка"}, {"$filter":"Опечатка eq false"}, {"$skip":"-1"}]:
            self.assertEqual(self.fetch(GOODS, params)[0], 400)

    def test_publication_verifier(self):
        api = Endpoint(self.root, "odata_user", "local-test")
        check_metadata(api)
        self.assertIn("500 товаров", check_catalog(api))
        self.assertIn("60 строк", check_group(api))
        self.assertIn("486150", check_register(api, STOCK+"/Balance", "КоличествоBalance"))
        self.assertIn("1000 строк", check_register(api, PRICE+"/SliceLast", "Цена"))

    def test_queries(self):
        rows, count = self.pages(GOODS, {"$filter":"IsFolder eq false", "$orderby":"Description asc",
                                         "$select":"Ref_Key,Description,Артикул"})
        self.assertEqual((len({r["Ref_Key"] for r in rows}), count), (500, 5))
        self.assertEqual(list(rows[0]), ["Ref_Key", "Description", "Артикул"])
        self.assertEqual(rows, sorted(rows, key=lambda r:r["Description"]))
        folder = self.pages(GOODS, {"$filter":"IsFolder eq true and Description eq 'Блокноты'"})[0][0]
        group = self.pages(GOODS, {"$filter":"Parent_Key eq guid'" + folder["Ref_Key"] + "'"})[0]
        self.assertEqual(len(group), 60)
        stock, pages = self.pages(STOCK + "/Balance")
        self.assertEqual((len(stock), pages, sum(r["КоличествоBalance"] for r in stock)), (500,5,486150))
        self.assertEqual(len(self.pages(PRICE + "/SliceLast")[0]), 1000)
        self.assertEqual(len(self.pages(GOODS, {"$top":"110","$skip":"10"})[0]), 110)

    def test_order(self):
        products, _ = self.pages(GOODS, {"$filter":"IsFolder eq false", "$orderby":"Артикул asc", "$top":"2"})
        body = {"Ref_Key":str(uuid.uuid4()), "Date":"2027-01-15T10:00:00", "Контрагент_Key":BUYER["Ref_Key"],
                "Запасы":[{"Номенклатура":p["Ref_Key"], "Количество":q, "Цена":v}
                          for p, q, v in zip(products, [2, 3], [83, 90])]}
        with ThreadPoolExecutor(2) as pool:
            statuses = sorted(pool.map(lambda _: self.fetch(ORDER, body=body)[0], range(2)))
        self.assertEqual(statuses, [201, 409])
        status, doc = self.fetch(ORDER + "(guid'" + body["Ref_Key"] + "')", {"$expand":"Контрагент"})
        self.assertEqual((status, doc["СуммаДокумента"], doc["Контрагент"]["Description"]), (200,436,"ОфисПро Трейд"))
        self.assertEqual(doc["Date"], body["Date"])
        self.assertEqual(len(doc["Запасы"]), 2)
        api = Endpoint(self.root, "odata_user", "local-test")
        check_order(api, body["Ref_Key"], True)
        state_url = "/practice/orders/" + body["Ref_Key"] + "/state"
        self.assertEqual(self.fetch(state_url, body={"state":"Закрыт"}, auth=False, absolute=True)[0], 401)
        self.assertEqual(self.fetch(state_url, body={"state":"Ошибка"}, absolute=True)[0], 400)
        status, changed = self.fetch(state_url, body={"state":"В работе"}, absolute=True)
        self.assertEqual(status, 200)
        status, saved = self.fetch(ORDER + "(guid'" + body["Ref_Key"] + "')")
        self.assertEqual(saved["СостояниеЗаказа"], changed["СостояниеЗаказа"])
        self.assertNotEqual(saved["СостояниеЗаказа"], doc["СостояниеЗаказа"])
        body["Запасы"][1]["Количество"] = -3
        self.assertEqual(self.fetch(ORDER, body=body)[0], 400)
        self.assertEqual(len(self.pages(ORDER)[0]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
