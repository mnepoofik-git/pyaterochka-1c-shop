"use strict";
const $ = id => document.getElementById(id);
const key = "officepro-championship-attempt-v1";
let state = {}, modules, current, interval;
try { state = JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch {}
state.marks ||= {};
state.responses ||= {};
const cases = [
  ["УЧ-0101","Ручка шариковая Office (синяя, 0.7 мм)",120,200,500],
  ["УЧ-0102","Ручка шариковая Office (чёрная, 0.7 мм)",85,150,400],
  ["УЧ-0001","Блокнот на спирали A5",10,50,150],
  ["УЧ-0002","Блокнот на спирали A4",45,30,100],
  ["УЧ-0201","Маркер текстовый Neon (жёлтый)",200,100,300],
  ["УЧ-0301","Папка-регистратор (синяя, A4, картон)",5,40,120],
  ["УЧ-0331","Папка-скоросшиватель (синяя, A4, пластик)",150,100,300],
  ["УЧ-0061","Тетрадь 48 листов клетка A5",0,80,200]
];
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function save() {
  try { localStorage.setItem(key, JSON.stringify(state)); $("saved").textContent = "Сохранено в этом браузере"; }
  catch { $("saved").textContent = "Хранилище браузера недоступно. Скачайте отчёт."; }
}
function sums(module) {
  return module.criteria.reduce((v,c) => [v[0]+Number(state.marks[c.row]?.score || 0),v[1]+c.points], [0,0]);
}
function scores() {
  const total = modules.reduce((sum,m) => sum+sums(m)[0],0);
  $("overall").textContent = Number(total.toFixed(2))+" / 100";
  $("subtotal").textContent = sums(current).map(x => Number(x.toFixed(2))).join(" / ")+" баллов";
}
function criterion(c) {
  const box=node("div",undefined,"criterion"),desc=node("div",undefined,"desc");
  desc.append(node("strong",c.title),node("p",c.action),node("small","Строка "+c.row+" · "+(c.judged?"Судейский аспект":"Измеримый аспект")));
  const fields=state.marks[c.row] ||= {};
  const label=node("label","Балл из "+c.points,"points"),points=node("input");
  Object.assign(points,{type:"number",min:0,max:c.points,step:"0.01",value:fields.score ?? ""});
  points.oninput=()=>{
    if (!points.validity.valid) { points.reportValidity(); delete fields.score; }
    else if(points.value==="") delete fields.score;
    else fields.score=Number(points.value);
    scores();save();
  };
  label.append(points);
  const proof=node("label","Основание"),note=node("input");
  note.placeholder="Документ, UID, файл или наблюдение";
  note.value=fields.note || "";note.oninput=()=>{fields.note=note.value;save();};proof.append(note);
  box.append(desc,label,proof);return box;
}
function inputFor(id) {
  const field=node("input");field.type="number";field.min=0;field.step=1;
  field.value=state.responses[id] ?? "";
  field.oninput=()=>{state.responses[id]=field.value;save();};
  return field;
}
function exercise(box, code, data) {
  const form=node("form"),out=node("output");out.setAttribute("aria-live","polite");
  const inputs=[];
  for(const [i,[label,expected]] of data.entries()) {
    const field=inputFor(code+i), wrap=node("label",label);
    field.required=true;wrap.append(field);form.append(wrap);inputs.push([field,label,expected]);
  }
  const send=node("button","Сверить");form.append(send);box.append(form,out);
  form.onsubmit=e=>{e.preventDefault();
    const misses=inputs.filter(([field,,expected])=>field.value===""||Number(field.value)!==expected);
    out.textContent=misses.length?"Перепроверьте: "+misses.map(([,label])=>label).join(", "):"Все значения совпали с учебным набором.";
  };
}
function tableCases(box, editable) {
  const area=node("div",undefined,"scroll"),table=node("table"),head=table.createTHead().insertRow();
  ["Артикул","Товар","Остаток","Мин.","Макс.",...(editable?["Ваш расчёт"]:[])].forEach(x=>head.append(node("th",x)));
  const body=table.createTBody(),fields=[];
  for(const r of cases) {
    const tr=body.insertRow();r.forEach(x=>tr.insertCell().textContent=x);
    if(editable) {const input=inputFor("Д"+r[0]);input.setAttribute("aria-label","Потребность "+r[0]);tr.insertCell().append(input);fields.push(input);}
  }
  area.append(table);box.append(area);
  if(!editable)return;
  const check=node("button","Сверить восемь строк"),out=node("output");out.setAttribute("aria-live","polite");
  check.onclick=()=>{
    const errors=cases.filter((r,i)=>fields[i].value===""||Number(fields[i].value)!==(r[2]<r[3]?r[4]-r[2]:0));
    out.textContent=errors.length?"Проверьте строки: "+errors.map(r=>r[0]).join(", "):"Совпало. В заказе 5 строк, всего 1 150 шт.";
  };box.append(check,out);
}
function stateLab(box) {
  const form=node("form"),id=node("input"),pass=node("input"),select=node("select"),out=node("output");
  for(const name of ["Не подтвержден","Подтвержден","В работе","Выполнен","Закрыт"])select.add(new Option(name));
  for(const [label,field] of [["UID заказа из клиента",id],["Пароль odata_user",pass],["Новое состояние",select]]) {
    const wrap=node("label",label);field.required=true;wrap.append(field);form.append(wrap);
  }
  pass.type="password";pass.autocomplete="off";form.append(node("button","Изменить у учебного производителя"));box.append(form,out);
  form.onsubmit=async e=>{e.preventDefault();
    try{
      const uid=id.value.trim();
      if(!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(uid))throw Error("Проверьте формат UID.");
      const token=btoa(String.fromCharCode(...new TextEncoder().encode("odata_user:"+pass.value)));
      const response=await fetch("/practice/orders/"+uid+"/state",{method:"POST",credentials:"omit",
        headers:{Authorization:"Basic "+token,"Content-Type":"application/json"},body:JSON.stringify({state:select.value})});
      const body=await response.json();
      if(!response.ok)throw Error("HTTP "+response.status+" · "+body.error.message.value);
      out.textContent="Состояние сохранено. Прочитайте заказ в Трейде. UID состояния: "+body.СостояниеЗаказа;
    }catch(err){out.textContent=err.message;}
  };
}
function clock(box) {
  const face=node("output",undefined,"clock"),start=node("button","Начать выступление"),stop=node("button","Завершить","alt");
  const controls=node("div",undefined,"inline");controls.append(start,stop);box.append(face,controls);
  function tick(){
    const ms=state.talkStart ? Date.now()-state.talkStart : state.talkMs||0;
    const sec=Math.floor(ms/1000);
    face.textContent=Math.floor(sec/60)+":"+String(sec%60).padStart(2,"0")+(ms>180000?" · лимит превышен":"");
    start.disabled=Boolean(state.talkStart);stop.disabled=!state.talkStart;
  }
  start.onclick=()=>{state.talkStart=Date.now();state.talkMs=0;save();tick();};
  stop.onclick=()=>{state.talkMs=Date.now()-state.talkStart;delete state.talkStart;save();tick();};
  tick();interval=setInterval(tick,250);
}
function show(module) {
  current=module;clearInterval(interval);
  $("heading").textContent=module.title;
  $("meta").textContent="Модуль "+module.code+" · "+module.minutes+" мин · "+module.base;
  $("steps").replaceChildren(...module.steps.map(s=>node("li",s)));
  $("criteria").replaceChildren(...module.criteria.map(criterion));
  for(const b of $("modules").children)b.setAttribute("aria-current",b.dataset.code===module.code?"page":"false");
  const box=$("exercise");box.className="lab";box.replaceChildren();
  const tasks={
    А:()=>{box.append(node("h3","Сверка после импорта"),node("p","Введите результаты из своей базы после второй загрузки учебного Excel."));
      exercise(box,"А",[["Товаров",500],["Папок",15],["Цен",1000],["Изображений",500],["Остаток, шт.",486150]]);},
    Б:()=>{box.append(node("h3","Проверка своего клиента"),node("p","Подключите свою обработку к сервису. Создайте заказ на 2 шт. УЧ-0001 и 3 шт. УЧ-0002 по закупочным ценам на 15.01.2027. Введите UID в разделе «Самопроверка» клиента OData."));
      const link=node("a","Открыть клиент OData →");link.href="/";box.append(link);},
    В:()=>{box.append(node("h3","Контроль прихода и синхронизации"),node("p","Создайте карточки и задайте остатки по таблице. После двух импортов в изначально пустой базе сверьте регистр и число элементов."));tableCases(box,false);
      exercise(box,"В",[["Исходных карточек",8],["Новых при первой загрузке",492],["Связей после второй",500],["Новых при второй",0]]);},
    Г:()=>{box.append(node("h3","Изменение состояния у производителя"),node("p","Форма меняет сохранённый учебный заказ. Затем проверьте получение события своей обработкой в 1С."));stateLab(box);},
    Д:()=>{box.append(node("h3","Рекомендации к закупке"),node("p","Перенесите количества из своего отчёта. Если позиция отсутствует в рекомендациях, введите 0."));tableCases(box,true);},
    Е:()=>{box.append(node("h3","Репетиция защиты"),node("p","Нажмите «Начать выступление» перед первым слайдом и «Завершить» после последней фразы. Лимит — 3 минуты."));clock(box);}
  };
  tasks[module.code]();scores();
}
function report(){
  const lines=["ОфисПро · Отчёт о самостоятельной тренировке",new Date().toLocaleString("ru-RU"),"Самооценка: "+$("overall").textContent];
  for(const m of modules){
    lines.push("",m.code+". "+m.title+" · "+sums(m).join(" / "));
    for(const c of m.criteria){const v=state.marks[c.row]||{};
      lines.push("Строка "+c.row+" · "+c.title+" · "+(v.score??"не проверено")+" / "+c.points+(v.note?" · "+v.note:""));}
  }
  lines.push("","Введённые результаты");
  for(const [id,v] of Object.entries(state.responses))lines.push((id.startsWith("Д") ? "Д · "+id.slice(1)+" · потребность, шт." : ({"А0":"А · товаров","А1":"А · папок","А2":"А · цен","А3":"А · изображений","А4":"А · остаток, шт.","В0":"В · исходных карточек","В1":"В · добавлено при первом импорте","В2":"В · связей после второй загрузки","В3":"В · добавлено при второй загрузке"}[id] || id))+" = "+v);
  if(state.talkMs)lines.push("Завершённое выступление: "+(state.talkMs/1000).toFixed(1)+" сек.");
  const link=node("a");link.href=URL.createObjectURL(new Blob([lines.join("\n")],{type:"text/plain;charset=utf-8"}));
  link.download="ОфисПро-самопроверка.txt";link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
}
async function boot(){
  const response=await fetch("/modules.json");if(!response.ok)throw Error("Не удалось загрузить критерии.");
  modules=await response.json();
  for(const m of modules){
    const b=node("button",m.code+" · "+m.title);b.dataset.code=m.code;
    b.onclick=()=>{location.hash=encodeURIComponent(m.code);};$("modules").append(b);
  }
  const selected=()=>modules.find(m=>encodeURIComponent(m.code)===location.hash.slice(1))||modules[0];
  window.onhashchange=()=>show(selected());
  $("export").onclick=report;show(selected());
}
boot().catch(e=>{$("saved").textContent=e.message;});
