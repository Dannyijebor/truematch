// ============================================================
// TrueMatch base.js — extracted from base.html for progressive render
// ============================================================
(function(){
"use strict";


// ---------- Block 1 ----------

  // Top progress bar on navigation
  (function() {
    const bar = document.getElementById('tm-progress');
    if (!bar) return;
    document.addEventListener('click', function(e) {
      const a = e.target.closest('a');
      if (!a) return;
      const href = a.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('http') || a.target === '_blank') return;
      bar.classList.remove('active');
      void bar.offsetWidth;  // reflow
      bar.classList.add('active');
    });
    // Also trigger on form submits
    document.addEventListener('submit', function() {
      bar.classList.remove('active');
      void bar.offsetWidth;
      bar.classList.add('active');
    });
  })();


// ---------- Block 2 ----------

  // Unread notifications polling
  async function pollUnread() {
    try {
      const r = await fetch('/api/notifications/unread', {credentials: 'same-origin'});
      if (r.ok) {
        const d = await r.json();
        const badge = document.getElementById('tm-bell-badge');
        if (badge) {
          if (d.unread > 0) {
            badge.textContent = d.unread > 9 ? '9+' : d.unread;
            badge.classList.remove('hidden');
          } else {
            badge.classList.add('hidden');
          }
        }
      }
    } catch(e) {}
    setTimeout(pollUnread, 15000);
  }
  pollUnread();


// ---------- Block 3 ----------

// ---------- Command palette ----------
const TM_CMDS = [
  { label: 'Home feed',        href: '/feed',        icon: 'home' },
  { label: 'My matches',       href: '/app',         icon: 'target' },
  { label: 'Discover',         href: '/discover',    icon: 'compass' },
  { label: 'Messages',         href: '/messages',    icon: 'chat' },
  { label: 'People',           href: '/app/people',  icon: 'users' },
  { label: 'Notifications',    href: '/notifications', icon: 'bell' },
  { label: 'My resume',        href: '/app/resume',  icon: 'doc' },
  { label: 'Jobs from recruiters', href: '/jobs-posted', icon: 'briefcase' },
  { label: 'Hiring dashboard', href: '/hire',        icon: 'star' },
  { label: 'Settings',         href: '/settings',    icon: 'gear' },
  { label: 'Log out',          action: 'logout',     icon: 'exit' },
];

const TM_ICONS = {
  home: '<path d="M3 12L12 3l9 9v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-9z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>',
  compass: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  users: '<circle cx="9" cy="8" r="3"/><path d="M3 19c0-3 3-5 6-5s6 2 6 5"/>',
  bell: '<path d="M18 8A6 6 0 1 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  star: '<path d="M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z"/>',
  gear: '<circle cx="12" cy="12" r="3"/>',
  exit: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
};

let tmCmdActive = 0;
let tmCmdFiltered = [...TM_CMDS];

function tmOpenCmd() {
  const el = document.getElementById('tm-cmd');
  el.classList.remove('hidden');
  const input = document.getElementById('tm-cmd-input');
  input.value = '';
  tmCmdFiltered = [...TM_CMDS];
  tmCmdRender();
  setTimeout(() => input.focus(), 60);
}
function tmCloseCmd() {
  document.getElementById('tm-cmd').classList.add('hidden');
}
function tmCmdRender() {
  const list = document.getElementById('tm-cmd-list');
  if (!tmCmdFiltered.length) {
    list.innerHTML = '<div class="p-4 text-sm text-slate-500 text-center">No matches</div>';
    return;
  }
  list.innerHTML = tmCmdFiltered.map((c, i) => `
    <button class="tm-cmd-item w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-300 hover:bg-slate-900 ${i === tmCmdActive ? 'bg-slate-900 text-white' : ''}"
            data-i="${i}">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="w-4 h-4 opacity-70">${TM_ICONS[c.icon]||''}</svg>
      <span>${c.label}</span>
    </button>
  `).join('');
  list.querySelectorAll('.tm-cmd-item').forEach(b => {
    b.addEventListener('click', () => tmCmdGo(tmCmdFiltered[+b.dataset.i]));
  });
}
function tmCmdGo(cmd) {
  if (!cmd) return;
  tmCloseCmd();
  if (cmd.action === 'logout') {
    const f = document.createElement('form');
    f.method = 'POST'; f.action = '/logout';
    document.body.appendChild(f); f.submit();
  } else if (cmd.href) {
    window.location.href = cmd.href;
  }
}
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault(); tmOpenCmd();
  }
  const el = document.getElementById('tm-cmd');
  if (!el || el.classList.contains('hidden')) return;
  if (e.key === 'Escape') { e.preventDefault(); tmCloseCmd(); }
  else if (e.key === 'ArrowDown') {
    e.preventDefault();
    tmCmdActive = Math.min(tmCmdActive + 1, tmCmdFiltered.length - 1);
    tmCmdRender();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    tmCmdActive = Math.max(tmCmdActive - 1, 0);
    tmCmdRender();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    tmCmdGo(tmCmdFiltered[tmCmdActive]);
  }
});
document.addEventListener('input', (e) => {
  if (e.target.id !== 'tm-cmd-input') return;
  const q = e.target.value.toLowerCase().trim();
  tmCmdFiltered = TM_CMDS.filter(c => c.label.toLowerCase().includes(q));
  tmCmdActive = 0;
  tmCmdRender();
});
document.getElementById('tm-cmd').addEventListener('click', (e) => {
  if (e.target.id === 'tm-cmd') tmCloseCmd();
});


// ---------- Block 4 ----------

let tmFeedbackSentiment = null;
function tmFeedbackOpen() {
  document.getElementById('tm-feedback').classList.remove('hidden');
  document.getElementById('tm-feedback-trigger').style.display = 'none';
}
function tmFeedbackClose() {
  document.getElementById('tm-feedback').classList.add('hidden');
  document.getElementById('tm-feedback-trigger').style.display = '';
  document.getElementById('tm-feedback-form').classList.remove('hidden');
  document.getElementById('tm-feedback-comment').classList.add('hidden');
  tmFeedbackSentiment = null;
}
function tmFeedbackSend(sent) {
  tmFeedbackSentiment = sent;
  document.getElementById('tm-feedback-form').classList.add('hidden');
  document.getElementById('tm-feedback-comment').classList.remove('hidden');
}
async function tmFeedbackSubmit() {
  const txt = document.getElementById('tm-feedback-text').value;
  try {
    await fetch('/api/feedback', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        page: location.pathname,
        sentiment: tmFeedbackSentiment,
        comment: txt || null,
      })
    });
    document.getElementById('tm-feedback-text').value = '';
    document.getElementById('tm-feedback').innerHTML =
      '<div class="text-center py-4"><div class="text-2xl mb-2">🙏</div><div class="text-sm text-slate-300">Thanks — we read every one.</div></div>';
    setTimeout(tmFeedbackClose, 1600);
  } catch(e) {}
}


// ---------- Block 5 ----------

window.TM_USER_ID = "{{ user.id if user else '' }}";
window.TM_USER_NAME = "{{ user.full_name if user else '' }}";
window.TM_USER_AVATAR = "{% if user_profile and user_profile.avatar_url %}{{ user_profile.avatar_url }}{% endif %}";


})();
