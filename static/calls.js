// ============================================================
// TrueMatch — Global call manager (WebRTC + UI)
// ============================================================
(function(){
"use strict";
function $(id){return document.getElementById(id);}

var state={
  active:false, role:null, callId:null, kind:'audio',
  startedAt:0, connectedAt:0, timerInt:null, signalInt:null,
  pc:null, localStream:null, remoteStream:null,
  micMuted:false, speakerOn:false, holdOn:false,
  lastIceCount:{caller:0,callee:0},
  lastReactionAt:"", audioCtx:null,
  analyserLocal:null, analyserRemote:null, meterRAF:null,
  ringInt:null, timeoutInt:null, incomingPayload:null,
  facingMode:'user', videoEnabled:false, minimized:false,
};

var TURN=[
  {urls:'stun:stun.l.google.com:19302'},
  {urls:'stun:stun1.l.google.com:19302'},
  {urls:'turn:openrelay.metered.ca:80',username:'openrelayproject',credential:'openrelayproject'},
  {urls:'turn:openrelay.metered.ca:443',username:'openrelayproject',credential:'openrelayproject'},
  {urls:'turn:openrelay.metered.ca:443?transport=tcp',username:'openrelayproject',credential:'openrelayproject'}
];

function ctx(){ if(state.audioCtx) return state.audioCtx;
  try{state.audioCtx=new (window.AudioContext||window.webkitAudioContext)();}catch(_){state.audioCtx=null;}
  return state.audioCtx;
}
function beep(freq,dur,vol){
  var c=ctx(); if(!c) return;
  try{ if(c.state==='suspended') c.resume();
    var t0=c.currentTime, o=c.createOscillator(), g=c.createGain();
    o.type='sine'; o.frequency.value=freq;
    g.gain.setValueAtTime(0,t0);
    g.gain.linearRampToValueAtTime(vol||0.1,t0+0.02);
    g.gain.exponentialRampToValueAtTime(0.0001,t0+dur);
    o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+dur+0.05);
  }catch(_){}
}
function ringStart(){
  ringStop();
  var doRing=function(){ if (window.TMSound && window.TMSound.incoming) window.TMSound.incoming(); };
  doRing();
  state.ringInt=setInterval(doRing,2200);
}
function ringStop(){ if(state.ringInt){clearInterval(state.ringInt);state.ringInt=null;} }
function vib(p){ try{navigator.vibrate&&navigator.vibrate(p);}catch(_){} }
function fmt(s){ var m=Math.floor(s/60),r=s%60; return String(m).padStart(2,'0')+':'+String(r).padStart(2,'0'); }
function init(n){ if(!n) return '?'; var p=n.trim().split(/\s+/); return ((p[0]||'')[0]||'?').toUpperCase(); }

function buildMeter(el,n){
  if(!el) return; el.innerHTML=''; n=n||48;
  for(var i=0;i<n;i++){ var s=document.createElement('span');
    var a=(i/n)*360;
    s.style.transform='translate(-50%,0) rotate('+a+'deg) translateY(-110px)';
    el.appendChild(s);
  }
}
function startMeter(){
  if(state.meterRAF) cancelAnimationFrame(state.meterRAF);
  var m=$('tm-c-meter'); var mic=$('tm-in-meter');
  var dL=new Uint8Array(64), dR=new Uint8Array(64);
  function loop(){
    if(state.analyserLocal){
      state.analyserLocal.getByteFrequencyData(dL);
      var bars=m?m.querySelectorAll('span'):[];
      var step=Math.floor(dL.length/Math.max(bars.length,1))||1;
      var sum=0; for(var k=0;k<dL.length;k++) sum+=dL[k];
      var avg=sum/dL.length;
      bars.forEach(function(s,i){var v=dL[i*step]||0;var h=Math.max(6,Math.min(46,6+(v/255)*40));s.style.height=h+'px';});
      if(m){m.classList.toggle('speaking',avg>22);m.classList.toggle('listening',avg<=22);}
      if(mic){mic.classList.toggle('speaking',avg>22);mic.classList.toggle('listening',avg<=22);}
    }
    if(state.analyserRemote&&m){
      state.analyserRemote.getByteFrequencyData(dR);
      var s2=0; for(var j=0;j<dR.length;j++) s2+=dR[j];
      var avgR=s2/dR.length;
      m.style.filter=avgR>22?'brightness(1.35)':'';
    }
    state.meterRAF=requestAnimationFrame(loop);
  }
  loop();
}
function stopMeter(){ if(state.meterRAF){cancelAnimationFrame(state.meterRAF);state.meterRAF=null;} }
function attachAnalyser(stream,which){
  var c=ctx(); if(!c||!stream) return;
  try{ var src=c.createMediaStreamSource(stream), an=c.createAnalyser();
    an.fftSize=128; an.smoothingTimeConstant=0.55; src.connect(an);
    if(which==='local') state.analyserLocal=an; else state.analyserRemote=an;
  }catch(e){}
}

function startTimer(){
  if(state.timerInt) clearInterval(state.timerInt);
  state.connectedAt=Date.now();
  var el=$('tm-c-status');
  var tick=function(){ if(el) el.textContent=fmt(Math.floor((Date.now()-state.connectedAt)/1000)); };
  tick(); state.timerInt=setInterval(tick,500);
}
function stopTimer(){ if(state.timerInt){clearInterval(state.timerInt);state.timerInt=null;} }

function showIncoming(p){
  var k=$('tm-in-kind'), n=$('tm-in-name'), a=$('tm-in-avatar');
  if(k) k.textContent=(p.kind==='video'?'INCOMING VIDEO CALL':'INCOMING AUDIO CALL');
  if(n) n.textContent=p.from.name||'Unknown';
  if(a){ if(p.from.avatar_url){a.innerHTML='<img src="'+p.from.avatar_url+'" alt="">';}else{a.textContent=init(p.from.name);} }
  buildMeter($('tm-in-meter'),48);
  document.body.classList.add('tm-in-call');
  var el=$('tm-incoming'); if(el) el.classList.add('tm-show');
}
function hideIncoming(){ var el=$('tm-incoming'); if(el) el.classList.remove('tm-show'); }
function showInCall(name,kind,avatarUrl){
  try {
    var ct=$('tm-c-type'), cn=$('tm-c-name'), ca=$('tm-c-avatar'), pip=$('tm-self-pip');
    if(ct) ct.textContent=(kind==='video'?'VIDEO CALL':'AUDIO CALL');
    if(cn) cn.textContent=name||'Unknown';
    if(ca){ if(avatarUrl){ca.innerHTML='<img src="'+avatarUrl+'" alt="">';}else{ca.textContent=init(name);} }
    if(pip){
      if(window.TM_USER_AVATAR){pip.innerHTML='<img src="'+window.TM_USER_AVATAR+'" alt="">';}
      else{pip.textContent=init(window.TM_USER_NAME);}
    }
    try { buildMeter($('tm-c-meter'),48); } catch(e){ console.warn('meter', e); }
    document.body.classList.add('tm-in-call');
    var el=$('tm-incall');
    if (el) {
      el.classList.add('tm-show');
      // Bulletproof: force inline display as fallback
      el.style.display = 'flex';
    } else {
      console.error('tm-incall element missing!');
      alert('Call screen missing from DOM. Please reload.');
    }
  } catch(e) {
    console.error('showInCall threw', e);
    alert('Call UI error: ' + e.message);
  }
}
function hideInCall(){
  var el=$('tm-incall'); if(el) el.classList.remove('tm-show');
  document.body.classList.remove('tm-in-call');
  var row=$('tm-emoji-row'); if(row) row.classList.remove('tm-show');
}

function activateVideoMode(){
  console.log('[video] activating video mode');
  var screen=$('tm-incall'); if(screen) screen.classList.add('tm-video-mode');
  function attachLocal(){
    var lv=$('tm-local-video');
    if(!lv || !state.localStream) return;
    if(lv.srcObject !== state.localStream){
      try { lv.srcObject = state.localStream; } catch(e){ console.warn('srcObject', e); }
    }
    lv.muted = true;
    lv.setAttribute('autoplay','');
    lv.setAttribute('playsinline','');
    lv.classList.add('tm-on');
    var p = lv.play();
    if (p && p.catch) p.catch(function(e){ console.warn('lv play', e); });
  }
  attachLocal();
  setTimeout(attachLocal, 300);
  setTimeout(attachLocal, 1200);
  var pip=$('tm-self-pip'); if(pip) pip.classList.add('tm-has-video');
  var cb=$('tm-btn-cam'); if(cb){ cb.classList.remove('tm-active'); cb.style.display=''; }
}

function deactivateVideoMode(){
  var screen=$('tm-incall'); if(screen){ screen.classList.remove('tm-video-mode','tm-no-cam'); }
  var lv=$('tm-local-video'); if(lv){ lv.classList.remove('tm-on'); lv.srcObject=null; }
  var pip=$('tm-self-pip'); if(pip) pip.classList.remove('tm-has-video');
  var rv=$('tm-remote-video'); if(rv){ rv.classList.remove('tm-on'); rv.srcObject=null; }
  var cb=$('tm-btn-cam'); if(cb){ cb.style.display='none'; cb.classList.remove('tm-active'); }
}

window.tmToggleCamera = async function(){
  if (state.kind !== 'video' || !state.localStream) return;
  var cb = $('tm-btn-cam');
  if (state.videoEnabled) {
    state.videoEnabled = false;
    state.localStream.getVideoTracks().forEach(function(t){
      try{t.stop();}catch(_){}
      try{state.localStream.removeTrack(t);}catch(_){}
    });
    try {
      var senderOff = state.pc && state.pc.getSenders().find(function(s){ return s.track && s.track.kind === 'video'; });
      if (senderOff) await senderOff.replaceTrack(null);
    } catch(_){}
    var lvOff = $('tm-local-video'); if(lvOff) lvOff.classList.remove('tm-on');
    var screenOff = $('tm-incall'); if(screenOff) screenOff.classList.add('tm-no-cam');
    if (cb) cb.classList.add('tm-active');
  } else {
    try {
      var ns = await navigator.mediaDevices.getUserMedia({video:{facingMode:state.facingMode,width:{ideal:1280},height:{ideal:720}}});
      var nt = ns.getVideoTracks()[0];
      state.localStream.addTrack(nt);
      state.videoEnabled = true;
      try {
        var existing = state.pc && state.pc.getSenders().find(function(s){ return s.track && s.track.kind === 'video'; });
        if (existing) { await existing.replaceTrack(nt); }
        else if (state.pc) { state.pc.addTrack(nt, state.localStream); }
      } catch(_){}
      var lvOn = $('tm-local-video');
      if (lvOn) { lvOn.srcObject = state.localStream; lvOn.classList.add('tm-on'); try{lvOn.play().catch(function(){});}catch(_){} }
      var screenOn = $('tm-incall'); if(screenOn) screenOn.classList.remove('tm-no-cam');
      if (cb) cb.classList.remove('tm-active');
    } catch(e) { alert('Could not access camera.'); }
  }
};

window.tmFlipCamera = async function(){
  if (!state.localStream) return;
  try {
    state.facingMode = (state.facingMode === 'user') ? 'environment' : 'user';
    var newStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: state.facingMode, width:{ideal:1280}, height:{ideal:720} }
    });
    var newTrack = newStream.getVideoTracks()[0];
    var sender = state.pc && state.pc.getSenders().find(function(s){ return s.track && s.track.kind === 'video'; });
    if (sender) await sender.replaceTrack(newTrack);
    state.localStream.getVideoTracks().forEach(function(t){ t.stop(); });
    state.localStream.addTrack(newTrack);
    var lv = $('tm-local-video'); if (lv) { lv.srcObject = state.localStream; lv.play().catch(function(){}); }
  } catch(e) { console.warn('flip', e); }
};

async function setupPeer(){
  var pc=new RTCPeerConnection({iceServers:TURN,iceCandidatePoolSize:10});
  state.pc=pc;
  if(state.localStream){ state.localStream.getTracks().forEach(function(t){pc.addTrack(t,state.localStream);}); }
  pc.ontrack=function(ev){ state.remoteStream=ev.streams[0];
    var ra=$('tm-remote-audio'); if(ra) ra.srcObject=ev.streams[0];
    var rv=$('tm-remote-video');
    if (rv && ev.track.kind === 'video') {
      rv.srcObject = ev.streams[0];
      // Only reveal once we get an actual frame
      rv.onloadeddata = function(){ rv.classList.add('tm-on'); };
      rv.play().catch(function(){});
    }
    try{attachAnalyser(ev.streams[0],'remote');}catch(_){} };
  pc.onicecandidate=function(ev){ if(!ev.candidate) return;
    var side=(state.role==='caller')?'caller':'callee';
    fetch('/api/calls/'+state.callId+'/ice?side='+side,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate:ev.candidate.toJSON()})}).catch(function(){});
  };
  pc.onconnectionstatechange=function(){
    var s=pc.connectionState, st=$('tm-c-status');
    if(s==='connected'){ if(!state.connectedAt){ startTimer(); if(window.TMSound) window.TMSound.callConnect(); if(window.TMHaptic) window.TMHaptic.connect(); } if(st) st.classList.remove('ringing'); }
    else if(s==='failed'){ if(st) st.textContent='Connection lost'; setTimeout(function(){tmEndCall(true);},1500); }
    else if(s==='disconnected'){ if(st) st.textContent='Reconnecting...'; }
  };
  return pc;
}

function startPolling(){
  if(state.signalInt) clearInterval(state.signalInt);
  state.signalInt=setInterval(async function(){
    if(!state.callId||!state.pc) return;
    try{
      var r=await fetch('/api/calls/'+state.callId+'/state',{credentials:'same-origin'});
      if(!r.ok) return;
      var s=await r.json(); var me=s.you_are;
      if(s.status==='declined'){ friendlyEnd('Declined'); return; }
      if(s.status==='ended'){ friendlyEnd('Call ended'); return; }
      if(me==='caller'&&s.answer&&state.pc&&!state.pc.currentRemoteDescription){
        try{await state.pc.setRemoteDescription(new RTCSessionDescription(s.answer));}catch(e){}
      }
      var list=(me==='caller'?s.ice_callee:s.ice_caller)||[];
      var seen=(me==='caller')?state.lastIceCount.callee:state.lastIceCount.caller;
      for(var i=seen;i<list.length;i++){ try{await state.pc.addIceCandidate(new RTCIceCandidate(list[i]));}catch(e){} }
      if(me==='caller') state.lastIceCount.callee=list.length; else state.lastIceCount.caller=list.length;
      if(s.reaction&&s.reaction.at&&s.reaction.at!==state.lastReactionAt){
        state.lastReactionAt=s.reaction.at;
        if(window.TM_USER_ID&&s.reaction.from!==window.TM_USER_ID){ floatEmoji(s.reaction.emoji); }
      }
    }catch(e){}
  },900);
}
function stopPolling(){ if(state.signalInt){clearInterval(state.signalInt);state.signalInt=null;} }

function floatEmoji(emoji){
  var layer=$('tm-reactions'); if(!layer) return;
  var span=document.createElement('span'); span.textContent=emoji;
  span.style.left=(10+Math.random()*70)+'%';
  layer.appendChild(span);
  setTimeout(function(){try{span.remove();}catch(_){}},2700);
}

window.tmStartCall=async function(kind){
  if(state.active) return;
  if(!window.TM_CALL_TARGET){ alert('Open a chat first to call someone.'); return; }
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){ alert('Calling not supported on this browser.'); return; }
  state.active=true; state.role='caller'; state.kind=kind||'audio';
  state.startedAt=Date.now(); state.lastIceCount={caller:0,callee:0};
  ctx();
  var isVideo = (state.kind === 'video');
  state.videoEnabled = isVideo;
  try{
    var constraints = { audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true} };
    if (isVideo) {
      constraints.video = { facingMode: state.facingMode, width:{ideal:1280}, height:{ideal:720} };
    } else {
      constraints.video = false;
    }
    state.localStream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch(e){
    state.active = false;
    var nm = (e && e.name) || '';
    if (nm === 'NotAllowedError' || nm === 'PermissionDeniedError') {
      alert('Camera and microphone permission is required.\n\nTap the lock icon -> Permissions -> Allow.');
    } else if (nm === 'NotFoundError') {
      alert('No camera or microphone found on this device.');
    } else if (nm === 'NotReadableError') {
      alert('Camera is already in use by another app. Close it and try again.');
    } else {
      alert('Could not start call: ' + nm + (e && e.message ? '\n' + e.message : ''));
    }
    return;
  }
  try { if (isVideo) activateVideoMode(); } catch(e){ console.warn('activateVideoMode', e); }
  try { history.pushState({tmCall:true}, '', location.href); } catch(_){}
  try{attachAnalyser(state.localStream,'local');}catch(_){}
  try { showInCall(window.TM_CALL_NAME||'Unknown',state.kind,window.TM_CALL_AVATAR||''); } catch(e){ console.warn('showInCall', e); }
  var st=$('tm-c-status'); if(st){st.textContent='Calling...';st.classList.add('ringing');}
  state.ringInt=setInterval(function(){ if (window.TMSound) window.TMSound.callRing(); },3200);
  setTimeout(function(){ if (window.TMSound) window.TMSound.callRing(); },100);
  startMeter();
  var r=await fetch('/api/calls/start/'+window.TM_CALL_TARGET+'?kind='+state.kind,{method:'POST',credentials:'same-origin'});
  if(!r.ok){ var reason='unknown'; try{var j=await r.json();reason=j.detail||reason;}catch(_){}
    cleanup(); alert('Could not start the call: '+reason); return; }
  var data=await r.json(); state.callId=data.call_id;
  await setupPeer();
  var offer=await state.pc.createOffer(); await state.pc.setLocalDescription(offer);
  await fetch('/api/calls/'+state.callId+'/offer',{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:offer.sdp,type:offer.type})});
  startPolling();
  state.timeoutInt=setTimeout(function(){
    if(state.pc&&!state.pc.currentRemoteDescription){ friendlyEnd('No answer'); }
  },45000);
};

window.tmAcceptIncoming=async function(){
  if(!state.incomingPayload) return;
  ringStop(); vib(0); if (window.TMHaptic) window.TMHaptic.tap();
  hideIncoming();
  state.active=true; state.role='callee';
  state.kind=state.incomingPayload.kind||'audio';
  state.callId=state.incomingPayload.call_id;
  state.lastIceCount={caller:0,callee:0};
  state.startedAt=Date.now();
  var isVideo = (state.kind === 'video');
  state.videoEnabled = isVideo;
  try{
    var constraints2 = { audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true} };
    if (isVideo) {
      constraints2.video = { facingMode: state.facingMode, width:{ideal:1280}, height:{ideal:720} };
    } else {
      constraints2.video = false;
    }
    state.localStream = await navigator.mediaDevices.getUserMedia(constraints2);
  }catch(e){ alert('Permission required.'); tmDeclineIncoming(); return; }
  try { if (isVideo) activateVideoMode(); } catch(e){ console.warn('activateVideoMode', e); }
  try { history.pushState({tmCall:true}, '', location.href); } catch(_){}
  try { history.pushState({tmCall:true}, '', location.href); } catch(_){}
  try{attachAnalyser(state.localStream,'local');}catch(_){}
  var p=state.incomingPayload;
  showInCall(p.from.name,state.kind,p.from.avatar_url||'');
  var st=$('tm-c-status'); if(st){st.textContent='Connecting...';st.classList.add('ringing');}
  startMeter();
  await fetch('/api/calls/'+state.callId+'/accept',{method:'POST',credentials:'same-origin'}).catch(function(){});
  await setupPeer();
  var tries=0;
  var waitOffer=setInterval(async function(){
    tries++;
    try{
      var r=await fetch('/api/calls/'+state.callId+'/state',{credentials:'same-origin'});
      if(!r.ok) return; var s=await r.json();
      if(s.offer){
        clearInterval(waitOffer);
        await state.pc.setRemoteDescription(new RTCSessionDescription(s.offer));
        var ans=await state.pc.createAnswer(); await state.pc.setLocalDescription(ans);
        await fetch('/api/calls/'+state.callId+'/answer',{method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:ans.sdp,type:ans.type})});
        startPolling();
      }
    }catch(e){}
    if(tries>25){ clearInterval(waitOffer); friendlyEnd('Connection failed'); }
  },600);
};

window.tmDeclineIncoming=async function(){
  if(!state.incomingPayload) return;
  var id=state.incomingPayload.call_id;
  ringStop(); vib(0); if (window.TMHaptic) window.TMHaptic.warn();
  hideIncoming(); cleanup();
  try{ await fetch('/api/calls/'+id+'/decline',{method:'POST',credentials:'same-origin'}); }catch(_){}
  state.incomingPayload=null;
};

window.tmEndCall=async function(silent){
  if (window.TMSound) window.TMSound.callEnd(); if (window.TMHaptic) window.TMHaptic.end();
  var id=state.callId, role=state.role;
  cleanup();
  if(id&&role&&!silent){
    try{ await fetch('/api/calls/'+id+'/end',{method:'POST',credentials:'same-origin'}); }catch(_){}
  }
};

function friendlyEnd(m){
  var st=$('tm-c-status'); if(st) st.textContent=m||'Call ended';
  var st2=$('tm-in-status'); if(st2) st2.textContent=m||'Call ended';
  setTimeout(function(){ tmEndCall(true); },1200);
}

function cleanup(){
  ringStop(); stopTimer(); stopPolling(); stopMeter(); vib(0);
  if(state.timeoutInt){ clearTimeout(state.timeoutInt); state.timeoutInt=null; }
  if(state.pc){ try{state.pc.close();}catch(_){} state.pc=null; }
  if(state.localStream){ try{state.localStream.getTracks().forEach(function(t){t.stop();});}catch(_){} state.localStream=null; }
  state.remoteStream=null;
  var ra=$('tm-remote-audio'); if(ra) ra.srcObject=null;
  var la=$('tm-local-audio'); if(la) la.srcObject=null;
  try{ deactivateVideoMode(); }catch(_){}
  hideInCall(); hideIncoming();
  state.analyserLocal=null; state.analyserRemote=null;
  state.micMuted=false; state.speakerOn=false; state.holdOn=false;
  var mb=$('tm-btn-mute'); if(mb) mb.classList.remove('tm-active');
  var sb=$('tm-btn-speaker'); if(sb) sb.classList.remove('tm-active');
  var wrap=$('tm-c-avatar-wrap'); if(wrap) wrap.classList.remove('tm-muted');
  // Remove pill
  var pill = $('tm-call-pill'); if(pill) pill.classList.remove('tm-show');
  // Pop the pushed history if still ours
  try { if (history.state && history.state.tmCall) { history.back(); } } catch(_){}
  state.active=false; state.role=null; state.callId=null; state.minimized=false;
  state.connectedAt=0; state.lastReactionAt=""; state.incomingPayload=null;
}
window.tmCleanupCall=cleanup;

async function pollIncoming(){
  if(state.active){ setTimeout(pollIncoming,2500); return; }
  try{
    var r=await fetch('/api/calls/incoming',{credentials:'same-origin'});
    if(r.ok){
      var d=await r.json();
      if(d.call&&!state.incomingPayload){
        state.incomingPayload=d.call;
        showIncoming(d.call);
        ringStart();
        if (window.TMHaptic) window.TMHaptic.incoming(); else vib([400,200,400]);
      }
    }
  }catch(e){}
  // Also refresh pill timer if minimized
  if (state.minimized && state.connectedAt) {
    var pt = $('tm-pill-status'); if (pt) pt.textContent = fmt(Math.floor((Date.now() - state.connectedAt) / 1000));
  }
  setTimeout(pollIncoming,2200);
}
setTimeout(pollIncoming,1200);

// Back button minimizes the call
window.addEventListener('popstate', function(e){
  if (state.active && !state.minimized) {
    minimizeCall();
  }
});

// Immediate poll when tab becomes visible
document.addEventListener('visibilitychange', function(){
  if (document.visibilityState === 'visible' && !state.active) {
    try { pollIncoming(); } catch(_){}
  }
});

// Unlock audio on first interaction (for incoming ringtone)
['touchstart','click','keydown'].forEach(function(ev){
  document.addEventListener(ev, function once(){
    try { ctx(); } catch(_){}
    document.removeEventListener(ev, once);
  }, { once: true, passive: true });
});

window.tmToggleMute=function(){
  if(!state.localStream) return;
  state.micMuted=!state.micMuted;
  state.localStream.getAudioTracks().forEach(function(t){t.enabled=!state.micMuted;});
  var b=$('tm-btn-mute'); if(b) b.classList.toggle('tm-active',state.micMuted);
  var w=$('tm-c-avatar-wrap'); if(w) w.classList.toggle('tm-muted',state.micMuted);
  if (window.TMSound) window.TMSound[state.micMuted?'mute':'unmute'](); if (window.TMHaptic) window.TMHaptic.mute();
};

window.tmToggleSpeaker=function(){
  state.speakerOn=!state.speakerOn;
  var b=$('tm-btn-speaker'); if(b) b.classList.toggle('tm-active',state.speakerOn);
  var ra=$('tm-remote-audio');
  if(ra&&ra.setSinkId){ try{ra.setSinkId(state.speakerOn?'speaker':'default').catch(function(){});}catch(_){} }
  if(ra) ra.volume=state.speakerOn?1.0:0.85;
  if (window.TMSound) window.TMSound.toggle(); if (window.TMHaptic) window.TMHaptic.tap();
};

window.tmToggleEmojiRow=function(){
  var r=$('tm-emoji-row'); if(r) r.classList.toggle('tm-show');
};

window.tmSendReaction=async function(emoji){
  if(!state.callId) return;
  floatEmoji(emoji); if (window.TMSound) window.TMSound.reaction(); if (window.TMHaptic) window.TMHaptic.reaction();
  try{
    await fetch('/api/calls/'+state.callId+'/reaction',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({emoji:emoji})});
  }catch(_){}
  var r=$('tm-emoji-row'); if(r) r.classList.remove('tm-show');
};

window.tmAddPerson=function(){
  alert('Group calling is coming in the next update.');
};

// Expose for chat button
window.startCall=function(kind){ window.tmStartCall(kind); };

// ---------- Camera toggle ----------

// ---------- Minimize / expand ----------
function minimizeCall(){
  if (!state.active) return;
  if (window.TMSound) window.TMSound.minimize(); if (window.TMHaptic) window.TMHaptic.tick();
  state.minimized = true;
  var incall = $('tm-incall'); if(incall) incall.classList.remove('tm-show');
  var incoming = $('tm-incoming'); if(incoming) incoming.classList.remove('tm-show');
  document.body.classList.remove('tm-in-call');
  var pill = $('tm-call-pill');
  if(pill){
    var pn = $('tm-pill-name');
    if(pn) pn.textContent = (state.role === 'caller'
      ? (window.TM_CALL_NAME || 'Call')
      : ((state.incomingPayload && state.incomingPayload.from.name) || 'Call'));
    var pa = $('tm-pill-avatar');
    if(pa){
      var avatarUrl = state.role === 'caller' ? window.TM_CALL_AVATAR : (state.incomingPayload && state.incomingPayload.from.avatar_url);
      var nm = state.role === 'caller' ? (window.TM_CALL_NAME || '?') : ((state.incomingPayload && state.incomingPayload.from.name) || '?');
      if (avatarUrl) { pa.innerHTML = '<img src="' + avatarUrl + '" alt="">'; }
      else { pa.textContent = init(nm); }
    }
    pill.classList.add('tm-show');
  }
  var pmb = $('tm-pill-mute');
  if(pmb) pmb.classList.toggle('tm-active', state.micMuted);
}

function expandCall(){
  if (!state.active) return;
  if (window.TMSound) window.TMSound.expand(); if (window.TMHaptic) window.TMHaptic.tick();
  state.minimized = false;
  var pill = $('tm-call-pill'); if(pill) pill.classList.remove('tm-show');
  if (state.incomingPayload && !state.connectedAt) {
    var inc = $('tm-incoming'); if(inc) inc.classList.add('tm-show');
  } else {
    var inc2 = $('tm-incall'); if(inc2) inc2.classList.add('tm-show');
  }
  document.body.classList.add('tm-in-call');
}
window.tmExpandCall = expandCall;

setInterval(function(){
  if (state.minimized && state.connectedAt) {
    var pt = $('tm-pill-status');
    if (pt) pt.textContent = fmt(Math.floor((Date.now() - state.connectedAt) / 1000));
  }
}, 500);
})();
