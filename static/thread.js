(function(){
"use strict";

// Pull values from the inline TM_INIT set by Jinja
var OTHER_ID = (window.TM_INIT && window.TM_INIT.otherId) || "";
var OTHER_NAME = (window.TM_INIT && window.TM_INIT.otherName) || "";
var OTHER_AVATAR = (window.TM_INIT && window.TM_INIT.otherAvatar) || "";
var CHAT_THEME = (window.TM_INIT && window.TM_INIT.chatTheme) || "executive";
var LAST_MSG_AT = (window.TM_INIT && window.TM_INIT.lastMsgAt) || "";
var OTHER_USERNAME = (window.TM_INIT && window.TM_INIT.otherUsername) || "";
var USER_ID = (window.TM_INIT && window.TM_INIT.userId) || "";


// ---------- Voice player (single clean implementation) ----------
var _tmAudio = null, _tmAudioBtn = null;
var _PLAY_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
var _PAUSE_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>';

function tmToggleVoice(btn, url) {
  console.log('[voice] tap', url);
  try {
    if (!url) { alert('No URL'); return; }
    if (_tmAudio && _tmAudioBtn === btn) {
      if (_tmAudio.paused) {
        _tmAudio.play().then(function(){ btn.innerHTML = _PAUSE_SVG; });
      } else {
        _tmAudio.pause();
        btn.innerHTML = _PLAY_SVG;
      }
      return;
    }
    if (_tmAudio) {
      try { _tmAudio.pause(); _tmAudio.remove(); } catch(_){}
      if (_tmAudioBtn) _tmAudioBtn.innerHTML = _PLAY_SVG;
    }
    var a = document.createElement('audio');
    a.src = url;
    a.preload = 'auto';
    a.setAttribute('playsinline', '');
    a.setAttribute('webkit-playsinline', '');
    a.style.display = 'none';
    document.body.appendChild(a);
    _tmAudio = a;
    _tmAudioBtn = btn;
    a.onended = function(){ btn.innerHTML = _PLAY_SVG; };
    a.onerror = function(){
      var code = a.error ? a.error.code : '?';
      alert('Audio failed (code ' + code + ')');
      btn.innerHTML = _PLAY_SVG;
    };
    a.play().then(function(){
      btn.innerHTML = _PAUSE_SVG;
    }).catch(function(e){
      alert('Play blocked: ' + (e.message || e.name));
    });
  } catch(err) {
    alert('Voice player error: ' + err.message);
  }
}

const ME_ID = "window.TM_INIT.userId";
let lastTs = "window.TM_INIT.lastMsgAt";
let currentTheme = "window.TM_INIT.chatTheme";
let replyTo = null;

function scrollBottom(smooth) { const c = document.getElementById('chat-messages'); if (c) c.scrollTo({top: c.scrollHeight, behavior: smooth ? 'smooth' : 'auto'}); }
scrollBottom();
function tmAutoGrow(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 100) + 'px'; }
function tmToggleSendMic() {
  var input = document.getElementById('msg-input');
  var sendBtn = document.getElementById('send-btn');
  var micBtn = document.getElementById('mic-btn');
  if (!input || !sendBtn || !micBtn) return;
  var hasText = input.value.trim().length > 0;
  sendBtn.style.display = hasText ? 'flex' : 'none';
  micBtn.style.display = hasText ? 'none' : 'flex';
}
document.addEventListener('input', function(e) {
  if (e.target && e.target.id === 'msg-input') tmToggleSendMic();
});
document.addEventListener('keyup', function(e) {
  if (e.target && e.target.id === 'msg-input') tmToggleSendMic();
});
document.addEventListener('paste', function(e) {
  if (e.target && e.target.id === 'msg-input') setTimeout(tmToggleSendMic, 20);
});
setTimeout(tmToggleSendMic, 200);

function tmSetReply(msgId, preview, mine) {
  replyTo = msgId;
  document.getElementById('reply-bar-name').textContent = mine ? 'You' : OTHER_NAME;
  document.getElementById('reply-bar-text').textContent = preview;
  document.getElementById('reply-bar').classList.add('active');
}
function tmCancelReply() { replyTo = null; document.getElementById('reply-bar').classList.remove('active'); }

async function tmSend(payload) {
  payload.to = OTHER_ID;
  if (replyTo) payload.reply_to_id = replyTo;
  const r = await fetch('/api/chat/send', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await r.json();
  if (data.ok) {
      var sentReply = null;
      if (replyTo) {
        var _row = document.querySelector('[data-msg-id="' + replyTo + '"]');
        if (_row) {
          var _previewEl = _row.querySelector('.msg-text, .voice-time, .sticker-emoji');
          var _preview = _row.dataset.body || (_previewEl ? _previewEl.textContent : '[media]');
          sentReply = { id: replyTo, preview: (_preview||'').substring(0,80), from_me: _row.classList.contains('mine') };
        }
      }
      var msg = data.message || {};
      if (sentReply && !msg.reply) msg.reply = sentReply;
      tmAppendMessage(msg);
      tmCancelReply();
      lastTs = msg.created_at;
      return true;
    }
  alert(data.error || 'Send failed');
  return false;
}
function tmOnSendBtn(e) {
  e.preventDefault();
  try { if (window.tmSound && window.tmSound._unlock) window.tmSound._unlock(); } catch(_){}
  const input = document.getElementById('msg-input');
  const body = input.value.trim();
  if (!body) return;
  input.value = ''; input.style.height = 'auto'; tmToggleSendMic();
  tmSend({ kind: 'text', body });
  try { if (window.TMSound) TMSound.send(); if (window.TMHaptic) TMHaptic.send(); } catch(_){}
}
document.getElementById('msg-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); tmOnSendBtn(e); }
});

function tmRenderBubble(m) {
  const isMine = m.from_me;
  const replyHTML = m.reply ? `<div class="bubble-reply"><div class="bubble-reply-name">${m.reply.from_me ? 'You' : OTHER_NAME}</div><div class="bubble-reply-text">${(m.reply.preview||'').replace(/</g,'&lt;')}</div></div>` : '';
  let contentHTML = '';
  if (m.kind === 'image') contentHTML = `<img src="${m.media_url}" class="msg-media" onclick="tmLightbox('${m.media_url}')" alt="">`;
  else if (m.kind === 'voice') {
    const dur = Math.round(m.media_duration || 0);
    let wave = ''; for (let i = 0; i < 28; i++) wave += `<span style="height:${6 + (i*5)%12}px"></span>`;
    contentHTML = `<div class="voice-player"><div class="voice-play" data-url="${m.media_url}" onclick="tmToggleVoice(this, '${m.media_url}')"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></div><div class="voice-wave">${wave}</div><span class="voice-time">${dur}s</span></div>`;
  } else if (m.kind === 'sticker') {
    contentHTML = (m.media_url && m.media_url.startsWith('http')) ? `<img src="${m.media_url}" class="sticker-img">` : `<span class="sticker-emoji">${m.body || m.media_url || '🙂'}</span>`;
  } else contentHTML = `<span class="msg-text">${(m.body||'').replace(/</g,'&lt;')}</span>`;
  const ticksHTML = isMine ? `<span class="tick ${m.read ? 'read' : (m.delivered ? 'delivered' : 'pending')}"><svg class="tick-a" viewBox="0 0 13 11" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1 6l3.5 3.5L11 3"/></svg><svg class="tick-b" viewBox="0 0 13 11" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1 6l3.5 3.5L11 3"/></svg></span>` : '';
  return `<div class="bubble ${isMine ? 'mine' : 'theirs'}" data-bubble-id="${m.id}">${replyHTML}${contentHTML}<div class="msg-meta"><span>${(m.created_at || '').substring(11, 16)}</span>${ticksHTML}</div></div>`;
}
function tmAppendMessage(m) {
  const chat = document.getElementById('chat-messages');
  const row = document.createElement('div');
  var prev = chat.lastElementChild;
  var curDate = (m.created_at || '').substring(0, 10);
  var prevDate = prev ? (prev.dataset.createdAt || '').substring(0, 10) : '';
  var firstDay = curDate && curDate !== prevDate;
  row.className = 'msg-row ' + (m.from_me ? 'mine' : 'theirs') + ' ' + (m.from_me ? 'just-sent' : 'just-received') + (firstDay ? ' first-of-day' : '');
  row.dataset.msgId = m.id;
  row.dataset.kind = m.kind;
  row.dataset.body = m.body;
  row.dataset.createdAt = m.created_at || '';
  row.innerHTML = tmRenderBubble(m);
  chat.appendChild(row);
  setTimeout(() => row.classList.remove('just-sent', 'just-received'), 700);
  scrollBottom(true);
}
async function tmPoll() {
  try {
    const url = '/api/messages/' + OTHER_ID + '/poll' + (lastTs ? '?since=' + encodeURIComponent(lastTs) : '');
    const r = await fetch(url, {credentials: 'same-origin'});
    if (r.ok) {
      const data = await r.json();
      for (const m of data.messages || []) {
        const existing = document.querySelector('[data-msg-id="' + m.id + '"]');
        if (!existing) { tmAppendMessage(m); if (!m.from_me) { try { if (window.TMSound) TMSound.receive(); if (window.TMHaptic) TMHaptic.receive(); } catch(_){} } }
        else if (m.from_me) {
          const tick = existing.querySelector('.tick');
          if (tick && m.delivered && !tick.classList.contains('read') && tick.classList.contains('pending')) {
            tick.classList.remove('pending');
            tick.classList.add('delivered', 'tick-fresh');
            setTimeout(() => tick.classList.remove('tick-fresh'), 850);
          }
          if (tick && m.read && !tick.classList.contains('read')) {
            tick.classList.add('read', 'tick-fresh');
            setTimeout(() => tick.classList.remove('tick-fresh'), 850);
          }
        }
        if (m.created_at) lastTs = m.created_at;
      }
    }
  } catch (e) {}
  setTimeout(tmPoll, 2000);
}
tmPoll();

let mediaRecorder = null, audioChunks = [], recStart = 0, recTimer = null, recording = false;
let activeStream = null, currentBlob = null;
let recHoldTimer = null, recCancelling = false, recLocked = false, recLockPending = false;
let recPaused = false;
let recPausedTotal = 0;  // total ms spent paused
let recPausedAt = 0;     // timestamp when pause began
let recPointerId = null, recStartY = 0, recStartX = 0;
let recAudioCtx = null, recAnalyser = null, recWaveRAF = null;

let recDocListenersAttached = false;

function tmAttachDocListeners() {
  if (recDocListenersAttached) return;
  recDocListenersAttached = true;
  document.addEventListener('pointermove', tmMicMove, { passive: false });
  document.addEventListener('pointerup', tmMicUp, { passive: false });
  document.addEventListener('pointercancel', tmMicUp, { passive: false });
  document.addEventListener('touchmove', tmMicMove, { passive: false });
  document.addEventListener('touchend', tmMicUp, { passive: false });
  document.addEventListener('touchcancel', tmMicUp, { passive: false });
  document.addEventListener('mousemove', tmMicMove);
  document.addEventListener('mouseup', tmMicUp);
}

function tmDetachDocListeners() {
  if (!recDocListenersAttached) return;
  recDocListenersAttached = false;
  document.removeEventListener('pointermove', tmMicMove);
  document.removeEventListener('pointerup', tmMicUp);
  document.removeEventListener('pointercancel', tmMicUp);
  document.removeEventListener('touchmove', tmMicMove);
  document.removeEventListener('touchend', tmMicUp);
  document.removeEventListener('touchcancel', tmMicUp);
  document.removeEventListener('mousemove', tmMicMove);
  document.removeEventListener('mouseup', tmMicUp);
}

function tmMicDown(e) {
  e.preventDefault(); e.stopPropagation();
  try { if (window.tmSound && window.tmSound._unlock) window.tmSound._unlock(); } catch(_){}
  if (recording && recLocked) return;
  if (recording) { tmRecSend(e); return; }

  const p = tmPointerPoint(e);
  recPointerId = (e.pointerId != null) ? e.pointerId : null;
  recStartX = p.x;
  recStartY = p.y;

  recCancelling = false;
  recLockPending = false;

  const cur = document.getElementById('rec-cursor');
  const micEl0 = document.getElementById('mic-btn');
  if (cur && micEl0) {
    const mr0 = micEl0.getBoundingClientRect();
    cur.style.left = (mr0.left + mr0.width / 2) + 'px';
    cur.style.top = (mr0.top + mr0.height / 2) + 'px';
    cur.classList.remove('locked');
  }

  if (recHoldTimer) clearTimeout(recHoldTimer);
  recHoldTimer = setTimeout(() => { tmStartRecording(); }, 60);

  tmAttachDocListeners();
}

function tmPointerPoint(e) {
  if (e.touches && e.touches[0]) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
  if (e.changedTouches && e.changedTouches[0]) return { x: e.changedTouches[0].clientX, y: e.changedTouches[0].clientY };
  return { x: e.clientX || 0, y: e.clientY || 0 };
}

function tmMicMove(e) {
  if (!recording && !recHoldTimer) return;
  if (recLocked) return;

  const p = tmPointerPoint(e);
  const cur = document.getElementById('rec-cursor');
  const micEl = document.getElementById('mic-btn');
  const lockField = document.getElementById('rec-lock-field');

  // Compute lock field bounds so we can clamp the cursor
  let lockTopY = -Infinity;
  if (lockField) {
    const lr = lockField.getBoundingClientRect();
    lockTopY = lr.top + lr.height / 2;
  }

  if (cur && micEl) {
    // Cursor moves VERTICALLY only, never below start, never above lock center
    const mr = micEl.getBoundingClientRect();
    let cy = Math.min(p.y, recStartY);
    if (lockTopY > -Infinity) cy = Math.max(cy, lockTopY);
    cur.style.left = (mr.left + mr.width / 2) + 'px';
    cur.style.top = cy + 'px';
  }

  const hint = document.getElementById('rec-hint');
  const bar = document.getElementById('rec-bar');

  // Lock field center (already computed above)
  const lockCenterY = lockTopY;

  const dyFromLock = p.y - lockCenterY; // negative when finger is ABOVE lock

  // Reached lock? Fire the moment the cursor touches the lock level
  if (dyFromLock <= 8 && recording) {
    tmRecLock();
    return;
  }

  const rail = document.getElementById('rec-rail');
  // Close to lock → armed (warm flash)
  if (dyFromLock < 60 && dyFromLock > -20) {
    if (lockField) lockField.classList.add('armed');
    if (lockField) document.getElementById('rec-lock-field-text').textContent = 'Release to lock';
    if (rail) rail.classList.add('armed');
  } else {
    if (lockField) lockField.classList.remove('armed');
    if (lockField) document.getElementById('rec-lock-field-text').textContent = 'Slide up to lock';
    if (rail) rail.classList.remove('armed');
  }

  // Slide left → cancel
  const dx = p.x - recStartX;
  if (dx < -55 && !recCancelling) {
    recCancelling = true;
    if (bar) { bar.classList.add('cancelling'); }
    if (hint) hint.textContent = 'Release to cancel';
  } else if (dx > -20 && recCancelling) {
    recCancelling = false;
    if (bar) bar.classList.remove('cancelling');
    if (hint) hint.textContent = 'Release to send';
  }
}

async function tmMicUp(e) {
  var _wasPending = !!recHoldTimer;
  if (recHoldTimer) { clearTimeout(recHoldTimer); recHoldTimer = null; }
  tmDetachDocListeners();

  // If recording never started (fast tap/swipe), force-hide everything immediately
  if (_wasPending && !recording) {
    try {
      var _b = document.getElementById('rec-bar');
      if (_b) {
        _b.style.transition = 'none';
        _b.classList.remove('active', 'locked', 'paused', 'cancelling', 'lock-hint');
        setTimeout(function(){ if (_b) _b.style.transition = ''; }, 50);
      }
      var _lf = document.getElementById('rec-lock-field');
      if (_lf) { _lf.style.transition = 'none'; _lf.classList.remove('visible','armed','locked'); setTimeout(function(){ if (_lf) _lf.style.transition=''; }, 50); }
      var _cu = document.getElementById('rec-cursor');
      if (_cu) { _cu.style.transition = 'none'; _cu.classList.remove('visible','locked'); setTimeout(function(){ if (_cu) _cu.style.transition=''; }, 50); }
      var _rm = document.getElementById('rec-dim');
      if (_rm) { _rm.style.transition = 'none'; _rm.classList.remove('visible'); setTimeout(function(){ if (_rm) _rm.style.transition=''; }, 50); }
      var _rl = document.getElementById('rec-rail');
      if (_rl) { _rl.style.transition = 'none'; _rl.classList.remove('visible','armed','locked'); setTimeout(function(){ if (_rl) _rl.style.transition=''; }, 50); }
    } catch(_){}
    return;
  }

  const cur = document.getElementById('rec-cursor');
  const micEl = document.getElementById('mic-btn');

  // If locked, do NOTHING — user must tap Send or Trash
  if (recLocked) {
    recPointerId = null;
    return;
  }

  // Animate the cursor back to the mic position before hiding
  if (cur && micEl) {
    const mr = micEl.getBoundingClientRect();
    cur.style.transition = 'left 0.34s cubic-bezier(0.4, 0, 0.2, 1), top 0.34s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.28s ease 0.14s';
    cur.style.left = (mr.left + mr.width / 2) + 'px';
    cur.style.top = (mr.top + mr.height / 2) + 'px';
    setTimeout(() => {
      cur.classList.remove('visible');
      setTimeout(() => {
        cur.style.transition = '';
        cur.style.left = '';
        cur.style.top = '';
      }, 320);
    }, 340);
  }

  if (!recording) { recLockPending = false; return; }

  if (recCancelling) {
    tmRecCancelInternal();
  } else {
    tmRecSend(e);
  }

  recPointerId = null;
  recCancelling = false;

  const bar = document.getElementById('rec-bar');
  if (bar) bar.classList.remove('cancelling', 'active', 'lock-hint');
  const lockField = document.getElementById('rec-lock-field');
  if (lockField) {
    lockField.classList.remove('visible', 'armed', 'locked');
    const t = document.getElementById('rec-lock-field-text');
    if (t) t.textContent = 'Slide up to lock';
  }
}


function tmRecLock() {
  if (!recording || recLocked) return;
  recLocked = true;
  try { if (window.TMSound) TMSound.lock(); if (window.TMHaptic) TMHaptic.lock(); } catch(_){}

  const bar = document.getElementById('rec-bar');
  if (bar) bar.classList.add('locked');

  const lockField = document.getElementById('rec-lock-field');
  if (lockField) {
    lockField.classList.add('locked');
    lockField.classList.remove('armed');
    const t = document.getElementById('rec-lock-field-text');
    if (t) t.textContent = 'Locked — release to send';
  }

  const rail = document.getElementById('rec-rail');
  if (rail) { rail.classList.add('locked'); rail.classList.remove('armed'); }

  // Return cursor to MIC position and back to normal colour
  const cur = document.getElementById('rec-cursor');
  const micEl = document.getElementById('mic-btn');
  if (cur && micEl) {
    const mr = micEl.getBoundingClientRect();
    cur.style.transition = 'left 0.42s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.42s cubic-bezier(0.34, 1.56, 0.64, 1), transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.28s ease 0.18s';
    cur.style.left = (mr.left + mr.width / 2) + 'px';
    cur.style.top = (mr.top + mr.height / 2) + 'px';
    cur.classList.remove('locked');   // back to red first, so the snap reads
    setTimeout(() => {
      cur.classList.remove('visible'); // then fade out at the mic
      setTimeout(() => {
        cur.style.transition = '';
        cur.style.left = '';
        cur.style.top = '';
      }, 340);
    }, 300);
  }

  setTimeout(() => {
    if (lockField) lockField.classList.remove('visible', 'locked');
    if (rail) rail.classList.remove('visible', 'locked', 'armed');
  }, 500);

  const hint = document.getElementById('rec-hint');
  if (hint) hint.textContent = 'Tap ➤ to send';

  recCancelling = false;
}

function tmRecPauseToggle(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  if (!recording) return;

  const bar = document.getElementById('rec-bar');
  const icon = document.getElementById('rec-pause-icon');
  const label = document.querySelector('.rec-pause .rec-pause-label');

  if (!recPaused) {
    // ---------- PAUSE ----------
    // Store the exact moment pause began
    recPausedAt = Date.now();

    // Best-effort: pause the MediaRecorder (Chrome supports this)
    try { if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.pause(); } catch(_) {}

    recPaused = true;
    if (bar) bar.classList.add('paused');
    if (icon) icon.innerHTML = '<path d="M8 5v14l11-7z"/>';
    if (label) label.textContent = 'Resume';

    // Freeze timer
    if (recTimer) { clearInterval(recTimer); recTimer = null; }
    // Freeze waveform
    if (recWaveRAF) { cancelAnimationFrame(recWaveRAF); recWaveRAF = null; }

  } else {
    // ---------- RESUME ----------
    // Accumulate the paused time
    if (recPausedAt) {
      recPausedTotal += Date.now() - recPausedAt;
      recPausedAt = 0;
    }

    try { if (mediaRecorder && mediaRecorder.state === 'paused') mediaRecorder.resume(); } catch(_) {}

    recPaused = false;
    if (bar) bar.classList.remove('paused');
    if (icon) icon.innerHTML = '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>';
    if (label) label.textContent = 'Pause';

    // Restart timer (excludes paused duration)
    recTimer = setInterval(() => {
      const elapsed = Date.now() - recStart - recPausedTotal;
      const s = Math.floor(elapsed / 1000);
      document.getElementById('rec-time').textContent = Math.floor(s/60) + ':' + String(s % 60).padStart(2, '0');
      if (s >= 120 && recording) tmRecSend(null);
    }, 200);

    // Restart waveform
    if (recAnalyser) {
      const data = new Uint8Array(recAnalyser.frequencyBinCount);
      const tick = () => {
        if (!recording || !recAnalyser || recPaused) return;
        recAnalyser.getByteFrequencyData(data);
        const spans = document.querySelectorAll('#rec-wave span');
        const step = Math.floor(data.length / spans.length) || 1;
        spans.forEach((sp, i) => {
          const v = data[i * step] || 0;
          const h = Math.max(3, Math.min(22, (v / 255) * 22));
          sp.style.height = h + 'px';
        });
        recWaveRAF = requestAnimationFrame(tick);
      };
      tick();
    }
  }
}


function tmRecStopFromLock(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  if (!recording || !recLocked) return;
  tmRecSend(e);
}

function tmRecCancelFromLock(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  if (!recording || !recLocked) return;
  recLocked = false;
  tmRecCancelInternal();
}

function tmRecCancelInternal() {
  if (!recording) return;
  try { if (window.TMSound) TMSound.voiceCancel(); if (window.TMHaptic) TMHaptic.voiceCancel(); } catch(_){}
  recLocked = false;
  recPaused = false;
  recPausedTotal = 0;
  // Clear all recorder UI
  const _dim = document.getElementById('rec-dim');
  if (_dim) _dim.classList.remove('visible');
  const _bar = document.getElementById('rec-bar');
  if (_bar) _bar.classList.remove('paused', 'locked', 'active', 'cancelling');
  const _cursor = document.getElementById('rec-cursor');
  if (_cursor) _cursor.classList.remove('visible', 'locked');
  const _lock = document.getElementById('rec-lock-field');
  if (_lock) _lock.classList.remove('visible', 'armed', 'locked');
  const _rail = document.getElementById('rec-rail');
  if (_rail) _rail.classList.remove('visible', 'armed', 'locked');
  audioChunks = [];
  currentBlob = null;
  try { mediaRecorder.stop(); } catch(err){}
}
async function tmStartRecording() {
  if (recording) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { alert('Recording not supported.'); return; }
  try { activeStream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (err) { alert('Microphone access is required.'); return; }
  try {
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    mediaRecorder = new MediaRecorder(activeStream, {mimeType: mime});
  } catch (err) { try { activeStream.getTracks().forEach(t => t.stop()); } catch(e){} activeStream = null; alert('Could not start: ' + err.message); return; }
  audioChunks = []; currentBlob = null;
  mediaRecorder.ondataavailable = ev => { if (ev.data && ev.data.size > 0) audioChunks.push(ev.data); };
  mediaRecorder.onstop = () => {
      // --- Reset mic button and all recorder UI ---
      const _mStop = document.getElementById('mic-btn');
      if (_mStop) _mStop.classList.remove('recording');
      const _cStop = document.getElementById('rec-cursor');
      if (_cStop) _cStop.classList.remove('visible', 'locked');
      const _lkStop = document.getElementById('rec-lock-field');
      if (_lkStop) _lkStop.classList.remove('visible', 'armed', 'locked');
      const _bStop = document.getElementById('rec-bar');
      if (_bStop) _bStop.classList.remove('active', 'locked', 'paused', 'cancelling');
      recLocked = false;
      recPaused = false;
      const _dim = document.getElementById('rec-dim');
      if (_dim) _dim.classList.remove('visible');
      recPaused = false;
    recording = false;
    if (recTimer) { clearInterval(recTimer); recTimer = null; }
    try { if (activeStream) activeStream.getTracks().forEach(t => t.stop()); } catch(e){}
    activeStream = null;
    if (audioChunks.length === 0) return;
    currentBlob = new Blob(audioChunks, {type: 'audio/webm'});
  };
  try { mediaRecorder.start(100); } catch (err) { try { activeStream.getTracks().forEach(t => t.stop()); } catch(e){} activeStream = null; alert('Recorder failed: ' + err.message); return; }
  recStart = Date.now(); recPausedTotal = 0; recording = true;
  try { if (window.TMSound) TMSound.voiceStart(); if (window.TMHaptic) TMHaptic.voiceStart(); } catch(_){}
  const _mBtn = document.getElementById('mic-btn');
  if (_mBtn) _mBtn.classList.add('recording');
  document.getElementById('rec-time').textContent = '0:00';

  // Show dim overlay + recorder bar
  const dim = document.getElementById('rec-dim');
  if (dim) dim.classList.add('visible');
  const bar = document.getElementById('rec-bar');
  if (bar) bar.classList.add('active');
  const lockField = document.getElementById('rec-lock-field');
  if (lockField) {
    lockField.classList.add('visible');
    lockField.classList.remove('armed', 'locked');
    const t = document.getElementById('rec-lock-field-text');
    if (t) t.textContent = 'Slide up to lock';
  }
  const cur = document.getElementById('rec-cursor');
  if (cur) {
    cur.classList.add('visible');
    cur.classList.remove('locked');
  }
  const hint = document.getElementById('rec-hint');
  if (hint) hint.textContent = 'Release to send';

  recTimer = setInterval(() => {
    const s = Math.floor((Date.now() - recStart) / 1000);
    document.getElementById('rec-time').textContent = Math.floor(s/60) + ':' + String(s % 60).padStart(2, '0');
    if (s >= 120 && recording) tmRecSend(null);
  }, 200);
}
function tmRecCancel(e) { if (e) { e.preventDefault(); e.stopPropagation(); } if (!recording) return; audioChunks = []; try { mediaRecorder.stop(); } catch(err){} }
async function tmRecSend(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  if (!recording) return;
  recLocked = false;
  recPaused = false;
  recPausedTotal = 0;
  // Clear all recorder UI immediately
  const _dimSend = document.getElementById('rec-dim');
  if (_dimSend) _dimSend.classList.remove('visible');
  const _barSend = document.getElementById('rec-bar');
  if (_barSend) _barSend.classList.remove('active', 'locked', 'paused', 'cancelling');
  const _cursorSend = document.getElementById('rec-cursor');
  if (_cursorSend) _cursorSend.classList.remove('visible', 'locked');
  const _lockSend = document.getElementById('rec-lock-field');
  if (_lockSend) _lockSend.classList.remove('visible', 'armed', 'locked');
  const _railSend = document.getElementById('rec-rail');
  if (_railSend) _railSend.classList.remove('visible', 'armed', 'locked');
  const _bar0 = document.getElementById('rec-bar');
  if (_bar0) _bar0.classList.remove('paused', 'locked');
  const duration = (Date.now() - recStart - (recPausedTotal || 0)) / 1000;

  // Reject sub-3s voice notes — too noisy to send
  if (duration < 3) {
    // Discard silently
    recLocked = false;
    recPaused = false;
    recPausedTotal = 0;
    audioChunks = [];
    currentBlob = null;
    const _dimS = document.getElementById('rec-dim');
    if (_dimS) _dimS.classList.remove('visible');
    const _barS = document.getElementById('rec-bar');
    if (_barS) _barS.classList.remove('active', 'locked', 'paused', 'cancelling');
    const _curS = document.getElementById('rec-cursor');
    if (_curS) _curS.classList.remove('visible', 'locked');
    const _lockS = document.getElementById('rec-lock-field');
    if (_lockS) _lockS.classList.remove('visible', 'armed', 'locked');
    try { mediaRecorder.stop(); } catch(err){}
    tmToast('Hold for at least 3 seconds');
    return;
  }

  try { mediaRecorder.stop(); } catch(err){}
  const startedAt = Date.now();
  while (!currentBlob && Date.now() - startedAt < 3000) await new Promise(r => setTimeout(r, 20));
  if (!currentBlob || currentBlob.size < 1) { alert('Recording was too short.'); return; }
  if (currentBlob.size > 15 * 1024 * 1024) { alert('Voice too large.'); return; }
  try {
    const presign = await fetch('/api/media/presign', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: 'voice.webm', content_type: 'audio/webm', size: currentBlob.size, kind: 'audio'})});
    const pdata = await presign.json();
    if (!pdata.ok) throw new Error(pdata.error || 'presign failed');
    const upRes = await fetch(pdata.upload_url, {
        method: 'PUT',
        body: currentBlob,
        headers: { 'Content-Type': 'audio/webm' },
      });
      if (!upRes.ok) {
        const txt = await upRes.text().catch(() => '');
        throw new Error('Upload failed (' + upRes.status + '): ' + txt.slice(0, 200));
      }
    await tmSend({ kind: 'voice', media_url: pdata.public_url, media_duration: duration });
          try { if (window.TMSound) TMSound.voiceSend(); if (window.TMHaptic) TMHaptic.voiceSend(); } catch(_){}
  } catch (err) { alert('Could not send voice: ' + err.message); }
  finally { currentBlob = null; audioChunks = []; }
}

function tmToggleAttach(e) { try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){} if (e) e.stopPropagation(); document.getElementById('attach-menu').classList.toggle('hidden'); }
function tmPickImage() { document.getElementById('attach-menu').classList.add('hidden'); document.getElementById('image-input').click(); }
document.getElementById('image-input').addEventListener('change', async function(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  if (file.size > 15 * 1024 * 1024) { alert('Image too large (15 MB max)'); return; }
  try {
    const presign = await fetch('/api/media/presign', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: file.name, content_type: file.type, size: file.size, kind: 'image'})});
    const pdata = await presign.json();
    if (!pdata.ok) throw new Error(pdata.error || 'presign failed');
    const upRes = await fetch(pdata.upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': file.type },
      });
      if (!upRes.ok) {
        const txt = await upRes.text().catch(() => '');
        throw new Error('Upload failed (' + upRes.status + '): ' + txt.slice(0, 200));
      }
    await tmSend({ kind: 'image', media_url: pdata.public_url });
  } catch (err) { alert('Upload failed: ' + err.message); }
  finally { e.target.value = ''; }
});

const TM_STICKERS = ['😀','😂','🥰','😎','🤔','👍','🙏','🔥','💯','🎉','❤️','✨','🚀','💪','☕','🎯','📈','💡','🤝','🌟','😅','🥳','👏','🙌','😍','🤩','💼','🏆','⚡','🌈','🦾','🧠'];
function tmOpenStickers() { try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){} document.getElementById('attach-menu').classList.add('hidden'); const grid = document.getElementById('emoji-grid'); grid.innerHTML = TM_STICKERS.map(e => `<button class="emoji-cell" onclick="tmSendSticker('${e}')">${e}</button>`).join(''); document.getElementById('sticker-sheet').classList.remove('hidden'); }
function tmCloseStickers() { document.getElementById('sticker-sheet').classList.add('hidden'); }
async function tmSendSticker(emoji) { try { if (window.TMHaptic) TMHaptic.send(); } catch(_){} tmCloseStickers(); await tmSend({ kind: 'sticker', body: emoji, media_url: emoji }); }

if (window.TMHaptic) try { TMHaptic.tap(); } catch(_){}
function tmOpenMsgMenu(event, msgId, isMine) {
  if (event) event.preventDefault();
  tmCloseMsgMenu();
  const holder = document.getElementById('msg-menu-holder');
  const menu = document.createElement('div');
  menu.className = 'msg-actions';
  const row = document.querySelector('[data-msg-id="' + msgId + '"]');
  const body = (row && row.dataset.body) || '';
  const kind = (row && row.dataset.kind) || 'text';
  const isText = kind === 'text';
  const safeBody = body.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  const btns = [];
  btns.push('<button class="msg-action" onclick="tmReplyAction(\'' + msgId + '\')"><span class="msg-action-icon">↩</span> Reply</button>');
  if (isMine && isText) {
    btns.push('<button class="msg-action" onclick="tmEditAction(\'' + msgId + '\')"><span class="msg-action-icon">✏️</span> Edit</button>');
  }
  btns.push('<button class="msg-action" onclick="tmCopyAction(\'' + safeBody + '\')"><span class="msg-action-icon">📋</span> Copy</button>');
  btns.push('<button class="msg-action" onclick="tmForwardAction(\'' + msgId + '\')"><span class="msg-action-icon">➡️</span> Forward</button>');
  if (isMine) {
    btns.push('<button class="msg-action danger" onclick="tmDeleteAction(\'' + msgId + '\')"><span class="msg-action-icon">🗑</span> Delete for everyone</button>');
  } else {
    btns.push('<button class="msg-action danger" onclick="tmDeleteForMeAction(\'' + msgId + '\')"><span class="msg-action-icon">🗑</span> Delete for me</button>');
  }
  menu.innerHTML = btns.join('');
  holder.appendChild(menu);

  // Position near the tap point
  var x = (event && (event.clientX || (event.touches && event.touches[0].clientX))) || window.innerWidth / 2;
  var y = (event && (event.clientY || (event.touches && event.touches[0].clientY))) || window.innerHeight / 2;
  var mw = 200, mh = menu.offsetHeight || 240;
  var px = Math.min(Math.max(12, x - mw / 2), window.innerWidth - mw - 12);
  var py = Math.max(12, y - mh - 10);
  if (py + mh > window.innerHeight - 12) py = Math.min(window.innerHeight - mh - 12, y + 10);
  menu.style.left = px + 'px';
  menu.style.top = py + 'px';

  setTimeout(() => document.addEventListener('click', tmCloseMsgMenu, { once: true }), 10);
}
function tmEditAction(msgId) {
  tmCloseMsgMenu();
  const row = document.querySelector('[data-msg-id="' + msgId + '"]');
  if (!row) return;
  const current = row.dataset.body || '';
  const next = prompt('Edit message:', current);
  if (next === null) return;
  const trimmed = next.trim();
  if (!trimmed || trimmed === current) return;
  fetch('/api/chat/messages/' + msgId + '/edit', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body: trimmed })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      const bubble = row.querySelector('.msg-text');
      if (bubble) bubble.textContent = trimmed;
      row.dataset.body = trimmed;
      tmToast('Message edited');
    } else {
      tmToast(data.error || 'Edit failed');
    }
  }).catch(() => tmToast('Edit failed'));
  try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){}
}

function tmDeleteForMeAction(msgId) {
  tmCloseMsgMenu();
  const row = document.querySelector('[data-msg-id="' + msgId + '"]');
  if (!row) return;
  row.dataset._deleting = '1';
  row.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
  row.style.opacity = '0';
  row.style.transform = 'translateX(-20px)';
  fetch('/api/chat/messages/' + msgId + '/delete', { method: 'POST', credentials: 'same-origin' })
    .then(r => r.json()).then(data => {
      if (data.ok) { row.remove(); tmToast('Deleted for you'); }
      else { row.style.opacity = '1'; row.style.transform = ''; row.dataset._deleting = '0'; tmToast('Delete failed'); }
    }).catch(() => { row.style.opacity = '1'; row.style.transform = ''; row.dataset._deleting = '0'; });
  try { if (window.TMHaptic) TMHaptic.deleted(); } catch(_){}
}

function tmForwardAction(msgId) {
  tmCloseMsgMenu();
  const row = document.querySelector('[data-msg-id="' + msgId + '"]');
  const body = (row && row.dataset.body) || '';
  const kind = (row && row.dataset.kind) || 'text';
  // Simple prompt-based forward: ask for the chat URL of the target
  const target = prompt('Forward to user ID (or leave blank to forward to this chat):', '');
  if (target === null) return;
  const to = target.trim() || OTHER_ID;
  fetch('/api/chat/send', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to: to, kind: kind, body: body, forwarded: true })
  }).then(r => r.json()).then(data => {
    if (data.ok) tmToast('Forwarded');
    else tmToast(data.error || 'Forward failed');
  }).catch(() => tmToast('Forward failed'));
}

function tmCloseMsgMenu() { document.getElementById('msg-menu-holder').innerHTML = ''; }
function tmReplyAction(msgId) { const row = document.querySelector('[data-msg-id="' + msgId + '"]'); if (!row) return; tmSetReply(msgId, row.dataset.body || '[media]', row.classList.contains('mine')); tmCloseMsgMenu(); }
function tmCopyAction(text) { try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){} if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => tmToast('Copied')); tmCloseMsgMenu(); }
async function tmDeleteAction(msgId) { try { if (window.TMHaptic) TMHaptic.deleted(); } catch(_){} tmCloseMsgMenu(); if (!confirm('Delete this message?')) return; const r = await fetch('/api/chat/messages/' + msgId + '/delete', {method: 'POST', credentials: 'same-origin'}); const data = await r.json(); if (data.ok) { const row = document.querySelector('[data-msg-id="' + msgId + '"]'); if (row) row.remove(); } }
function tmToast(msg) {
  var old = document.querySelector('.tm-toast-pro');
  if (old) old.remove();
  var t = document.createElement('div');
  t.className = 'tm-toast-pro';
  t.textContent = msg;
  document.body.appendChild(t);
  void t.offsetWidth;
  t.classList.add('show');
  setTimeout(function () {
    t.classList.remove('show');
    setTimeout(function () { t.remove(); }, 300);
  }, 2000);
}
function tmLightbox(url) { document.getElementById('lightbox-img').src = url; document.getElementById('lightbox').classList.remove('hidden'); }

function tmOpenChatMenu(e) { try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){} if (e) e.stopPropagation(); document.getElementById('cm-backdrop').classList.remove('hidden'); document.getElementById('cm-panel').classList.remove('hidden'); var label = document.getElementById('cm-mute-label'); if (label) label.textContent = tmIsMuted() ? 'Unmute notifications' : 'Mute notifications'; }
function tmCloseChatMenu() { document.getElementById('cm-backdrop').classList.add('hidden'); document.getElementById('cm-panel').classList.add('hidden'); }
function tmSearchChat() {
  tmCloseChatMenu();
  var term = prompt('Search in this chat:'); if (!term) return;
  term = term.trim().toLowerCase(); if (!term) return;
  var rows = document.querySelectorAll('.msg-row'); var found = 0;
  rows.forEach(function(r) {
    var text = (r.dataset.body || '').toLowerCase();
    if (text.indexOf(term) !== -1) {
      r.style.transition = 'background 0.3s'; r.style.background = 'rgba(16,185,129,0.2)';
      setTimeout(function() { r.style.background = ''; }, 2400);
      if (found === 0) r.scrollIntoView({behavior: 'smooth', block: 'center'});
      found++;
    }
  });
  tmToast(found === 0 ? 'No matches' : found + ' match' + (found === 1 ? '' : 'es'));
}
function tmMuteKey() { return 'tm_mute_' + OTHER_ID; }
function tmIsMuted() { return localStorage.getItem(tmMuteKey()) === '1'; }
function tmToggleMuteChat() { var muted = !tmIsMuted(); localStorage.setItem(tmMuteKey(), muted ? '1' : '0'); var label = document.getElementById('cm-mute-label'); if (label) label.textContent = muted ? 'Unmute notifications' : 'Mute notifications'; tmToast(muted ? 'Chat muted' : 'Chat unmuted'); tmCloseChatMenu(); }
function tmOpenThemeFromMenu(e) { if (e) e.stopPropagation(); tmCloseChatMenu(); setTimeout(function() { document.getElementById('tp-backdrop').classList.remove('hidden'); document.getElementById('tp-panel').classList.remove('hidden'); }, 120); }
function tmCloseThemePicker() { document.getElementById('tp-backdrop').classList.add('hidden'); document.getElementById('tp-panel').classList.add('hidden'); }
function tmCopyUsername() { var uname = "window.TM_INIT.otherUsername"; if (navigator.clipboard) navigator.clipboard.writeText(uname).then(function() { tmToast('Copied'); }); tmCloseChatMenu(); }
async function tmClearChat() {
  tmCloseChatMenu();
  if (!confirm('Clear all messages in this chat? This cannot be undone.')) return;
  var r = await fetch('/api/chat/clear/' + OTHER_ID, {method: 'POST', credentials: 'same-origin'});
  var data = {}; try { data = await r.json(); } catch(e) {}
  if (data.ok) { document.getElementById('chat-messages').innerHTML = '<div style="text-align:center;padding:40px 20px;color:#8696a0;font-size:13px;">Chat cleared</div>'; tmToast('Chat cleared'); }
  else alert('Could not clear chat.');
}
function tmReportUser() {
  tmCloseChatMenu();
  var reason = prompt('Why are you reporting this user?');
  if (!reason || !reason.trim()) return;
  fetch('/api/chat/report', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: OTHER_ID, name: OTHER_NAME, reason: reason.trim().slice(0, 500)})}).then(function() { tmToast('Report sent'); }).catch(function() { tmToast('Report logged'); });
}

async function pickTheme(key) { try { if (window.TMHaptic) TMHaptic.soft(); } catch(_){}
  currentTheme = key;
  tmCloseThemePicker();

  // Apply theme class cleanly
  var screen = document.querySelector('.chat-screen');
  if (screen) {
    // Remove any theme-* class, add the new one
    var cls = screen.getAttribute('class') || '';
    cls = cls.split(' ').filter(function(x) { return x && !x.startsWith('theme-'); }).join(' ');
    screen.setAttribute('class', cls + ' theme-' + key);
    try {
      document.querySelectorAll('.chat-wallpaper').forEach(function(wp){
        var active = (wp.getAttribute('data-wallpaper') === key);
        wp.querySelectorAll('svg').forEach(function(sv){
          if (typeof sv.pauseAnimations !== 'function') return;
          if (active) sv.unpauseAnimations(); else sv.pauseAnimations();
        });
      });
      var b = document.querySelector('.tm-theme-bloom');
      if (b) { b.classList.remove('tm-pulse'); void b.offsetWidth; b.classList.add('tm-pulse'); }
    } catch (e) {}
  }

  // Update tile selected state
  document.querySelectorAll('.tp-row').forEach(function(b) {
    if (b.dataset.themeKey === key) b.classList.add('tp-row-active');
    else b.classList.remove('tp-row-active');
  });

  // Bump animation on the chat
  var chat = document.getElementById('chat-messages');
  if (chat) {
    chat.style.transition = 'transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1)';
    chat.style.transform = 'scale(1.015)';
    setTimeout(function() { chat.style.transform = ''; }, 220);
  }

  // Persist
  try {
    await fetch('/api/settings/chat_theme', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({theme: key})
    });
  } catch(e) {}

  tmToast('Theme saved');
}

let pc = null, localStream = null, currentCallId = null, currentCallKind = 'audio';
let pollInterval = null, incomingCall = null;
var RINGBACK_CTX = null, RINGBACK_OSC = null, RINGBACK_TIMER = null;
var CALL_TIMEOUT_MS = 45000;
var CALL_START_AT = 0;

function tmStartRingback() {
  try {
    RINGBACK_CTX = new (window.AudioContext || window.webkitAudioContext)();
    RINGBACK_OSC = RINGBACK_CTX.createOscillator();
    var g = RINGBACK_CTX.createGain();
    RINGBACK_OSC.type = 'sine';
    RINGBACK_OSC.frequency.value = 440;
    g.gain.value = 0.06;
    RINGBACK_OSC.connect(g); g.connect(RINGBACK_CTX.destination);
    RINGBACK_OSC.start();
    // Ring pattern: 1s on, 3s off
    RINGBACK_TIMER = setInterval(function(){
      try {
        g.gain.setValueAtTime(0.06, RINGBACK_CTX.currentTime);
        setTimeout(function(){ try { g.gain.setValueAtTime(0, RINGBACK_CTX.currentTime); } catch(_){} }, 1000);
      } catch(_){}
    }, 4000);
    // Start immediately
    setTimeout(function(){ try { g.gain.setValueAtTime(0, RINGBACK_CTX.currentTime); } catch(_){} }, 1000);
  } catch(_) {}
}

function tmStopRingback() {
  try { if (RINGBACK_TIMER) clearInterval(RINGBACK_TIMER); } catch(_){}
  RINGBACK_TIMER = null;
  try { if (RINGBACK_OSC) RINGBACK_OSC.stop(); } catch(_){}
  RINGBACK_OSC = null;
  try { if (RINGBACK_CTX) RINGBACK_CTX.close(); } catch(_){}
  RINGBACK_CTX = null;
}

// Call integration — global call manager handles the UI + WebRTC
window.TM_CALL_TARGET = OTHER_ID;
window.TM_CALL_NAME = OTHER_NAME;
window.TM_CALL_AVATAR = OTHER_AVATAR || "";

function startCall(kind) {
  window.TM_CALL_TARGET = OTHER_ID;
  window.TM_CALL_NAME = OTHER_NAME;
  window.TM_CALL_AVATAR = OTHER_AVATAR || "";
  if (window.tmStartCall) {
    window.tmStartCall(kind);
  } else {
    setTimeout(function(){
      if (window.tmStartCall) window.tmStartCall(kind);
      else alert('Call system is still loading. Try again.');
    }, 500);
  }
}

// Wallpaper opacity control
// ============================================================
var WP_KEY = 'tm_wallpaper_opacity_' + OTHER_ID;

function tmApplyWallpaperOpacity(val) {
  var el = document.getElementById('chat-messages');
  if (!el) return;
  el.style.setProperty('--wallpaper-opacity', val);
}

function tmSetWallpaperOpacity(key, val) {
  try { localStorage.setItem(WP_KEY, String(val)); } catch(e) {}
  tmApplyWallpaperOpacity(val);
  // Mark button active
  document.querySelectorAll('.tp-op-btn').forEach(function(b) {
    b.classList.toggle('tp-op-active', b.dataset.opacity === key);
  });
  tmToast('Wallpaper ' + (val === '0' ? 'off' : key));
}

// Restore on load
(function() {
  var stored = '0.15';
  try { stored = localStorage.getItem(WP_KEY) || '0.15'; } catch(e) {}
  tmApplyWallpaperOpacity(stored);
  // Highlight the matching button
  setTimeout(function() {
    var matchKey = 'soft';
    if (stored === '0') matchKey = 'off';
    else if (stored === '0.30') matchKey = 'medium';
    else if (stored === '0.55') matchKey = 'bold';
    document.querySelectorAll('.tp-op-btn').forEach(function(b) {
      b.classList.toggle('tp-op-active', b.dataset.opacity === matchKey);
    });
  }, 300);
})();


function tmToggleTheme(e) {
  if (e) e.stopPropagation();
  var html = document.documentElement;
  var isLight = html.classList.contains('light');
  if (isLight) {
    html.classList.remove('light');
    html.classList.add('dark'); try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){}
    try { document.cookie = 'tm_theme=dark; path=/; max-age=' + (60*60*24*365); } catch(e){}
    tmToast('Dark mode');
  } else {
    html.classList.add('light'); try { if (window.TMHaptic) TMHaptic.tap(); } catch(_){}
    html.classList.remove('dark');
    try { document.cookie = 'tm_theme=light; path=/; max-age=' + (60*60*24*365); } catch(e){}
    tmToast('Light mode');
  }
}

console.log('[TrueMatch] chat loaded');

// ============================================================
// Long-press / right-click to open message menu
// ============================================================
(function(){
  var LONG_PRESS_MS = 450;
  var longPressTimer = null;
  var startX = 0, startY = 0;

  function findMsgRow(el) {
    while (el && el !== document.body) {
      if (el.dataset && el.dataset.msgId) return el;
      el = el.parentElement;
    }
    return null;
  }

  function openMenuAt(el, ev) {
    var row = findMsgRow(el);
    if (!row) return;
    var msgId = row.dataset.msgId;
    var isMine = row.classList.contains('mine');
    if (typeof tmOpenMsgMenu === 'function') {
      tmOpenMsgMenu(ev, msgId, isMine);
      if (navigator.vibrate) try { navigator.vibrate(15); } catch(_){}
    }
  }

  // Right-click (desktop / long-press on some Androids)
  document.addEventListener('contextmenu', function(ev){
    var row = findMsgRow(ev.target);
    if (row) {
      ev.preventDefault();
      openMenuAt(ev.target, ev);
    }
  });

  // Touch-and-hold (mobile primary trigger)
  document.addEventListener('touchstart', function(ev){
    var t = ev.touches[0];
    startX = t.clientX;
    startY = t.clientY;
    var target = ev.target;
    if (longPressTimer) clearTimeout(longPressTimer);
    longPressTimer = setTimeout(function(){
      longPressTimer = null;
      openMenuAt(target, {
        clientX: startX,
        clientY: startY,
        preventDefault: function(){}
      });
    }, LONG_PRESS_MS);
  }, { passive: true });

  document.addEventListener('touchmove', function(ev){
    var t = ev.touches[0];
    if (Math.abs(t.clientX - startX) > 8 || Math.abs(t.clientY - startY) > 8) {
      if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
    }
  }, { passive: true });

  document.addEventListener('touchend', function(){
    if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
  }, { passive: true });

  document.addEventListener('touchcancel', function(){
    if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
  }, { passive: true });
})();


// ---------- Swipe to reply ----------
(function(){
  var SWIPE_MAX = 78;
  var SWIPE_THRESHOLD = 55;
  var SWIPE_LOCK = 12;
  function hintSVG(){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 17l-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>';}
  function ensureHint(row){
    var h = row.querySelector('.swipe-reply-hint');
    if (!h) { h = document.createElement('div'); h.className='swipe-reply-hint'; h.innerHTML=hintSVG(); row.appendChild(h); }
    return h;
  }
  function attachSwipe(row){
    if (row.dataset.swipeBound === '1') return;
    row.dataset.swipeBound = '1';
    var bubble = row.querySelector('.bubble');
    if (!bubble) return;
    var startX=0, startY=0, dx=0, dy=0;
    var tracking=false, locked=false, active=false;
    var isMine = row.classList.contains('mine');
    function onStart(e){
      if (row.dataset._deleting==='1') return;
      var t = e.touches ? e.touches[0] : e;
      startX = t.clientX; startY = t.clientY;
      dx=0; dy=0; tracking=true; locked=false; active=false;
    }
    function onMove(e){
      if (!tracking) return;
      var t = e.touches ? e.touches[0] : e;
      dx = t.clientX - startX; dy = t.clientY - startY;
      if (!locked){
        if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > SWIPE_LOCK){ tracking=false; return; }
        if (Math.abs(dx) > SWIPE_LOCK){
          locked=true; active=true;
          row.classList.add('swipe-active'); ensureHint(row);
        } else return;
      }
      var eff = isMine ? Math.min(0,dx) : Math.max(0,dx);
      if (Math.abs(eff) > SWIPE_MAX) eff = isMine ? -SWIPE_MAX : SWIPE_MAX;
      bubble.style.transform = 'translateX(' + eff + 'px)';
      bubble.style.transition = 'none';
      if (Math.abs(eff) >= SWIPE_THRESHOLD) row.classList.add('swipe-ready');
      else row.classList.remove('swipe-ready');
    }
    function onEnd(){
      if (!tracking && !active) return;
      tracking = false;
      if (!active) return;
      var trigger = Math.abs(dx) >= SWIPE_THRESHOLD;
      var direction = isMine ? dx < 0 : dx > 0;
      var valid = trigger && direction;
      bubble.style.transition = '';
      row.classList.add('swipe-released');
      if (valid){
        bubble.style.transform = 'translateX(' + (isMine ? -90 : 90) + 'px)';
        if (navigator.vibrate) try { navigator.vibrate(15); } catch(_){}
        var msgId = row.dataset.msgId;
        var body = row.dataset.body || '';
        setTimeout(function(){
          bubble.style.transform = '';
          row.classList.remove('swipe-active','swipe-ready');
          setTimeout(function(){ row.classList.remove('swipe-released'); }, 260);
          if (window.TMSound) TMSound.reply();
        if (window.TMHaptic) TMHaptic.reply();
        if (window.TMHaptic) TMHaptic.reply();
        if (typeof tmSetReply === 'function') tmSetReply(msgId, body, isMine);
        }, 160);
      } else {
        bubble.style.transform = '';
        row.classList.remove('swipe-active','swipe-ready');
        setTimeout(function(){ row.classList.remove('swipe-released'); }, 260);
      }
      active=false; locked=false;
    }
    row.addEventListener('touchstart', onStart, { passive: true });
    row.addEventListener('touchmove', onMove, { passive: false });
    row.addEventListener('touchend', onEnd, { passive: true });
    row.addEventListener('touchcancel', onEnd, { passive: true });
  }
  document.querySelectorAll('.msg-row').forEach(attachSwipe);
  var chat = document.getElementById('chat-messages');
  if (chat){
    var mo = new MutationObserver(function(muts){
      muts.forEach(function(mu){
        mu.addedNodes.forEach(function(n){
          if (n.nodeType===1 && n.classList && n.classList.contains('msg-row')) attachSwipe(n);
        });
      });
    });
    mo.observe(chat, { childList: true });
  }
})();


})();
