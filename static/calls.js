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
      // Only update the initials span, NEVER overwrite the whole pip
      // (it contains the local <video> element)
      var initSpan = pip.querySelector('.tm-self-pip-init');
      if (initSpan) {
        if (window.TM_USER_AVATAR) {
          initSpan.style.backgroundImage = 'url(' + window.TM_USER_AVATAR + ')';
          initSpan.style.backgroundSize = 'cover';
          initSpan.style.backgroundPosition = 'center';
          initSpan.textContent = '';
        } else {
          initSpan.textContent = init(window.TM_USER_NAME);
        }
      }
    }
    try { buildMeter($('tm-c-meter'),48); } catch(e){ console.warn('meter', e); }
    document.body.classList.add('tm-in-call');
    var el=$('tm-incall');
    if (el) {
      el.classList.add('tm-show');
      el.style.display = '';   // rely on .tm-show class, no inline overrides
    } else {
      console.error('tm-incall element missing!');
    }
  } catch(e) {
    console.error('showInCall threw', e);
    alert('Call UI error: ' + e.message);
  }
}
function hideInCall(){
  var el=$('tm-incall');
  if(el){ el.classList.remove('tm-show'); el.style.display=''; }
  var el2=$('tm-incoming');
  if(el2){ el2.classList.remove('tm-show'); el2.style.display=''; }
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

async function setupPeer(role){
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
    var side=role || ((state.role==='caller')?'caller':'callee');
    fetch('/api/calls/'+state.callId+'/ice?side='+side,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate:ev.candidate.toJSON()})}).catch(function(){});
  };
  pc.onconnectionstatechange=function(){
    var s=pc.connectionState, st=$('tm-c-status');
    if(s==='connected'){
      state.retryCount = 0;
      if(state.disconnectTimer){ clearTimeout(state.disconnectTimer); state.disconnectTimer=null; }
      if(!state.connectedAt){
        startTimer();
        if(window.TMSound) window.TMSound.callConnect();
        if(window.TMHaptic) window.TMHaptic.connect();
      }
      if(st) st.classList.remove('ringing');
      var ps=$('tm-pill-status'); if(ps) ps.textContent='Connected';
    } else if(s==='disconnected'){
      if(st) st.textContent='Reconnecting…';
      if(!state.disconnectTimer && state.role==='caller'){
        state.disconnectTimer = setTimeout(function(){
          state.disconnectTimer = null;
          if(pc.connectionState!=='connected' && state.role==='caller'){
            try{ triggerRenegotiation(); }catch(_){}
          }
        }, 4000);
      }
      state.retryCount = (state.retryCount || 0) + 1;
      if(state.retryCount > 30) {
        if(window.TMSound) window.TMSound.error();
        friendlyEnd('Connection lost');
      }
    } else if(s==='failed'){
      if(st) st.textContent='Reconnecting…';
      if(state.role==='caller'){ try{ triggerRenegotiation(); }catch(_){} }
      state.retryCount = (state.retryCount || 0) + 1;
      if(state.retryCount > 12) {
        friendlyEnd('Connection lost');
      }
    }
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
      if(s.offer&&s.offer.sdp&&s.offer.sdp!==state.appliedOfferSdp&&s.offer.sdp!==state.myLocalOfferSdp){
        try{
          await state.pc.setRemoteDescription(new RTCSessionDescription(s.offer));
          state.appliedOfferSdp=s.offer.sdp;
          if(me==='callee'){
            var ans=await state.pc.createAnswer();
            await state.pc.setLocalDescription(ans);
            state.appliedAnswerSdp=ans.sdp;
            await fetch('/api/calls/'+state.callId+'/answer',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:ans.sdp,type:ans.type})});
          }
        }catch(e){}
      }
      if(me==='caller'&&s.answer&&s.answer.sdp&&s.answer.sdp!==state.appliedAnswerSdp&&state.pc.signalingState!=='stable'){
        try{await state.pc.setRemoteDescription(new RTCSessionDescription(s.answer));state.appliedAnswerSdp=s.answer.sdp;}catch(e){}
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

  // --- CRITICAL: push history state FIRST (synchronous, before any await) ---
  // This guarantees the back button is trapped the moment a call starts.
  state.active=true; state.role='caller'; state.kind=kind||'audio';
  state.startedAt=Date.now(); state.lastIceCount={caller:0,callee:0};
  state.minimized=false;
  window.TM_CALL_STATE = state;
  try { history.pushState({tmCall:true}, '', location.href); } catch(_){}
  // ---

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
  try{attachAnalyser(state.localStream,'local');}catch(_){}
  try { showInCall(window.TM_CALL_NAME||'Unknown',state.kind,window.TM_CALL_AVATAR||''); } catch(e){ console.warn('showInCall', e); }
  // Re-attach the local video stream (showInCall may have reset the DOM)
  setTimeout(function(){
    try { if (isVideo) activateVideoMode(); } catch(e){ console.warn('re-activate', e); }
  }, 100);
  var st=$('tm-c-status'); if(st){st.textContent='Calling...';st.classList.add('ringing');}
  state.ringInt=setInterval(function(){ if (window.TMSound) window.TMSound.callRing(); },3200);
  setTimeout(function(){ if (window.TMSound) window.TMSound.callRing(); },100);
  startMeter();
  var r=await fetch('/api/calls/start/'+window.TM_CALL_TARGET+'?kind='+state.kind,{method:'POST',credentials:'same-origin'});
  if(!r.ok){ var reason='unknown'; try{var j=await r.json();reason=j.detail||reason;}catch(_){}
    cleanup(); alert('Could not start the call: '+reason); return; }
  var data=await r.json(); state.callId=data.call_id;
  await setupPeer('caller');
  var offer=await state.pc.createOffer(); await state.pc.setLocalDescription(offer);
  await fetch('/api/calls/'+state.callId+'/offer',{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:offer.sdp,type:offer.type})});
  startPolling();
  state.timeoutInt=setTimeout(function(){
    // Only fire if we're still ringing (no connection yet)
    if (state.connectedAt) return;
    if (state.pc && !state.pc.currentRemoteDescription) {
      friendlyEnd('No answer');
    }
  }, 60000);
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
  try{attachAnalyser(state.localStream,'local');}catch(_){}
  var p=state.incomingPayload;
  showInCall(p.from.name,state.kind,p.from.avatar_url||'');
  var st=$('tm-c-status'); if(st){st.textContent='Connecting...';st.classList.add('ringing');}
  startMeter();
  await fetch('/api/calls/'+state.callId+'/accept',{method:'POST',credentials:'same-origin'}).catch(function(){});
  await setupPeer('callee');
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
  // Show the message for 1.2s, then force-hide + cleanup
  setTimeout(function(){
    try {
      var incall = $('tm-incall');
      if (incall) { incall.classList.remove('tm-show'); incall.style.display=''; }
      var incoming = $('tm-incoming');
      if (incoming) { incoming.classList.remove('tm-show'); incoming.style.display=''; }
      var pill = $('tm-call-pill'); if(pill) pill.classList.remove('tm-show');
      document.body.classList.remove('tm-in-call');
    } catch(_){}
    tmEndCall(true);
  },1200);
}

function cleanup(){
  ringStop(); stopTimer(); stopPolling(); stopMeter(); vib(0);
  // Force-hide both call screens (removing inline display:flex we set earlier)
  try {
    var incall = $('tm-incall');
    if (incall) {
      incall.classList.remove('tm-show');
      incall.style.display = '';
      incall.classList.remove('tm-video-mode','tm-no-cam');
    }
    var incoming = $('tm-incoming');
    if (incoming) {
      incoming.classList.remove('tm-show');
      incoming.style.display = '';
    }
    var pill = $('tm-call-pill');
    if (pill) pill.classList.remove('tm-show');
    document.body.classList.remove('tm-in-call');
  } catch(_){}
  // Remove the pushed history entries from this call
  try {
    if (history.state && history.state.tmCall) {
      history.replaceState(null, '', location.href);
    }
  } catch(_){}
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
  state.appliedOfferSdp=null; state.appliedAnswerSdp=null; state.myLocalOfferSdp=null;
  if(state.disconnectTimer){ clearTimeout(state.disconnectTimer); state.disconnectTimer=null; }
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
  if (window.TMSound) window.TMSound.minimize();
  if (window.TMHaptic) window.TMHaptic.tick();
  state.minimized = true;
  var incall = $('tm-incall');
  if (incall) { incall.classList.remove('tm-show'); incall.style.display = ''; }
  var incoming = $('tm-incoming');
  if (incoming) { incoming.classList.remove('tm-show'); incoming.style.display = ''; }
  document.body.classList.remove('tm-in-call');
  var pill = $('tm-call-pill');
  if (!pill) return;
  var name, avatarUrl;
  if (state.role === 'caller') {
    name = window.TM_CALL_NAME || 'Call';
    avatarUrl = window.TM_CALL_AVATAR || '';
  } else {
    name = (state.incomingPayload && state.incomingPayload.from.name) || 'Call';
    avatarUrl = (state.incomingPayload && state.incomingPayload.from.avatar_url) || '';
  }
  var pn = $('tm-pill-name'); if (pn) pn.textContent = name;
  var pav = $('tm-pill-avatar');
  if (pav) {
    var wantVideo = (state.kind === 'video' && state.remoteStream);
    if (wantVideo) {
      pav.classList.add('tm-pill-avatar--video');
      pav.innerHTML = '<video class="tm-pill-video" autoplay playsinline muted></video>';
      var v = pav.querySelector('video');
      if (v) { v.srcObject = state.remoteStream; v.play().catch(function(){}); }
    } else {
      pav.classList.remove('tm-pill-avatar--video');
      if (avatarUrl) pav.innerHTML = '<img src="' + avatarUrl + '" alt="">';
      else pav.textContent = init(name);
    }
  }
  var pt = $('tm-pill-status');
  if (pt) {
    if (state.connectedAt) pt.textContent = fmt(Math.floor((Date.now() - state.connectedAt) / 1000));
    else pt.textContent = (state.role === 'caller' ? 'Calling...' : 'Connecting...');
  }
  var pmb = $('tm-pill-mute');
  if (pmb) pmb.classList.toggle('tm-active', state.micMuted);
  pill.classList.toggle('tm-call-pill--video', state.kind === 'video');
  pill.classList.add('tm-show');
}

window.tmMinimizeFromButton = function(e){
  if (e) { e.preventDefault(); e.stopPropagation(); }
  if (!state.active) return;
  try { minimizeCall(); } catch(err) { console.warn('minimize failed', err); }
};


function expandCall(){
  if (!state.active) return;
  if (window.TMSound) window.TMSound.expand();
  if (window.TMHaptic) window.TMHaptic.tick();
  state.minimized = false;
  var pill = $('tm-call-pill');
  if (pill) pill.classList.remove('tm-show');
  if (state.incomingPayload && !state.connectedAt) {
    var inc = $('tm-incoming');
    if (inc) { inc.classList.add('tm-show'); inc.style.display = ''; }
  } else {
    var inc2 = $('tm-incall');
    if (inc2) { inc2.classList.add('tm-show'); inc2.style.display = ''; }
    if (state.kind === 'video' && state.localStream) {
      try {
        var lv = $('tm-local-video');
        if (lv) {
          if (lv.srcObject !== state.localStream) lv.srcObject = state.localStream;
          lv.play().catch(function(){});
        }
      } catch(_){}
    }
  }
  document.body.classList.add('tm-in-call');
  try { history.pushState({tmCall:true}, '', location.href); } catch(_){}
}
window.tmExpandCall = expandCall;

// ---------- Draggable pill ----------
(function(){
  var pill = null;
  var startX=0, startY=0, baseX=0, baseY=0, dragging=false;
  var POS_KEY = 'tm_pill_pos';

  function ensurePill() {
    if (pill) return pill;
    pill = document.getElementById('tm-call-pill');
    if (!pill) return null;
    return pill;
  }

  function applyPos(x, y) {
    var p = ensurePill(); if (!p) return;
    p.style.left = x + 'px';
    p.style.right = 'auto';
    p.style.top = y + 'px';
    try { sessionStorage.setItem(POS_KEY, JSON.stringify({ x: x, y: y })); } catch(_){}
  }

  function restorePos() {
    var p = ensurePill(); if (!p) return;
    try {
      var v = sessionStorage.getItem(POS_KEY);
      if (!v) return;
      var pos = JSON.parse(v);
      if (typeof pos.x === 'number' && typeof pos.y === 'number') {
        p.style.left = pos.x + 'px';
        p.style.right = 'auto';
        p.style.top = pos.y + 'px';
      }
    } catch(_){}
  }

  document.addEventListener('touchstart', function(e){
    var t = e.target.closest && e.target.closest('.tm-call-pill');
    if (!t) return;
    // don't drag if tapping on the end/mute buttons
    if (e.target.closest('.tm-call-pill-end') || e.target.closest('.tm-call-pill-btn')) return;
    var p = ensurePill(); if (!p) return;
    var r = p.getBoundingClientRect();
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    baseX = r.left;
    baseY = r.top;
    dragging = true;
    p.style.transition = 'none';
    try { p.style.left = baseX + 'px'; p.style.right = 'auto'; p.style.top = baseY + 'px'; } catch(_){}
  }, { passive: true });

  document.addEventListener('touchmove', function(e){
    if (!dragging) return;
    var dx = e.touches[0].clientX - startX;
    var dy = e.touches[0].clientY - startY;
    if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
    var p = ensurePill(); if (!p) return;
    var w = window.innerWidth, h = window.innerHeight;
    var pr = p.getBoundingClientRect();
    var pw = pr.width, ph = pr.height;
    var x = Math.max(6, Math.min(w - pw - 6, baseX + dx));
    var y = Math.max(60, Math.min(h - ph - 60, baseY + dy));
    p.style.left = x + 'px';
    p.style.top = y + 'px';
    if (e.cancelable) e.preventDefault();
  }, { passive: false });

  document.addEventListener('touchend', function(){
    if (!dragging) return;
    dragging = false;
    var p = ensurePill(); if (!p) return;
    p.style.transition = '';
    var r = p.getBoundingClientRect();
    try { sessionStorage.setItem(POS_KEY, JSON.stringify({ x: r.left, y: r.top })); } catch(_){}
  }, { passive: true });

  // Restore position when pill shows
  document.addEventListener('transitionend', function(){ restorePos(); }, true);
  var obs = new MutationObserver(function(){
    var p = ensurePill();
    if (p && p.classList.contains('tm-show')) restorePos();
  });
  setTimeout(function(){
    var p = ensurePill();
    if (p) obs.observe(p, { attributes: true, attributeFilter: ['class'] });
  }, 500);
})();

setInterval(function(){
  if (!state.minimized) return;
  var pt = $('tm-pill-status');
  if (!pt) return;
  if (state.connectedAt) {
    pt.textContent = fmt(Math.floor((Date.now() - state.connectedAt) / 1000));
  } else {
    pt.textContent = (state.role === 'caller' ? 'Calling…' : 'Connecting…');
  }
}, 500);

// ============================================================
// BACK BUTTON GUARD — closure-based, references state directly
// ============================================================
try {
  window.addEventListener('popstate', function(e){
    // No active call → let the browser navigate normally
    if (!state.active) return;

    // Active call → trap the navigation and minimize
    try { history.pushState({tmCall:true}, '', location.href); } catch(_){}

    // Force-minimize (direct DOM ops + class swaps)
    try {
      // If already minimized, do nothing extra
      if (state.minimized) return;

      // Set state
      state.minimized = true;

      // Hide full-screen UI
      var incall = document.getElementById('tm-incall');
      if (incall) {
        incall.classList.remove('tm-show');
        incall.style.display = 'none';
        setTimeout(function(){ if (incall) incall.style.display = ''; }, 20);
      }
      var incoming = document.getElementById('tm-incoming');
      if (incoming) {
        incoming.classList.remove('tm-show');
        incoming.style.display = 'none';
        setTimeout(function(){ if (incoming) incoming.style.display = ''; }, 20);
      }
      document.body.classList.remove('tm-in-call');

      // Populate + show the pill
      var pill = document.getElementById('tm-call-pill');
      if (pill) {
        // Name
        var nm = (state.role === 'caller')
          ? (window.TM_CALL_NAME || 'Call')
          : ((state.incomingPayload && state.incomingPayload.from.name) || 'Call');
        var av = (state.role === 'caller')
          ? (window.TM_CALL_AVATAR || '')
          : ((state.incomingPayload && state.incomingPayload.from.avatar_url) || '');

        var nameEl = document.getElementById('tm-pill-name');
        if (nameEl) nameEl.textContent = nm;

        var avEl = document.getElementById('tm-pill-avatar');
        if (avEl) {
          if (state.kind === 'video' && state.remoteStream) {
            avEl.classList.add('tm-pill-avatar--video');
            avEl.innerHTML = '<video class="tm-pill-video" autoplay playsinline muted></video>';
            var v = avEl.querySelector('video');
            if (v) { v.srcObject = state.remoteStream; v.play().catch(function(){}); }
          } else {
            avEl.classList.remove('tm-pill-avatar--video');
            if (av) avEl.innerHTML = '<img src="' + av + '" alt="">';
            else {
              var ini = (nm || '?').trim().split(/\s+/);
              avEl.textContent = ((ini[0] || '?')[0] || '?').toUpperCase();
            }
          }
        }

        var stEl = document.getElementById('tm-pill-status');
        if (stEl) {
          if (state.connectedAt) {
            var sec = Math.floor((Date.now() - state.connectedAt) / 1000);
            var m = Math.floor(sec / 60), s = sec % 60;
            stEl.textContent = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
          } else {
            stEl.textContent = (state.role === 'caller' ? 'Calling…' : 'Connecting…');
          }
        }

        var muteBtn = document.getElementById('tm-pill-mute');
        if (muteBtn) muteBtn.classList.toggle('tm-active', state.micMuted);

        pill.classList.add('tm-show');
      }

      // Also run the full minimize for sound/vibration/haptic consistency
      if (typeof minimizeCall === 'function') {
        try { minimizeCall(); } catch(_) { /* silent — DOM already handled above */ }
      }
    } catch(err) {
      console.warn('popstate minimize failed:', err);
    }
  }, false);

  // Push a state now so the back button has something to pop
  try {
    if (!history.state || !history.state.tmCall) {
      history.pushState({tmCall:true}, '', location.href);
    }
  } catch(_){}

  // Before unload safety
  window.addEventListener('beforeunload', function(e){
    if (state.active) {
      e.preventDefault();
      e.returnValue = '';
      return '';
    }
  });
} catch(err) {
  console.warn('history guard setup failed:', err);
}

})();

// ---------- Premium widget: sync pill buttons + keep nav visible ----------
(function premiumPillSync(){
  function bind(fullId, pillId){
    var full = document.getElementById(fullId);
    var pill = document.getElementById(pillId);
    if (!full || !pill) return;
    var sync = function(){ pill.classList.toggle('tm-active', full.classList.contains('tm-active')); };
    sync();
    try { new MutationObserver(sync).observe(full, { attributes:true, attributeFilter:['class'] }); } catch(_){}
  }
  bind('tm-btn-mute', 'tm-pill-mute');
  bind('tm-btn-speaker', 'tm-pill-speaker');

  // When the top widget is visible, ensure nav is not hidden by tm-in-call
  var pill = document.getElementById('tm-call-pill');
  if (pill) {
    var ensureNav = function(){
      if (pill.classList.contains('tm-show')) {
        document.body.classList.remove('tm-in-call');
      }
    };
    ensureNav();
    try { new MutationObserver(ensureNav).observe(pill, { attributes:true, attributeFilter:['class'] }); } catch(_){}
  }
})();

// ---------- Renegotiation + rehydration (call persistence across navigation) ----------
async function triggerRenegotiation(){
  if(!state.pc || !state.callId) return;
  try {
    var offer = await state.pc.createOffer({iceRestart:true});
    await state.pc.setLocalDescription(offer);
    state.myLocalOfferSdp = offer.sdp;
    await fetch('/api/calls/'+state.callId+'/offer',{
      method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sdp:offer.sdp,type:offer.type})
    });
  } catch(e){ console.warn('renegotiate failed', e); }
}

async function rehydrateCall(){
  if(state.active) return;
  try {
    var r = await fetch('/api/calls/active',{credentials:'same-origin'});
    if(!r.ok) return;
    var data = await r.json();
    if(!data || !data.call_id) return;

    // Rebuild local state
    state.active = true;
    state.role = data.you_are;
    state.kind = data.kind;
    state.callId = data.call_id;
    state.lastIceCount = {caller:0, callee:0};
    state.startedAt = Date.now();
    state.appliedOfferSdp = null;
    state.appliedAnswerSdp = null;
    state.myLocalOfferSdp = null;

    var isVideo = (state.kind === 'video');
    state.videoEnabled = isVideo;
    var constraints = { audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true} };
    constraints.video = isVideo ? { facingMode: state.facingMode, width:{ideal:1280}, height:{ideal:720} } : false;
    try {
      state.localStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch(e){
      console.warn('rehydrate getUserMedia failed', e);
      state.active = false;
      return;
    }
    try { if(isVideo) activateVideoMode(); } catch(_){}
    try { attachAnalyser(state.localStream,'local'); } catch(_){}

    // Show the top pill widget (not full-screen) so user sees call continues
    var pill = $('tm-call-pill');
    if(pill) pill.classList.add('tm-show');
    var pn = $('tm-pill-name'); if(pn) pn.textContent = data.peer.name || 'Call';
    var pa = $('tm-pill-avatar');
    if(pa){
      if(data.peer.avatar_url){ pa.innerHTML = '<img src="'+data.peer.avatar_url+'" alt="">'; }
      else { pa.textContent = ((data.peer.name||'?')[0]||'?').toUpperCase(); }
    }
    var ps = $('tm-pill-status'); if(ps) ps.textContent = 'Reconnecting…';

    await setupPeer(state.role);

    if(state.role === 'caller'){
      try { await triggerRenegotiation(); } catch(_){}
    }
    startPolling();
    startMeter();
  } catch(e){
    console.warn('rehydrate failed', e);
  }
}

// Run on load — with a small delay so other init settles
setTimeout(function(){ try { rehydrateCall(); } catch(_){} }, 400);
