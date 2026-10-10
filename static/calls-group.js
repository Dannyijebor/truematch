// ===== Group calls (mesh) v1 =====
(function(){
'use strict';
var G = window.tmGroup = { peers:{}, lastSignalAt:null, pollTimer:null, participants:[] };

function state(){ return window.tmState || {}; }
function callId(){ var s = state(); return s.callId; }
function me(){ return window.TM_USER_ID; }

function iceConfig(){
  return { iceServers:[
    { urls:'stun:stun.l.google.com:19302' },
    { urls:'turn:openrelay.metered.ca:80', username:'openrelayproject', credential:'openrelayproject' },
    { urls:'turn:openrelay.metered.ca:443', username:'openrelayproject', credential:'openrelayproject' }
  ], iceCandidatePoolSize:10 };
}

async function postJSON(url, body){
  var r = await fetch(url, { method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{}) });
  if (!r.ok) { var t = ''; try { t = (await r.json()).detail || ''; } catch(_){}; throw new Error(t || ('HTTP '+r.status)); }
  return r.json().catch(function(){ return {}; });
}
async function getJSON(url){
  var r = await fetch(url, { credentials:'same-origin' });
  if (!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}

async function sendSignal(to, kind, payload){
  var id = callId(); if (!id) return;
  try { await postJSON('/api/calls/'+id+'/signal', { to:to, kind:kind, payload:payload||{} }); }
  catch(e){ console.warn('signal send failed', e); }
}

async function getOrCreatePeer(peerId, initiator){
  var p = G.peers[peerId];
  if (p && p.pc && p.pc.connectionState !== 'closed') return p;
  var pc = new RTCPeerConnection(iceConfig());
  var local = state().localStream;
  if (local) local.getTracks().forEach(function(t){ pc.addTrack(t, local); });
  pc.onicecandidate = function(ev){
    if (!ev.candidate) return;
    sendSignal(peerId, 'ice', { candidate: ev.candidate.toJSON() });
  };
  pc.ontrack = function(ev){
    var wrap = G.peers[peerId];
    if (!wrap) return;
    wrap.stream = ev.streams[0];
    var v = document.getElementById('tm-gp-'+peerId);
    if (v) { v.srcObject = ev.streams[0]; v.play && v.play().catch(function(){}); }
  };
  pc.onconnectionstatechange = function(){
    var w = G.peers[peerId];
    if (!w) return;
    w.state = pc.connectionState;
    var el = document.getElementById('tm-gp-'+peerId);
    if (el && el.parentElement) el.parentElement.dataset.state = pc.connectionState;
  };
  G.peers[peerId] = { pc:pc, stream:null, state:'new' };
  if (initiator) {
    try {
      var offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await sendSignal(peerId, 'offer', { sdp:offer.sdp, type:offer.type });
    } catch(e){ console.warn('offer failed', e); }
  }
  renderGrid();
  return G.peers[peerId];
}

async function handleSignal(sig){
  var from = sig.from, kind = sig.kind, pl = sig.payload || {};
  var wrap = await getOrCreatePeer(from, false);
  var pc = wrap.pc;
  try {
    if (kind === 'offer') {
      await pc.setRemoteDescription(new RTCSessionDescription({ sdp:pl.sdp, type:pl.type }));
      var ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await sendSignal(from, 'answer', { sdp:ans.sdp, type:ans.type });
    } else if (kind === 'answer') {
      if (!pc.currentRemoteDescription) await pc.setRemoteDescription(new RTCSessionDescription({ sdp:pl.sdp, type:pl.type }));
    } else if (kind === 'ice') {
      if (pl.candidate) { try { await pc.addIceCandidate(new RTCIceCandidate(pl.candidate)); } catch(_){} }
    } else if (kind === 'bye') {
      try { pc.close(); } catch(_){}; delete G.peers[from]; renderGrid();
    } else if (kind === 'invite') {
      showJoinPrompt();
    }
  } catch(e){ console.warn('signal handle failed', kind, e); }
}

function startSignalPoll(){
  if (G.pollTimer) return;
  G.pollTimer = setInterval(async function(){
    var id = callId();
    if (!id) return;
    try {
      var url = '/api/calls/'+id+'/signals';
      if (G.lastSignalAt) url += '?since='+encodeURIComponent(G.lastSignalAt);
      var data = await getJSON(url);
      var arr = data.signals || [];
      for (var i = 0; i < arr.length; i++) { await handleSignal(arr[i]); }
      if (arr.length) G.lastSignalAt = arr[arr.length-1].created_at;
    } catch(e){}
  }, 1200);
}
function stopSignalPoll(){ if (G.pollTimer) { clearInterval(G.pollTimer); G.pollTimer = null; } }

async function refreshParticipants(){
  var id = callId(); if (!id) return;
  try {
    var d = await getJSON('/api/calls/'+id+'/participants');
    G.participants = d.participants || [];
    renderGrid();
    renderInviteSheet();
  } catch(e){}
}

function renderGrid(){
  var grid = document.getElementById('tm-group-grid');
  if (!grid) return;
  var meId = me();
  var html = '';
  var n = 0;
  for (var pid in G.peers) {
    var w = G.peers[pid];
    var info = (G.participants||[]).find(function(x){ return x.user_id === pid; }) || {};
    var name = info.name || 'Peer';
    html += '<div class="tm-gp-tile" data-state="'+ (w.state||'new') +'">';
    html += '<video id="tm-gp-'+pid+'" autoplay playsinline></video>';
    html += '<div class="tm-gp-name">'+ escapeHtml(name) +'</div>';
    html += '</div>';
    n++;
  }
  var avatarWrap = document.getElementById('tm-c-avatar-wrap');
  if (n === 0) { grid.innerHTML = ''; grid.style.display = 'none'; if (avatarWrap) avatarWrap.style.display = ''; return; }
  grid.style.display = 'grid';
  grid.setAttribute('data-count', String(n));
  grid.innerHTML = html;
  if (avatarWrap) avatarWrap.style.display = (n >= 2) ? 'none' : '';
  // Re-attach streams
  for (var pid2 in G.peers) {
    var w2 = G.peers[pid2];
    var v = document.getElementById('tm-gp-'+pid2);
    if (v && w2.stream && v.srcObject !== w2.stream) { v.srcObject = w2.stream; v.play && v.play().catch(function(){}); }
  }
}

function escapeHtml(s){ return String(s||'').replace(/[&<>"']/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'})[c]; }); }

function showJoinPrompt(){
  var box = document.getElementById('tm-group-invite-toast');
  if (!box) {
    box = document.createElement('div');
    box.id = 'tm-group-invite-toast';
    box.className = 'tm-group-invite-toast';
    box.innerHTML = '<div class="tm-git-card"><div class="tm-git-text">You were added to a call</div><div class="tm-git-actions"><button class="tm-git-decline" type="button">Dismiss</button><button class="tm-git-join" type="button">Join</button></div></div>';
    document.body.appendChild(box);
    box.querySelector('.tm-git-join').addEventListener('click', function(){ window.tmJoinGroup(); });
    box.querySelector('.tm-git-decline').addEventListener('click', function(){ box.classList.remove('tm-show'); });
  }
  box.classList.add('tm-show');
}

function buildInviteSheet(){
  if (document.getElementById('tm-invite-sheet')) return;
  var d = document.createElement('div');
  d.id = 'tm-invite-sheet';
  d.className = 'tm-invite-sheet';
  d.innerHTML = '<div class="tm-invite-card">' +
    '<div class="tm-invite-head">' +
      '<div class="tm-invite-title">Add to call</div>' +
      '<button class="tm-invite-close" type="button" aria-label="Close">&#215;</button>' +
    '</div>' +
    '<input class="tm-invite-search" id="tm-invite-q" type="text" placeholder="Search people by name or @username" autocomplete="off">' +
    '<div class="tm-invite-list" id="tm-invite-list"></div>' +
  '</div>';
  document.body.appendChild(d);
  var close = d.querySelector('.tm-invite-close');
  if (close) close.addEventListener('click', function(){ d.classList.remove('tm-show'); });
  d.addEventListener('click', function(e){ if (e.target === d) d.classList.remove('tm-show'); });
  var q = d.querySelector('#tm-invite-q');
  var timer = null;
  if (q) q.addEventListener('input', function(){
    clearTimeout(timer);
    timer = setTimeout(function(){ doSearch(q.value); }, 260);
  });
}

async function doSearch(term){
  var list = document.getElementById('tm-invite-list');
  if (!list) return;
  if (!term || term.trim().length < 2) { list.innerHTML = '<div class="tm-invite-empty">Type at least 2 characters</div>'; return; }
  list.innerHTML = '<div class="tm-invite-empty">Searching…</div>';
  try {
    var d = await getJSON('/api/people/search?q=' + encodeURIComponent(term));
    var people = d.people || [];
    if (!people.length) { list.innerHTML = '<div class="tm-invite-empty">No matches</div>'; return; }
    var html = '';
    people.forEach(function(p){
      var inCall = (G.participants||[]).some(function(x){ return x.user_id === p.user_id; });
      html += '<div class="tm-invite-row" data-id="'+p.user_id+'">';
      html += '<div class="tm-invite-avatar">' + (p.avatar_url ? '<img src="'+p.avatar_url+'">' : (p.name[0]||'?').toUpperCase()) + '</div>';
      html += '<div class="tm-invite-info"><div class="tm-invite-nm">'+escapeHtml(p.name)+'</div>';
      if (p.username) html += '<div class="tm-invite-un">@'+escapeHtml(p.username)+'</div>';
      html += '</div>';
      if (inCall) html += '<div class="tm-invite-status">In call</div>';
      else html += '<button class="tm-invite-add" type="button" data-id="'+p.user_id+'">Invite</button>';
      html += '</div>';
    });
    list.innerHTML = html;
    list.querySelectorAll('.tm-invite-add').forEach(function(b){
      b.addEventListener('click', function(){ inviteUser(b.dataset.id, b); });
    });
  } catch(e) { list.innerHTML = '<div class="tm-invite-empty">Search failed</div>'; }
}

async function inviteUser(userId, btn){
  var id = callId(); if (!id) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Inviting…'; }
  try {
    await postJSON('/api/calls/'+id+'/invite', { user_id:userId });
    await refreshParticipants();
    if (btn) { btn.textContent = 'Invited'; btn.classList.add('tm-invited'); }
    // Start mesh peer immediately if this user has joined (skip — they'll signal us)
  } catch(e){
    if (btn) { btn.disabled = false; btn.textContent = 'Invite'; }
    alert('Could not invite: ' + e.message);
  }
}

function renderInviteSheet(){
  // no-op for now; participant list refresh handled by search
}


async function joinAndConnect(){
  var id = callId(); if (!id) return;
  try { await postJSON('/api/calls/'+id+'/join', {}); } catch(e){ console.warn('join failed', e); return; }
  await refreshParticipants();
  var meId = me();
  for (var i = 0; i < (G.participants||[]).length; i++) {
    var part = G.participants[i];
    if (part.user_id === meId) continue;
    if (part.status !== 'joined') continue;
    await getOrCreatePeer(part.user_id, true);
  }
  var box = document.getElementById('tm-group-invite-toast');
  if (box) box.classList.remove('tm-show');
}
window.tmJoinGroup = joinAndConnect;

// -------- Button hook: replace Add handler --------
function wireAddButton(){
  var btn = document.getElementById('tm-btn-add');
  if (!btn || btn._groupWired) return;
  btn._groupWired = true;
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    buildInviteSheet();
    var sheet = document.getElementById('tm-invite-sheet');
    if (sheet) sheet.classList.add('tm-show');
    doSearch('');
  }, true);
}

// -------- Boot on call active --------
setInterval(function(){
  var s = state();
  if (s.active && s.callId) {
    if (!G.bootedCallId || G.bootedCallId !== s.callId) {
      G.bootedCallId = s.callId;
      G.peers = {}; G.lastSignalAt = null; G.participants = [];
      startSignalPoll();
      refreshParticipants();
      wireAddButton();
      setInterval(refreshParticipants, 3500);
    }
  } else if (!s.active && G.bootedCallId) {
    stopSignalPoll();
    Object.keys(G.peers).forEach(function(k){ try { G.peers[k].pc.close(); } catch(_){} });
    G.peers = {}; G.bootedCallId = null; G.lastSignalAt = null; G.participants = [];
  }
}, 1500);

})();
