"""
apply_patch.py - connects your existing pages to the new server code.

Put this file in the SAME folder as admin.html, home.html, login.html and index.html, then run:
    python apply_patch.py

It makes a backup (file.html.bak) before changing anything, and it is safe to run twice.
If a spot cannot be found it tells you exactly which one, so nothing is changed halfway.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as f:
        return f.read().replace('\r\n', '\n')


def write(name, text):
    path = os.path.join(HERE, name)
    if not os.path.exists(path + '.bak'):
        shutil.copyfile(path, path + '.bak')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise ValueError('%s: expected to find the spot exactly once, found %d' % (label, n))
    return s.replace(old, new)


def between(s, start, end, new, label):
    i = s.find(start)
    j = s.find(end, i + 1) if i != -1 else -1
    if i == -1 or j == -1:
        raise ValueError('%s: start/end markers not found' % label)
    return s[:i] + new + s[j:]


# ------------------------------------------------------------------ admin.html
ADMIN_CHAT = '''// ---- Live chat (connected to the server: /api/admin/chats) ----
                activeId: null, chatSearch: '', newMsg: '', chats: [], chatBusy: false,
                get activeChat() { return this.chats.find(c => c.id === this.activeId); },
                get chatList() {
                    const q = this.chatSearch.trim().toLowerCase();
                    return this.chats.filter(c => !q || c.name.toLowerCase().includes(q)).sort((a, b) => this.lastOf(b).ts - this.lastOf(a).ts);
                },
                get unreadTotal() { return this.chats.reduce((t, c) => t + this.unreadOf(c), 0); },
                lastOf(c) { return c.messages[c.messages.length - 1]; },
                unreadOf(c) { return c.messages.filter(m => m.from === 'guest' && !m.read).length; },
                initials(n) { return n.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase(); },
                timeOf(ts) { return new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); },
                sameDay(a, b) { return new Date(a).toDateString() === new Date(b).toDateString(); },
                dayLabel(ts) {
                    if (this.sameDay(ts, Date.now())) return 'Today';
                    if (this.sameDay(ts, Date.now() - 86400000)) return 'Yesterday';
                    return new Date(ts).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
                },
                listTime(ts) {
                    if (this.sameDay(ts, Date.now())) return this.timeOf(ts);
                    if (this.sameDay(ts, Date.now() - 86400000)) return 'Yesterday';
                    return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                },
                showDate(c, i) { return i === 0 || !this.sameDay(c.messages[i].ts, c.messages[i - 1].ts); },
                isLastAdmin(c, i) { for (let j = c.messages.length - 1; j >= 0; j--) if (c.messages[j].from === 'admin') return j === i; return false; },
                chatUrl(c, action) { return '/api/admin/chats/' + encodeURIComponent(c.id) + '/' + action; },
                async loadChats() {
                    if (this.chatBusy || !this.isLoggedIn) return;
                    this.chatBusy = true;
                    try {
                        const before = this.activeChat ? this.activeChat.messages.length : 0;
                        this.chats = await this.api('/api/admin/chats');
                        const c = this.activeChat;
                        if (c) {
                            if (this.currentTab === 'messages' && this.unreadOf(c) > 0) {   // chat is open: mark as read
                                c.messages.forEach(m => { if (m.from === 'guest') m.read = true; });
                                this.api(this.chatUrl(c, 'read'), 'POST').catch(() => {});
                            }
                            if (c.messages.length !== before) this.scrollChat();
                        }
                    } catch (e) { /* ignore: will retry on the next tick */ }
                    finally { this.chatBusy = false; }
                },
                openChat(c) {
                    this.activeId = c.id;
                    c.messages.forEach(m => { if (m.from === 'guest') m.read = true; });
                    this.api(this.chatUrl(c, 'read'), 'POST').catch(() => {});
                    this.scrollChat();
                },
                scrollChat() { this.$nextTick(() => { const el = this.$refs.chatBody; if (el) el.scrollTop = el.scrollHeight; }); },
                async sendMsg() {
                    const text = this.newMsg.trim(), c = this.activeChat;
                    if (!text || !c) return;
                    this.newMsg = '';
                    c.messages.push({ from: 'admin', text, ts: Date.now(), seen: false });
                    this.scrollChat();
                    try { await this.api(this.chatUrl(c, 'reply'), 'POST', { text }); await this.loadChats(); }
                    catch (e) { alert(e.message); }
                },

                '''


def patch_admin():
    s = read('admin.html')
    if 'loadChats' in s:
        return 'admin.html: already patched'
    s = between(s, '// ---- Live chat (demo data; connect to a backend for real two-way chat) ----',
                '// ---- Print ----', ADMIN_CHAT, 'admin chat block')
    s = once(s, "const list = await this.api('/api/admin/bookings');",
             "this.loadChats();\n                        const list = await this.api('/api/admin/bookings');", 'admin loadAll')
    s = once(s, '}, 30000);', '}, 30000);\n                    setInterval(() => { if (this.isLoggedIn) this.loadChats(); }, 4000);', 'admin chat polling')
    write('admin.html', s)
    return 'admin.html: live chat connected'


# ------------------------------------------------------------------ home.html
def patch_home():
    s = read('home.html')
    if 'home-connect.js' in s:
        return 'home.html: already patched'
    s = once(s, '<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>',
             '<script src="ui.js"></script>\n<script src="shared.js"></script>\n<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>',
             'home scripts')
    s = once(s, '<!-- Chatbot -->', '<script src="home-connect.js"></script>\n\n<!-- Chatbot -->', 'home-connect.js')
    write('home.html', s)
    return 'home.html: calendar + live chat + delete account connected'


# ------------------------------------------------------------------ login.html
def patch_login():
    s = read('login.html')
    if 'const API =' in s:
        return 'login.html: already patched'
    s = once(s, 'function switchTab(mode) {',
             "const API = (location.protocol === 'file:' || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') && location.port !== '5000')) ? 'http://127.0.0.1:5000' : '';\n\n    function switchTab(mode) {",
             'login API constant')
    s = once(s, "'http://127.0.0.1:5000/api/auth/signup'", "API + '/api/auth/signup'", 'login signup url')
    s = once(s, "'http://127.0.0.1:5000/api/auth/login'", "API + '/api/auth/login'", 'login url')
    s = once(s, 'isLoggedIn: true', 'token: data.token,\n                isLoggedIn: true', 'login token')
    s = once(s, '<input type="text" id="signupName" placeholder="e.g. Maria Santos" required>',
             '<input type="text" id="signupName" placeholder="e.g. Maria Santos" required>\n                    <p class="hint-text">Enter your full name exactly as it appears on your valid ID.</p>',
             'login name hint')
    write('login.html', s)
    return 'login.html: works on Render + keeps the sign-in token'


# ------------------------------------------------------------------ index.html (reservation)
def patch_index():
    s = read('index.html')
    if 'must match the name on your valid ID' in s:
        return 'index.html: already patched'
    s = once(s, '<input type="text" id="fullName" placeholder="e.g. Maria Santos">',
             '<input type="text" id="fullName" placeholder="e.g. Maria Santos" readonly style="cursor: not-allowed;">\n'
             '        <p style="margin: 4px 0 0; font-size: 11px;">Name from your account. It must match the name on your valid ID.</p>',
             'index full name')
    s = once(s, '<input type="email" id="email" placeholder="maria@gmail.com">',
             '<input type="email" id="email" placeholder="maria@gmail.com" readonly style="cursor: not-allowed;">', 'index email')
    write('index.html', s)
    return 'index.html: name and email locked to the account'


def main():
    ok = True
    for fn in (patch_admin, patch_home, patch_login, patch_index):
        try:
            print('OK   ', fn())
        except FileNotFoundError as err:
            ok = False
            print('SKIP ', fn.__name__, '- file not found:', os.path.basename(err.filename))
        except ValueError as err:
            ok = False
            print('FAIL ', fn.__name__, '-', err, '(file left unchanged)')
    print('\nDone.' if ok else '\nSome files were not patched. Send me the message above and I will fix it.')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()