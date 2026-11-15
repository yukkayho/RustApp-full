(function () {
  "use strict";
  function authHeaders() {
    var token = localStorage.getItem("token") || localStorage.getItem("access_token") || "";
    try { token = JSON.parse(token); } catch (_) {}
    return {"Content-Type":"application/json", Accept:"application/json", Authorization:/^Bearer /.test(token)?token:"Bearer "+token};
  }
  function savedSettings(method, url, status, data) {
    if (!/^(PUT|POST|PATCH)$/i.test(method) || status < 200 || status >= 300) return;
    var path;
    try { path = new URL(url, location.href).pathname; } catch (_) { return; }
    if (!/^\/(court(?:\/options|\/discord)?|court-discord(?:\/[^/]+\/toggle)?|court-autokick(?:\/[^/]+)?|auto-kick(?:\/[^/]+)?|webhook|court-api(?:\/(?:toggle|public-api-routes|regenerate))?|project(?:\/[^/]+(?:\/general)?)?|players\/[^/]+\/settings-auto-kick)$/.test(path)) return;
    if (data && (data.error || data.ok === false)) return;
    if (window.__checkappToast) window.__checkappToast('success','Изменения сохранены',{title:'Готово'});
  }
  // Notify once the actual save completes; never on polling or failed requests.
  var fetchSave = window.fetch;
  window.fetch = function(input, options) {
    var method = (options && options.method) || (input && input.method) || 'GET';
    var url = (input && input.url) || input;
    return fetchSave.apply(this, arguments).then(function(res) {
      if (/^(PUT|POST|PATCH)$/i.test(method)) res.clone().json().then(function(data){savedSettings(method,url,res.status,data);}).catch(function(){});
      return res;
    });
  };
  var xhrOpen = XMLHttpRequest.prototype.open, xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method,url) {
    this.__rcSaveRequest = {method:method,url:url};
    return xhrOpen.apply(this,arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    var xhr=this, req=this.__rcSaveRequest;
    if (req && /^(PUT|POST|PATCH)$/i.test(req.method)) this.addEventListener('load',function(){
      var data;
      try { data = xhr.responseType === 'json' ? xhr.response : JSON.parse(xhr.responseText); } catch (_) { return; }
      savedSettings(req.method,req.url,xhr.status,data);
    },{once:true});
    return xhrSend.apply(this,arguments);
  };
  function registration() {
    if (sessionStorage.getItem("rc-complete-registration") !== "1" || !document.body || document.getElementById("rc-registration")) return;
    var root = document.createElement("div");root.id="rc-registration";root.className="rc-registration-overlay";
    root.innerHTML='<form class="rc-registration-card"><h2>Завершите регистрацию</h2><p>Выберите имя и уникальный юзернейм</p><label>Имя<input name="name" required minlength="2" maxlength="40" autocomplete="name"></label><label>Имя пользователя<div class="rc-handle-input"><span>@</span><input name="tag" required minlength="3" maxlength="24" pattern="[a-zA-Z0-9_]+" autocomplete="username"></div></label><p class="rc-registration-error" role="alert"></p><button type="submit">Сохранить и продолжить</button></form>';
    document.body.appendChild(root);
    root.querySelector('input').focus();
    root.querySelector('form').addEventListener('submit',async function(e){
      e.preventDefault();var form=e.currentTarget,button=form.querySelector('button'),error=form.querySelector('[role="alert"]');button.disabled=true;error.textContent="";
      try {
        var res=await fetch('/client/profile',{method:'PUT',credentials:'include',headers:authHeaders(),body:JSON.stringify({name:form.elements.name.value.trim(),tag:form.elements.tag.value.trim().toLowerCase()})});
        var data=await res.json();if(!res.ok || data.ok===false || data.error)throw new Error(data.message||data.error||'Не удалось сохранить профиль');
        sessionStorage.removeItem('rc-complete-registration');root.remove();location.reload();
      }catch(err){error.textContent=err.message;button.disabled=false;}
    });
  }
  var freezeHistory = new Map();
  function rememberFreeze(item) {
    if(item && item.type==='FreezeChanged') freezeHistory.set(String(item.check_id)+':'+String(item.id),item);
    drawFreezeHistory();
  }
  function placeFreezeRow(list,node,item,time) {
      var reversed=list.classList.contains('reversed');
      var target=Array.from(list.children).find(function(n){
        if(n===node || !n.classList.contains('activity-item'))return false;
        var value=n.dataset.rcFreezeCreated;
        var clock=n.firstElementChild && n.firstElementChild.textContent;
        if(value)return reversed?Number(value)<item.created_at:Number(value)>item.created_at;
        return clock && (reversed?clock<time:clock>time);
      });
      node.dataset.rcFreezeCreated=String(item.created_at);
      if(target){if(node.nextElementSibling!==target)list.insertBefore(node,target);}else if(list.lastElementChild!==node)list.appendChild(node);
  }
  function drawFreezeHistory() {
    var match=location.pathname.match(/\/checks\/(\d+)/), list=document.querySelector('.activity');
    if(!match || !list)return;
    var cid=match[1];
    freezeHistory.forEach(function(item,key){
      if(String(item.check_id)!==cid)return;
      var active=!!item.meta.active, title=active?'\u0418\u0433\u0440\u043e\u043a \u0437\u0430\u043c\u043e\u0440\u043e\u0436\u0435\u043d':'\u0418\u0433\u0440\u043e\u043a \u0440\u0430\u0437\u043c\u043e\u0440\u043e\u0436\u0435\u043d';
      var subtitle=active?'\u0421\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u043a \u0437\u0430\u043c\u043e\u0440\u043e\u0437\u0438\u043b \u0438\u0433\u0440\u043e\u043a\u0430':'\u0421\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u043a \u0440\u0430\u0437\u043c\u043e\u0440\u043e\u0437\u0438\u043b \u0438\u0433\u0440\u043e\u043a\u0430';
      var time=new Date(item.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
      var nodes=Array.from(list.querySelectorAll('.activity-item'));
      var custom=nodes.find(function(n){return n.dataset.rcFreezeEvent===key;});
      var native=nodes.find(function(n){return !n.dataset.rcFreezeEvent && n.querySelector('.title') && n.querySelector('.title').textContent===title && n.firstElementChild && n.firstElementChild.textContent===time;});
      if(native){if(custom)custom.remove();return;}
      if(custom){placeFreezeRow(list,custom,item,time);return;}
      var template=nodes.find(function(n){return !n.dataset.rcFreezeEvent && n.querySelector('.title') && n.querySelector('.subtitle') && n.querySelector('.point-box');});
      if(!template)return;
      var node=template.cloneNode(true);node.dataset.rcFreezeEvent=key;
      node.querySelector('.title').textContent=title;node.querySelector('.subtitle').textContent=subtitle;
      var content=node.querySelector('.content'), heading=node.querySelector('.title').parentElement;
      if(heading!==content)Array.from(heading.children).forEach(function(n){if(!n.classList.contains('title')&&!n.classList.contains('subtitle'))n.remove();});
      Array.from(content.children).forEach(function(n){if(n!==heading && !n.classList.contains('title')&&!n.classList.contains('subtitle'))n.remove();});
      node.firstElementChild.textContent=time;node.firstElementChild.title=new Date(item.created_at).toLocaleString('ru-RU');
      node.querySelector('.circle').className='circle bg-grey-1000 !border-grey-300'+(active?'':' border-dotted');
      placeFreezeRow(list,node,item,time);
    });
  }
  function freezeButton() {
    var match=location.pathname.match(/\/checks\/(\d+)/), old=document.getElementById('rc-check-freeze');
    if (!match) {if(old)old.remove();return;}
    var cid=match[1];
    if(old && old.dataset.checkId===cid)return;
    if(old)old.remove();
    var notice=Array.from(document.querySelectorAll('button')).find(function(b){return /(?:показать|скрыть|убрать).*табличку|show.*notice|hide.*notice/i.test(b.textContent);});
    if(!notice)return;
    var b=document.createElement('button');b.className=notice.className;b.id='rc-check-freeze';b.dataset.checkId=cid;b.type='button';b.textContent='Freeze';b.style.marginLeft='6px';notice.insertAdjacentElement('afterend',b);
    var active=false;
    function render(data){active=!!data.active;b.textContent=active?'UnFreeze':'Freeze';b.setAttribute('aria-pressed',String(active));}
    function request(value){return fetch('/check/'+cid+'/freeze-state',{method:value===undefined?'GET':'PUT',credentials:'include',headers:authHeaders(),body:value===undefined?undefined:JSON.stringify({active:value})}).then(async function(r){var d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Не удалось отправить команду');return d;});}
    fetch('/check/'+cid+'/activity',{credentials:'include',headers:authHeaders()}).then(function(r){return r.json();}).then(function(rows){(Array.isArray(rows)?rows:[]).forEach(rememberFreeze);}).catch(function(){});
    b.disabled=true;request().then(render).catch(function(){b.remove();}).finally(function(){b.disabled=false;});
    b.addEventListener('click',async function(e){e.preventDefault();e.stopPropagation();b.disabled=true;try{var d=await request(!active);render(d);var item=d.activity;if(!item){item={id:'freeze-'+cid+'-'+Date.now(),check_id:Number(cid),checkId:Number(cid),type:'FreezeChanged',kind:'FreezeChanged',created_at:Date.now(),meta:{action:'freeze',active:active,client_id:0,error:false}};}if(window.__checkappPublishFreezeActivity)window.__checkappPublishFreezeActivity(item);rememberFreeze(item);}catch(e){if(window.__checkappToast)window.__checkappToast('error',e.message);}finally{b.disabled=false;}});
  }
  function update() {
    var path=location.pathname;
    if (/\/integrations\/?$/.test(path) && new URLSearchParams(location.search).get('section') === 'rcc') {
      var app=document.querySelector('#app');var router=app && app.__vue_app__ && app.__vue_app__.config.globalProperties.$router;
      if (router && router.currentRoute.value.path === path) router.replace({path:path,query:Object.assign({},router.currentRoute.value.query,{section:'webhook'})});
    }
    document.documentElement.classList.toggle('rc-project-settings-page',/\/settings\/about\/?$/.test(path));
    document.documentElement.classList.toggle('rc-servers-page',/\/servers\/?$/.test(path));
    document.documentElement.classList.toggle('rc-billing-page',/\/(billing|payments)(\/|$)/.test(path));
    document.querySelectorAll('.layout-page .header button.ra-button').forEach(function(b){
      if(b.textContent.trim() || !b.querySelector('svg') || b.dataset.rcFilter) return;
      b.dataset.rcFilter='1';b.classList.add('rc-filter-trigger');b.setAttribute('aria-label','Фильтры');b.title='Фильтры';var svg=b.querySelector('svg');svg.setAttribute('viewBox','0 0 24 24');svg.innerHTML='<path d="M4 6h16v2H4zM7 11h10v2H7zM10 16h4v2h-4z"/>';
    });
    // Remove RCC entry points, including player menu links and check options.
    document.querySelectorAll('a[href*="rustcheatcheck"],a[href*="rust-cheat-check"],a[href*="rcc"], [data-rc-rcc]').forEach(function(n){n.hidden=true;});
    document.querySelectorAll('.player-modal button,.player-modal a,.player-modal label,.n-dropdown-option-body').forEach(function(n){
      if(/\bRCC\b|rust[\s_-]*cheat[\s_-]*check/i.test(n.textContent)){n.hidden=true;n.setAttribute('data-rc-rcc','1');}
    });
    if (/\/integrations\/?$/.test(path)) {
      document.querySelectorAll('.tabbed-navigation > .header > .element,[role="tab"]').forEach(function(n){
        if (/^(?:RCC|rust[\s_-]*cheat[\s_-]*check)$/i.test(n.textContent.trim())) n.setAttribute('data-rc-rcc','1');
      });
    }
    registration();
    freezeButton();
    drawFreezeHistory();
  }
  var queued=false;
  function schedule(){if(queued)return;queued=true;requestAnimationFrame(function(){queued=false;update();});}
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('popstate',schedule);
  document.addEventListener('click',function(){setTimeout(schedule,0);});
  update();
})();
