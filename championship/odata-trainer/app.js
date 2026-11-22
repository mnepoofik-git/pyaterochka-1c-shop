"use strict";
const el = id => document.getElementById(id);
const goods = "Catalog_Номенклатура";
const stock = "AccumulationRegister_ЗапасыНаСкладах/Balance";
const prices = "InformationRegister_ЦеныНоменклатуры/SliceLast";
const orders = "Document_ЗаказПокупателя";
const partners = "Catalog_Контрагенты";
const sections = ["Номенклатура", "Остатки", "Цены", "Создание заказа", "Произвольный запрос", "Самопроверка"];
const resources = [goods, stock, prices, orders, partners, "Catalog_ВидыЦен", "Catalog_СтруктурныеЕдиницы",
  "Catalog_СостоянияЗаказовПокупателей", "Catalog_Организации", "$metadata", "Training_Error500"];
let active = 0;
let receipt = "";
let generation = 0;
const filters = ["IsFolder eq false", "", "", "", ""];
el("base").value = location.origin + "/unf_production/odata/standard.odata/";
el("date").value = "2027-01-15T10:00:00";
el("resource").value = goods;
for (const value of resources) el("resources").append(new Option(value, value));

function note(id, message, error = false) {
  const node = el(id);
  node.textContent = message;
  node.className = error ? "error" : "ok";
}
function switchTo(index) {
  filters[active] = el("filter").value;
  generation++;
  active = index;
  el("title").textContent = sections[index];
  el("browse").hidden = index === 3 || index === 5;
  el("create").hidden = index !== 3;
  el("check").hidden = index !== 5;
  el("resourceLabel").hidden = el("options").hidden = index !== 4;
  el("get").textContent = index === 4 ? "Выполнить" : "Получить";
  el("filter").value = filters[index] || "";
  el("grid").replaceChildren();
  note("message", "");
  [...el("tabs").children].forEach((button, i) => {
    if (i === index) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}
sections.forEach((label, i) => {
  const button = document.createElement("button");
  button.textContent = label;
  button.onclick = () => switchTo(i);
  el("tabs").append(button);
});
el("filter").value = filters[0];
switchTo(0);

function baseUrl() {
  const base = new URL(el("base").value);
  if (base.origin !== location.origin || base.username || base.password || base.search || base.hash)
    throw Error("Для браузерного клиента укажите публикацию на адресе этого тренажёра.");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return base;
}
function resourceUrl(resource, params = {}) {
  const base = baseUrl();
  const url = new URL(resource, base);
  if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname))
    throw Error("Введите имя ресурса относительно корня OData.");
  for (const [name, value] of Object.entries(params)) if (value) url.searchParams.set("$" + name, value);
  if (resource !== "$metadata") url.searchParams.set("$format", "json");
  return url;
}
async function request(url, body) {
  if (url.origin !== baseUrl().origin) throw Error("Проверьте адрес следующей страницы.");
  const token = new TextEncoder().encode(el("login").value + ":" + el("password").value);
  const headers = {Authorization: "Basic " + btoa(String.fromCharCode(...token))};
  const options = {headers, credentials: "omit", redirect: "error", cache: "no-store"};
  if (body) {
    headers["Content-Type"] = "application/json; charset=utf-8";
    Object.assign(options, {method: "POST", body: JSON.stringify(body)});
  }
  let response;
  try { response = await fetch(url, options); }
  catch { throw Error("Нет соединения. Проверьте адрес и запуск сервиса."); }
  const raw = await response.text();
  if (!response.ok) {
    let reason = response.statusText;
    try { reason = JSON.parse(raw).error.message.value; } catch {}
    throw Error("HTTP " + response.status + " · " + reason);
  }
  return response.headers.get("Content-Type")?.includes("xml") ? raw : JSON.parse(raw);
}
async function readAll(resource, params) {
  let url = resourceUrl(resource, params);
  const seen = new Set(), rows = [];
  while (!seen.has(url.href)) {
    seen.add(url.href);
    const data = await request(url);
    if (!Array.isArray(data.value)) return {value: data, pages: 1};
    rows.push(...data.value);
    const next = data["odata.nextLink"] || data["@odata.nextLink"];
    if (!next) return {value: rows, pages: seen.size};
    url = new URL(next, url);
  }
  throw Error("Сервис вернул повторную ссылку на страницу.");
}
function draw(value) {
  const grid = el("grid");
  grid.replaceChildren();
  if (!Array.isArray(value)) {
    const pre = document.createElement("pre");
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    grid.append(pre);
    return;
  }
  if (!value.length) return;
  const table = document.createElement("table"), head = table.createTHead().insertRow();
  const columns = Object.keys(value[0]);
  for (const key of columns) {
    const th = document.createElement("th");
    th.textContent = key;
    head.append(th);
  }
  const tbody = table.createTBody();
  for (const row of value) {
    const tr = tbody.insertRow();
    for (const key of columns) {
      const item = row[key];
      tr.insertCell().textContent = typeof item === "object" ? JSON.stringify(item) : item;
    }
  }
  grid.append(table);
}
el("connect").onsubmit = async event => {
  event.preventDefault();
  try {
    const data = await request(resourceUrl(""));
    if (!Array.isArray(data.value)) throw Error("Сервис не вернул список ресурсов.");
    note("status", "HTTP 200 · Подключено. Ресурсов в публикации: " + data.value.length);
  } catch (e) { note("status", e.message, true); }
};
el("query").onsubmit = async event => {
  event.preventDefault();
  const ticket = ++generation;
  const params = {filter: el("filter").value.trim()};
  if (active === 4) for (const k of ["select", "expand", "orderby"]) params[k] = el(k).value.trim();
  el("grid").replaceChildren();
  note("message", "Загрузка…");
  try {
    const result = await readAll(active === 4 ? el("resource").value.trim() : resources[active], params);
    if (ticket !== generation) return;
    draw(result.value);
    const total = Array.isArray(result.value) && result.value.length && result.value.every(row => typeof row.КоличествоBalance === "number")
      ? " · Остаток, шт.: " + result.value.reduce((sum, row) => sum + row.КоличествоBalance, 0).toLocaleString("ru-RU") : "";
    note("message", Array.isArray(result.value)
      ? "HTTP 200 · Загружено строк: " + result.value.length + " · Страниц: " + result.pages + total : "HTTP 200");
  } catch (e) { if (ticket === generation) note("message", e.message, true); }
};
function addLine() {
  const node = document.createElement("div");
  node.className = "line";
  node.innerHTML = '<label>UID товара<input class="product" required></label><label>Количество<input class="qty" type="number" min="0.001" step="0.001" required></label><label>Цена, ₽<input class="price" type="number" min="0.01" step="0.01" required></label><button class="alt" type="button">Убрать</button>';
  node.querySelector("button").onclick = () => node.remove();
  el("lines").append(node);
}
el("add").onclick = addLine;
addLine();
el("orderForm").onsubmit = async event => {
  event.preventDefault();
  const button = el("orderForm").querySelector("button:not([type])");
  button.disabled = true;
  el("receipt").textContent = "";
  el("reread").hidden = true;
  el("grid").replaceChildren();
  const lines = [...el("lines").children].map((line, i) => ({
    LineNumber: i + 1, Номенклатура: line.querySelector(".product").value.trim(),
    Номенклатура_Type: "StandardODATA." + goods, Количество: Number(line.querySelector(".qty").value),
    Цена: Number(line.querySelector(".price").value)
  }));
  try {
    const doc = await request(resourceUrl(orders), {Date: el("date").value, Контрагент_Key: el("buyer").value.trim(), Запасы: lines});
    receipt = doc.Ref_Key;
    el("receipt").textContent = "HTTP 201 · UID созданного заказа: " + receipt;
    el("reread").hidden = false;
    if (active === 3) note("message", "");
  } catch (e) { if (active === 3) note("message", e.message, true); }
  finally { button.disabled = false; }
};
async function readOrder(id) {
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) throw Error("Проверьте формат UID заказа.");
  return request(resourceUrl(orders + "(guid'" + id + "')", {expand: "Контрагент"}));
}
el("reread").onclick = async () => {
  try {
    const doc = await readOrder(receipt);
    if (active === 3) { draw(doc); note("message", "HTTP 200 · Заказ прочитан по UID"); }
  } catch (e) { if (active === 3) note("message", e.message, true); }
};
el("answers").onsubmit = async event => {
  event.preventDefault();
  const values = new FormData(event.target), list = el("verdict");
  list.replaceChildren();
  function mark(ok, label) {
    const li = document.createElement("li");
    li.textContent = (ok ? "Верно · " : "Проверьте · ") + label;
    li.className = ok ? "ok" : "error";
    list.append(li);
  }
  for (const [field, expected, label] of [["goods",500,"Товары без папок"],["stock",486150,"Сумма остатков"],
    ["prices",1000,"Цены двух видов"],["group",60,"Товары в папке «Блокноты»"]]) {
    mark(Number(values.get(field)) === expected, label);
  }
  try {
    const doc = await readOrder(values.get("uid").trim());
    mark(doc.Date.slice(0,10) === "2027-01-15", "Дата заказа");
    mark(doc.Контрагент.Description === "ОфисПро Трейд", "Связанный контрагент");
    const ref = await readAll(goods, {filter: "IsFolder eq false", select: "Ref_Key,Артикул"});
    const articles = new Map(ref.value.map(r => [r.Ref_Key, r.Артикул]));
    const rows = doc.Запасы.map(r => [articles.get(r.Номенклатура),r.Количество,r.Цена].join("/")).sort();
    mark(rows.join("|") === "УЧ-0001/2/83|УЧ-0002/3/90", "Состав, количество и закупочные цены");
    mark(doc.СуммаДокумента === 436, "Сумма заказа");
  } catch (e) { mark(false, e.message); }
};
