/* 元アプリ app.py の HEAD にあるスクリプト（お気に入り・絞り込み・折りたたみ・コピー）。tools/export_ui.py が書き出す。
   変更点: (1) お気に入りの変更を Gradio ではなく静的版の画面（window.tjFavChanged）に知らせる
   (2) tjCopy は元アプリでは plan.js の同名関数に上書きされ、結果画面の「共有リンクをコピー」が動かなかった。文字列なら共有リンク、要素なら plan.js の処理に振り分ける */
(function(){
var FAV=[];try{FAV=JSON.parse(localStorage.getItem('tj_favs')||'[]')}catch(e){}
function has(r,s){for(var i=0;i<FAV.length;i++){if(FAV[i][0]===r&&FAV[i][1]===s)return i}return -1}
function mark(){var a=document.querySelectorAll('.star');for(var i=0;i<a.length;i++){a[i].classList.toggle('on',has(a[i].dataset.reg,a[i].dataset.sp)>=0)}}
function push(){try{localStorage.setItem('tj_favs',JSON.stringify(FAV))}catch(e){}
 if(window.tjFavChanged)window.tjFavChanged(FAV.slice());return true}
window.tjFav=function(b){var i=has(b.dataset.reg,b.dataset.sp);if(i>=0)FAV.splice(i,1);else FAV.push([b.dataset.reg,b.dataset.sp]);mark();push()};
window.tjFavClear=function(){FAV=[];mark();push()};
var tm2=null;new MutationObserver(function(){clearTimeout(tm2);tm2=setTimeout(mark,60)}).observe(document.documentElement,{childList:true,subtree:true});
var tries=0,iv=setInterval(function(){tries++;if(push()||tries>60)clearInterval(iv)},500);
function fb(t){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(a)}
function copyText(t,b){var done=function(){if(b&&b.dataset.ok){var old=b.textContent;b.textContent=b.dataset.ok;setTimeout(function(){b.textContent=old},1800)}};
 if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done,function(){fb(t);done()})}else{fb(t);done()}}
var _planCopy=window.tjCopy;window.tjCopy=function(q,b){if(typeof q!=='string')return _planCopy&&_planCopy(q);copyText(location.origin+location.pathname+q,b)};
window.tjCopyList=function(b){var o=[];document.querySelectorAll('.pg section.cat').forEach(function(s){var h=s.querySelector('h3');o.push('■ '+(h?h.dataset.rg||'':''));s.querySelectorAll('.spot .nm').forEach(function(n){o.push('・'+n.textContent)});o.push('')});copyText(o.join('\n'),b)};
window.tjFold=function(h,open){var s=h&&h.closest('section');if(!s)return;if(open){s.classList.add('open');s.dataset.auto='';s.scrollIntoView({behavior:'smooth',block:'start'})}else{s.classList.toggle('open');s.dataset.auto=''}};
window.tjGen=function(b){var sec=b.closest('section');if(!sec)return;sec.dataset.g=b.dataset.g;sec.querySelectorAll('.ngb').forEach(function(x){var o=x===b;x.classList.toggle('on',o);x.setAttribute('aria-pressed',o)});
 if(b.closest('.pg')&&b.closest('.pg').querySelector('.f-q'))tjFilter(b);else sec.querySelectorAll('.spot').forEach(function(r){r.classList.toggle('hide',!!b.dataset.g&&r.dataset.g!==b.dataset.g)})};
window.tjFilter=function(el){var pg=el.closest('.pg');if(!pg)return;
 var fnw=pg.querySelector('.f-new'),nw=fnw?(fnw.type==='checkbox'?fnw.checked:fnw.value==='new'):false,off=(pg.querySelector('.f-off')||{}).checked,q=pg.querySelector('.f-q').value.trim().toLowerCase(),mode=pg.querySelector('.f-sort').value,cat=(pg.querySelector('.f-cat')||{}).value||'',shown=0;
 pg.querySelectorAll('section.cat').forEach(function(sec){var box=sec.querySelector('.spots');var rows=[].slice.call(box.querySelectorAll('.spot'));
  rows.sort(function(a,b){if(mode==='name'){return a.dataset.nm<b.dataset.nm?-1:(a.dataset.nm>b.dataset.nm?1:0)}
   if(mode==='off'){var d=(+b.dataset.off)-(+a.dataset.off);if(d)return d}
   return (+a.dataset.i)-(+b.dataset.i)});
  var n=0,gen=sec.dataset.g||'',catok=(!cat||sec.id==='cat-'+cat);rows.forEach(function(r){box.appendChild(r);var ok=catok&&(!gen||r.dataset.g===gen)&&(!off||r.dataset.off==='1')&&(!nw||r.dataset.new==='1')&&(!q||r.dataset.nm.indexOf(q)>=0);r.classList.toggle('hide',!ok);if(ok)n++});
  sec.classList.toggle('hide',!n);if(sec.classList.contains('fold')){if((q||cat||nw)&&n)sec.classList.add('open');else if(!q&&!cat&&!nw&&sec.dataset.auto)sec.classList.remove('open');sec.dataset.auto=(q||cat||nw)?'1':''}var em=sec.querySelector('h3 em');if(em&&em.dataset.t)em.textContent=em.dataset.t.replace('{n}',n);shown+=n});
 var c=pg.querySelector('.f-n');if(c)c.textContent=c.dataset.t.replace('{n}',shown);var z=pg.querySelector('.f-none');if(z)z.classList.toggle('on',shown===0)};
})();