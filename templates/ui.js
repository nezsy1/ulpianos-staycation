/* ui.js - elegant replacements for alert(), confirm() and prompt()
   Usage (inside an async function):
     await UI.alert('Message', { title: 'Notice' });
     if (await UI.confirm('Are you sure?', { title: 'Log Out', okText: 'Log Out', danger: true })) { ... }
     const text = await UI.prompt('Type your email', { placeholder: 'you@email.com' });   // null if cancelled
*/
const UI = (() => {
    const ICONS = {
        info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        question: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        warn: '<svg viewBox="0 0 24 24"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    };
    const CSS = `
    .ui-overlay{position:fixed;inset:0;z-index:100000;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.62);backdrop-filter:blur(6px)}
    .ui-overlay.open{display:flex}
    .ui-card{width:100%;max-width:410px;background:#fffdf8;border:1px solid #e7dcc6;border-radius:20px;overflow:hidden;box-shadow:0 30px 70px rgba(15,23,42,.45);font-family:'Montserrat',sans-serif;animation:uiPop .22s ease}
    @keyframes uiPop{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:none}}
    .ui-head{display:flex;align-items:center;gap:12px;padding:18px 22px;background:linear-gradient(135deg,#0f172a,#1e2a47);border-bottom:2px solid #c9a96e}
    .ui-ico{width:36px;height:36px;border-radius:50%;border:1.5px solid #c9a96e;background:rgba(201,169,110,.12);display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .ui-ico svg{width:18px;height:18px;stroke:#c9a96e;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .ui-title{margin:0;font-family:'Playfair Display',serif;font-size:18px;font-weight:600;letter-spacing:.4px;color:#fff}
    .ui-body{padding:22px 24px 6px}
    .ui-msg{margin:0;font-size:13.5px;line-height:1.7;color:#334155;white-space:pre-line;word-break:break-word}
    .ui-input{display:none;width:100%;margin-top:14px;padding:12px 14px;border:1.5px solid #e0d6bf;border-radius:10px;font-size:13.5px;font-family:inherit;outline:none;background:#fff;color:#0f172a}
    .ui-input:focus{border-color:#c9a96e;box-shadow:0 0 0 3px rgba(201,169,110,.22)}
    .ui-foot{display:flex;gap:10px;padding:20px 24px 24px}
    .ui-btn{flex:1;padding:13px 14px;border-radius:10px;font-family:'Montserrat',sans-serif;font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;cursor:pointer;transition:.22s;border:1px solid transparent}
    .ui-btn.primary{background:linear-gradient(135deg,#1e2a47,#0f172a);color:#fff;border-color:#c9a96e}
    .ui-btn.primary:hover{background:#c9a96e;color:#0f172a}
    .ui-btn.danger{background:#9b2c2c;color:#fff;border-color:#9b2c2c}
    .ui-btn.danger:hover{background:#7f1d1d;border-color:#7f1d1d}
    .ui-btn.ghost{background:transparent;color:#475569;border-color:#d9c9a3}
    .ui-btn.ghost:hover{background:#faf3e3;color:#1e2a47}
    body.dark-mode .ui-card{background:#1c1d21;border-color:#30323a}
    body.dark-mode .ui-msg{color:#c4c7cc}
    body.dark-mode .ui-input{background:#26272c;border-color:#30323a;color:#e8eaed}
    body.dark-mode .ui-btn.ghost{color:#e8eaed;border-color:#3a3c44}
    body.dark-mode .ui-btn.ghost:hover{background:#26272c;color:#fff}
    body.dark-mode .ui-btn.primary{background:#c9a96e;color:#0f172a}
    body.dark-mode .ui-btn.primary:hover{background:#b08d57;color:#fff}
    `;
    let root = null, queue = Promise.resolve();

    function ensure() {
        if (root) return;
        const st = document.createElement('style');
        st.textContent = CSS;
        document.head.appendChild(st);
        root = document.createElement('div');
        root.className = 'ui-overlay';
        root.innerHTML = '<div class="ui-card" role="dialog" aria-modal="true">' +
            '<div class="ui-head"><span class="ui-ico"></span><h3 class="ui-title"></h3></div>' +
            '<div class="ui-body"><p class="ui-msg"></p><input class="ui-input" type="text" autocomplete="off"></div>' +
            '<div class="ui-foot"><button type="button" class="ui-btn ghost ui-cancel"></button><button type="button" class="ui-btn primary ui-ok"></button></div></div>';
        document.body.appendChild(root);
    }

    function show(o) {
        return new Promise(resolve => {
            ensure();
            const $ = s => root.querySelector(s);
            const inp = $('.ui-input'), ok = $('.ui-ok'), cancel = $('.ui-cancel');
            $('.ui-title').textContent = o.title;
            $('.ui-msg').textContent = o.message || '';
            $('.ui-ico').innerHTML = ICONS[o.icon || 'info'];
            inp.style.display = o.input ? 'block' : 'none';
            inp.value = '';
            inp.placeholder = o.placeholder || '';
            ok.textContent = o.okText || 'OK';
            ok.className = 'ui-btn ui-ok ' + (o.danger ? 'danger' : 'primary');
            cancel.textContent = o.cancelText || 'Cancel';
            cancel.style.display = o.showCancel ? '' : 'none';

            const done = v => {
                root.classList.remove('open');
                document.removeEventListener('keydown', key, true);
                ok.onclick = cancel.onclick = root.onclick = null;
                resolve(v);
            };
            const accept = () => done(o.input ? inp.value : true);
            const dismiss = () => done(o.input ? null : false);
            const key = e => {
                if (e.key === 'Escape') { e.preventDefault(); dismiss(); }
                else if (e.key === 'Enter') { e.preventDefault(); accept(); }
            };
            ok.onclick = accept;
            cancel.onclick = dismiss;
            root.onclick = e => { if (e.target === root) dismiss(); };
            document.addEventListener('keydown', key, true);
            root.classList.add('open');
            setTimeout(() => (o.input ? inp : ok).focus(), 30);
        });
    }

    const run = o => { const p = queue.then(() => show(o)); queue = p.catch(() => {}); return p; };

    return {
        alert: (message, opts = {}) => run({ title: opts.title || 'Notice', message, icon: opts.icon || 'info', okText: opts.okText || 'OK', showCancel: false }).then(() => {}),
        confirm: (message, opts = {}) => run({ title: opts.title || 'Please Confirm', message, icon: opts.danger ? 'warn' : 'question', okText: opts.okText || 'OK', cancelText: opts.cancelText || 'Cancel', danger: !!opts.danger, showCancel: true }),
        prompt: (message, opts = {}) => run({ title: opts.title || 'Please Confirm', message, icon: opts.danger ? 'warn' : 'question', okText: opts.okText || 'OK', cancelText: opts.cancelText || 'Cancel', danger: !!opts.danger, showCancel: true, input: true, placeholder: opts.placeholder })
    };
})();