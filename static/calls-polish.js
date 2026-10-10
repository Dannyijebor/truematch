// ===== Calls polish v2 =====
(function(){
'use strict';
function debounceEnd(){
  if (typeof window.tmEndCall !== 'function') { return setTimeout(debounceEnd, 300); }
  if (window.tmEndCall._deb) return;
  var o = window.tmEndCall;
  var fn = function(){
    if (fn._busy) return;
    fn._busy = true;
    try { o.apply(this, arguments); } finally { setTimeout(function(){ fn._busy = false; }, 1500); }
  };
  fn._deb = true;
  window.tmEndCall = fn;
}
setTimeout(debounceEnd, 300);
})();

window.tmEnsureVideoPip = function(){
  var pip = document.getElementById('tm-video-pip');
  if (pip) return pip;
  pip = document.createElement('div');
  pip.id = 'tm-video-pip';
  pip.className = 'tm-video-pip';
  var html = '';
  html += '<video id="tm-pip-remote-video" autoplay playsinline></video>';
  html += '<div class="tm-pip-scrim"></div>';
  html += '<div class="tm-pip-header">';
  html += '<div class="tm-pip-name" id="tm-pip-name">Call</div>';
  html += '<div class="tm-pip-time" id="tm-pip-time">00:00</div>';
  html += '</div>';
  html += '<div class="tm-pip-controls">';
  html += '<button class="tm-pip-btn" id="tm-pip-mute" type="button"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/></svg></button>';
  html += '<button class="tm-pip-btn tm-pip-end" id="tm-pip-end" type="button"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.28-.7.28-.28 0-.53-.11-.71-.29L.29 13.08c-.18-.17-.29-.42-.29-.7 0-.28.11-.53.29-.71C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.7l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.1-.7-.28-.79-.73-1.68-1.36-2.66-1.85-.33-.16-.56-.51-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/></svg></button>';
  html += '</div>';
  pip.innerHTML = html;
  document.body.appendChild(pip);
  var mb = pip.querySelector('#tm-pip-mute');
  if (mb) mb.addEventListener('click', function(e){ e.stopPropagation(); try { window.tmToggleMute(); } catch(_){}});
  var eb = pip.querySelector('#tm-pip-end');
  if (eb) eb.addEventListener('click', function(e){ e.stopPropagation(); try { window.tmEndCall(); } catch(_){}});
  try {
    var s = JSON.parse(localStorage.getItem('tm_pip_pos') || 'null');
    if (s && typeof s.x === 'number') { pip.style.left = s.x + 'px'; pip.style.top = s.y + 'px'; pip.style.right = 'auto'; pip.style.bottom = 'auto'; }
    else { pip.style.right = '12px'; pip.style.bottom = '96px'; }
  } catch(_) { pip.style.right = '12px'; pip.style.bottom = '96px'; }
  return pip;
};

window.tmWirePipDrag = function(pip){
  if (!pip || pip._dragWired) return;
  pip._dragWired = true;
  var d = { active:false, sx:0, sy:0, ox:0, oy:0, moved:false };
  function down(ev){
    if (ev.target.closest && ev.target.closest('.tm-pip-btn')) return;
    var pt = ev.touches ? ev.touches[0] : ev;
    var r = pip.getBoundingClientRect();
    d.active = true; d.moved = false;
    d.ox = r.left; d.oy = r.top; d.sx = pt.clientX; d.sy = pt.clientY;
    pip.style.left = r.left + 'px'; pip.style.top = r.top + 'px';
    pip.style.right = 'auto'; pip.style.bottom = 'auto';
    pip.classList.add('tm-dragging');
    if (ev.cancelable) ev.preventDefault();
  }
  function move(ev){
    if (!d.active) return;
    var pt = ev.touches ? ev.touches[0] : ev;
    var dx = pt.clientX - d.sx, dy = pt.clientY - d.sy;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
    var mx = window.innerWidth - pip.offsetWidth - 6;
    var my = window.innerHeight - pip.offsetHeight - 6;
    var nx = Math.max(6, Math.min(mx, d.ox + dx));
    var ny = Math.max(6, Math.min(my, d.oy + dy));
    pip.style.left = nx + 'px'; pip.style.top = ny + 'px';
    if (ev.cancelable) ev.preventDefault();
  }
  function up(){
    if (!d.active) return;
    d.active = false;
    pip.classList.remove('tm-dragging');
    var r = pip.getBoundingClientRect();
    var cx = r.left + r.width / 2;
    var goR = cx > window.innerWidth / 2;
    var tx = goR ? (window.innerWidth - r.width - 12) : 12;
    var ty = Math.max(70, Math.min(window.innerHeight - r.height - 12, r.top));
    pip.style.left = tx + 'px'; pip.style.top = ty + 'px';
    try { localStorage.setItem('tm_pip_pos', JSON.stringify({x:tx, y:ty})); } catch(_){}
  }
  pip.addEventListener('mousedown', down);
  pip.addEventListener('touchstart', down, { passive:false });
  document.addEventListener('mousemove', move);
  document.addEventListener('touchmove', move, { passive:false });
  document.addEventListener('mouseup', up);
  document.addEventListener('touchend', up);
  pip.addEventListener('click', function(e){
    if (e.target.closest && e.target.closest('.tm-pip-btn')) return;
    if (d.moved) return;
    try { window.tmExpandCall(); } catch(_){}
  });
};

window.tmSyncMuteUI = function(){
  var st = window.tmState || {};
  var muted = !!st.micMuted;
  var p = document.getElementById('tm-call-pill');
  if (p) p.classList.toggle('tm-muted', muted);
  var pmb = document.getElementById('tm-pill-mute');
  if (pmb) pmb.classList.toggle('tm-mute-on', muted);
  var vp = document.getElementById('tm-video-pip');
  if (vp) vp.classList.toggle('tm-muted', muted);
  var vmb = document.getElementById('tm-pip-mute');
  if (vmb) vmb.classList.toggle('tm-mute-on', muted);
  var fmb = document.getElementById('tm-btn-mute');
  if (fmb) fmb.classList.toggle('tm-mute-on', muted);
};

(function(){
  function wrap(){
    if (typeof window.showInCall !== 'function' || window.showInCall._pol) return false;
    var o = window.showInCall;
    var fn = function(name, kind){
      var r = o.apply(this, arguments);
      var isV = (kind === 'video');
      var ap = document.getElementById('tm-call-pill');
      if (isV) {
        var vp = window.tmEnsureVideoPip();
        window.tmWirePipDrag(vp);
        var vn = vp.querySelector('#tm-pip-name'); if (vn) vn.textContent = name || 'Call';
        var vt = vp.querySelector('#tm-pip-time'); if (vt) vt.textContent = '00:00';
        try { var st = window.tmState || {}; var rv = vp.querySelector('#tm-pip-remote-video'); if (rv && st.remoteStream) rv.srcObject = st.remoteStream; } catch(_){}
        vp.classList.add('tm-show');
        if (ap) ap.classList.add('tm-video-active');
      } else {
        var vp2 = document.getElementById('tm-video-pip');
        if (vp2) vp2.classList.remove('tm-show');
        if (ap) ap.classList.remove('tm-video-active');
      }
      setTimeout(window.tmSyncMuteUI, 60);
      return r;
    };
    fn._pol = true;
    window.showInCall = fn;
    return true;
  }
  if (!wrap()) { var t = setInterval(function(){ if (wrap()) clearInterval(t); }, 400); }
})();

setInterval(function(){
  var vp = document.getElementById('tm-video-pip');
  if (!vp || !vp.classList.contains('tm-show')) { window.tmSyncMuteUI(); return; }
  var st = window.tmState || {};
  try { var rv = vp.querySelector('#tm-pip-remote-video'); if (rv && st.remoteStream && rv.srcObject !== st.remoteStream) rv.srcObject = st.remoteStream; } catch(_){}
  var vt = vp.querySelector('#tm-pip-time');
  if (vt && st.connectedAt) {
    var sec = Math.floor((Date.now() - st.connectedAt) / 1000);
    var mm = String(Math.floor(sec / 60)).padStart(2, '0');
    var ss = String(sec % 60).padStart(2, '0');
    vt.textContent = mm + ':' + ss;
  }
  window.tmSyncMuteUI();
}, 1000);

(function(){
  function wrap2(){
    if (typeof window.tmCleanupCall !== 'function' || window.tmCleanupCall._pol) return false;
    var o = window.tmCleanupCall;
    var fn = function(){
      var vp = document.getElementById('tm-video-pip');
      if (vp) vp.classList.remove('tm-show', 'tm-muted', 'tm-dragging');
      var ap = document.getElementById('tm-call-pill');
      if (ap) ap.classList.remove('tm-video-active', 'tm-muted');
      return o.apply(this, arguments);
    };
    fn._pol = true;
    window.tmCleanupCall = fn;
    return true;
  }
  if (!wrap2()) { var t = setInterval(function(){ if (wrap2()) clearInterval(t); }, 400); }
})();
