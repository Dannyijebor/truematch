// ============================================================
// TrueMatch — Premium sound + haptics engine (global)
// ============================================================
(function(){
"use strict";
var ctx = null;
function getCtx(){
  if (ctx) return ctx;
  try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch(_){}
  return ctx;
}
function unlock(){
  var c = getCtx(); if (!c) return;
  try { if (c.state === 'suspended') c.resume(); } catch(_){}
}

function tone(freq, opts){
  opts = opts || {};
  var c = getCtx(); if (!c) return;
  var dur = opts.dur || 0.15;
  var vol = opts.vol || 0.1;
  var type = opts.type || 'sine';
  var delay = opts.delay || 0;
  var attack = opts.attack || 0.008;
  try {
    var t0 = c.currentTime + delay;
    var osc = c.createOscillator();
    var g = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (opts.glide) osc.frequency.linearRampToValueAtTime(opts.glide, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    var f = c.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = opts.filter || 2600;
    f.Q.value = 0.7;
    osc.connect(f); f.connect(g); g.connect(c.destination);
    osc.start(t0); osc.stop(t0 + dur + 0.05);
  } catch(_){}
}
function arp(notes, opts){
  opts = opts || {};
  notes.forEach(function(f, i){
    tone(f, {
      dur: opts.dur || 0.1,
      vol: opts.vol || 0.08,
      type: opts.type || 'sine',
      delay: (opts.gap || 0.055) * i,
      filter: opts.filter || 2800,
    });
  });
}
function bell(freq, vol, dur){
  var c = getCtx(); if (!c) return;
  try {
    var t0 = c.currentTime;
    var carrier = c.createOscillator();
    var mod = c.createOscillator();
    var modG = c.createGain();
    var g = c.createGain();
    carrier.type = 'sine'; carrier.frequency.value = freq;
    mod.type = 'sine'; mod.frequency.value = freq * 2.5;
    modG.gain.value = freq * 0.35;
    mod.connect(modG); modG.connect(carrier.frequency);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol || 0.08, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + (dur || 0.32));
    carrier.connect(g); g.connect(c.destination);
    carrier.start(t0); mod.start(t0);
    carrier.stop(t0 + (dur || 0.32) + 0.05);
    mod.stop(t0 + (dur || 0.32) + 0.05);
  } catch(_){}
}
function whoosh(vol, dur){
  var c = getCtx(); if (!c) return;
  try {
    var t0 = c.currentTime;
    var len = Math.floor((dur || 0.18) * c.sampleRate);
    var buf = c.createBuffer(1, len, c.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < len; i++) data[i] = (Math.random()*2 - 1) * (1 - i/len);
    var src = c.createBufferSource(); src.buffer = buf;
    var f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 1100; f.Q.value = 2;
    var g = c.createGain();
    g.gain.setValueAtTime(vol || 0.05, t0);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + (dur || 0.18));
    src.connect(f); f.connect(g); g.connect(c.destination);
    src.start(t0);
  } catch(_){}
}

window.TMSound = {
  unlock: unlock,
  send: function(){ tone(587.33, {dur:0.08, vol:0.12, filter:3000}); tone(880, {dur:0.14, vol:0.09, delay:0.055, filter:3200}); },
  receive: function(){ bell(987.77, 0.075, 0.28); tone(659.25, {dur:0.2, vol:0.05, delay:0.08, filter:2200}); },
  voiceStart: function(){ tone(1200, {dur:0.05, vol:0.09, filter:3600}); tone(1600, {dur:0.06, vol:0.06, delay:0.035, filter:3800}); },
  voiceSend: function(){ arp([659.25, 987.77], {dur:0.09, vol:0.11, gap:0.055, filter:3200}); },
  voiceCancel: function(){ tone(180, {dur:0.18, vol:0.11, type:'triangle', filter:800, glide:130}); },
  play: function(){ tone(880, {dur:0.06, vol:0.07, filter:2800}); },
  pause: function(){ tone(587, {dur:0.06, vol:0.06, filter:2400}); },
  reply: function(){ whoosh(0.06, 0.16); tone(1400, {dur:0.04, vol:0.05, delay:0.08, filter:3800}); },
  callRing: function(){ tone(440, {dur:0.9, vol:0.075, filter:1800}); },
  incoming: function(){ tone(880, {dur:0.35, vol:0.12, filter:3000}); tone(660, {dur:0.35, vol:0.12, delay:0.38, filter:3000}); },
  callConnect: function(){ arp([523.25, 659.25, 783.99, 1046.5], {dur:0.09, vol:0.09, gap:0.07, filter:3200}); },
  callEnd: function(){ arp([1046.5, 783.99, 659.25, 523.25], {dur:0.11, vol:0.09, gap:0.06, filter:2800}); },
  lock: function(){ tone(300, {dur:0.06, vol:0.1, type:'triangle', filter:900}); tone(600, {dur:0.1, vol:0.07, delay:0.05, filter:2000}); },
  minimize: function(){ tone(660, {dur:0.07, vol:0.07, filter:2400, glide:440}); },
  expand: function(){ tone(440, {dur:0.07, vol:0.07, filter:2400, glide:660}); },
  mute: function(){ tone(400, {dur:0.06, vol:0.09, type:'triangle', filter:1400}); },
  unmute: function(){ tone(800, {dur:0.06, vol:0.08, type:'triangle', filter:2000}); },
  camera: function(){ tone(1400, {dur:0.045, vol:0.06, filter:3600}); },
  reaction: function(){ var b = 1100 + Math.random()*400; tone(b, {dur:0.06, vol:0.07, filter:3000}); tone(b*1.5, {dur:0.08, vol:0.05, delay:0.04, filter:3000}); },
  toggle: function(){ tone(700, {dur:0.05, vol:0.07, filter:2200}); },
  error: function(){ tone(180, {dur:0.22, vol:0.11, type:'triangle', filter:700, glide:120}); },
  tap: function(){ tone(2200, {dur:0.03, vol:0.04, filter:4500}); },
};

// Premium haptics
window.TMHaptic = (function(){
  function vib(pattern){ try { if (navigator.vibrate) navigator.vibrate(pattern); } catch(_){} }
  return {
    // ---- subtle UI ----
    tick:  function(){ vib(6); },              // theme picker tap, toggle
    tap:   function(){ vib(10); },             // generic tap
    soft:  function(){ vib(14); },             // picker selection
    // ---- messaging ----
    send:  function(){ vib([8, 22, 8]); },     // outgoing message
    receive: function(){ vib([12, 35, 12, 35, 12]); }, // incoming message
    reply: function(){ vib(12); },             // reply action
    deleted: function(){ vib([25, 50, 25]); },
    // ---- voice ----
    voiceStart: function(){ vib([10, 20, 10]); },
    voiceSend: function(){ vib([10, 30, 10, 30, 10]); },
    voiceCancel: function(){ vib([40, 60, 40]); },
    lock:  function(){ vib([18, 30, 50]); },
    swipeReady: function(){ vib(18); },
    swipeTrigger: function(){ vib([12, 25, 12]); },
    // ---- feedback ----
    success: function(){ vib([15, 40, 15]); },
    warn:  function(){ vib([30, 60, 30]); },
    error: function(){ vib([60, 45, 60, 45, 60]); },
    long:  function(){ vib(45); },
    // ---- calls ----
    incoming: function(){ vib([400, 200, 400]); },
    ring: function(){ vib([250, 150, 250, 150, 250]); },
    connect: function(){ vib([8, 30, 8]); },
    end: function(){ vib([20, 50, 20]); },
    mute: function(){ vib([10, 30, 10]); },
    camera: function(){ vib(12); },
    reaction: function(){ vib([8, 20, 8]); },
    // ---- social ----
    like: function(){ vib([8, 18, 8]); },
    follow: function(){ vib([14, 30, 14]); },
  };
})();

// Auto-unlock on first interaction
['touchstart','click','keydown'].forEach(function(ev){
  document.addEventListener(ev, function once(){
    unlock();
    document.removeEventListener(ev, once);
  }, { once: true, passive: true });
});
})();
