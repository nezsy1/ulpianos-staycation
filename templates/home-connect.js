/* home-connect.js - connects home.html to the server (app.py):
   1) calendar disables booked / blocked dates
   2) chatbot -> LIVE CHAT with the admin (Live Agent)
   3) Delete Account really deletes the account on the server
   Load it AFTER the main script of home.html (apply_patch.py does this for you). */
(function () {
    const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

    // ---------- 1. Calendar ----------
    document.addEventListener('DOMContentLoaded', async () => {
        const ciEl = document.getElementById('checkInDate'), coEl = document.getElementById('checkOutDate');
        if (!ciEl || !coEl) return;
        await UDB.sync();
        const ci = ciEl._flatpickr, co = coEl._flatpickr;
        if (!ci || !co) return;

        ci.set('disable', [d => UDB.isTaken(iso(d))]);
        ci.config.onChange.push((sel, str) => {
            if (!str) return;
            const next = new Date(sel[0]); next.setDate(next.getDate() + 1);
            let limit = null; const p = new Date(next);
            for (let i = 0; i < 400; i++) {                       // check-out can't pass the next booked night
                if (UDB.isTaken(iso(p))) { limit = new Date(p); break; }
                p.setDate(p.getDate() + 1);
            }
            co.set('maxDate', limit);
            const cur = coEl.value;
            if (cur && limit && cur > iso(limit)) {
                co.clear();
                document.getElementById('feeDisplay').innerText = '₱1,000.00';
            }
        });
        setInterval(async () => { await UDB.sync(); ci.redraw(); co.redraw(); }, 60000);   // pick up new bookings
    });

    // ---------- 2. Live chat ----------
    const TERMS = '<b>Staycation Terms & Conditions:</b><br>' +
        '1. <b>Reservation Fee:</b> A non-refundable reservation fee of ₱1,000 is required to lock in your dates (this will be <b>deducted from your total full payment</b>).<br>' +
        '2. <b>Arrival Time:</b> Please arrive at least <b>30 minutes before your booked time</b>.<br>' +
        '3. <b>Check-in & Payments:</b> Upon arrival, guests must sign the staycation contract, settle the remaining balance of the full payment, and pay a <b>₱1,000 security deposit</b>.<br>' +
        '4. <b>Refundable Deposit:</b> The ₱1,000 security deposit is fully refundable upon check-out if there are no damages or missing items.<br>' +
        '5. <b>No Smoking & Pets:</b> Strictly NO SMOKING and NO PETS allowed inside the suite.<br>' +
        '6. <b>Valid ID:</b> All guests must present a government ID upon check-in.';
    const PAYMENT = 'Your ₱1,000 reservation fee will be <b>deducted from your total full payment</b> upon check-in. You will only pay the remaining balance along with the ₱1,000 refundable security deposit.';

    let lastId = 0, firstLoad = true, liveMode = false;
    const getUser = () => { try { return JSON.parse(localStorage.getItem('currentUser')); } catch (e) { return null; } };
    const loggedIn = () => { const u = getUser(); return !!(u && u.isLoggedIn && u.token); };
    const chatOpen = () => { const b = document.getElementById('chatBox'); return !!b && b.style.display === 'flex'; };
    const setDot = unread => { const d = document.querySelector('.chat-fab-dot'); if (d) d.style.background = unread ? '#ef4444' : '#22c55e'; };

    const baseToggle = window.toggleChat;
    window.toggleChat = function () { baseToggle(); if (chatOpen()) setDot(false); };

    async function postChat(text) {
        try { const r = await UDB.authFetch('/api/chat/send', 'POST', { message: text }); return r.ok; }
        catch (e) { return false; }
    }

    async function poll() {
        if (!loggedIn() || document.hidden) return;
        try {
            const r = await UDB.authFetch('/api/chat/messages?after=' + lastId);
            if (!r.ok) return;
            let newAdmin = false;
            r.data.forEach(m => {
                lastId = Math.max(lastId, m.id);
                if (firstLoad) appendMessage(m.sender === 'admin' ? 'bot' : 'user', (m.sender === 'admin' ? '<b>Admin:</b> ' : '') + esc(m.text));
                else if (m.sender === 'admin') { appendMessage('bot', '<b>Admin:</b> ' + esc(m.text)); newAdmin = true; }
            });
            if (firstLoad && r.data.length) liveMode = true;
            firstLoad = false;
            if (newAdmin) { liveMode = true; if (!chatOpen()) setDot(true); }
        } catch (e) { /* offline or session expired: try again on the next tick */ }
    }

    window.connectLiveAgent = async function () {
        appendMessage('user', '👤 I want to speak with a Live Agent / Admin.');
        liveMode = true;
        const ok = await postChat('I want to speak with a Live Agent / Admin.');
        setTimeout(() => appendMessage('bot', ok
            ? 'The Admin (Owner) has been notified. Please wait a moment. Replies will appear right here.'
            : 'Sorry, we cannot reach the server right now. Please try again in a moment.'), 400);
    };

    window.sendMessage = async function () {
        const input = document.getElementById('chatInput');
        const text = input.value.trim();
        if (!text) return;
        appendMessage('user', esc(text));
        input.value = '';

        const lower = text.toLowerCase();
        let reply = null;
        if (!liveMode) {                                         // the bot answers common questions first
            if (lower.includes('parking') || lower.includes('park')) reply = 'Yes, we do have parking available for our guests!';
            else if (['term', 'condition', 'policy', 'rule', 'contract', 'deposit'].some(k => lower.includes(k))) reply = TERMS;
            else if (['payment', 'balance', 'deduct'].some(k => lower.includes(k))) reply = PAYMENT;
        }
        if (reply) { setTimeout(() => appendMessage('bot', reply), 500); return; }

        const first = !liveMode;
        liveMode = true;
        const ok = await postChat(text);
        if (!ok) setTimeout(() => appendMessage('bot', 'Sorry, we cannot reach the server right now. Please try again in a moment.'), 500);
        else if (first) setTimeout(() => appendMessage('bot', 'Thank you for your message. I have forwarded it to our Live Agent (Admin). Their reply will appear here.'), 500);
    };

    document.addEventListener('DOMContentLoaded', () => {
        const u = getUser();
        if (u && u.isLoggedIn && !u.token) {                     // old session from before the update: sign in again
            localStorage.removeItem('currentUser');
            location.reload();
            return;
        }
        if (loggedIn()) { poll(); setInterval(poll, 4000); }
    });

    // ---------- 3. Delete account (really deletes it on the server) ----------
    window.confirmDeleteAccount = async function () {
        const registered = (document.getElementById('modalUserEmail').innerText || '').trim();
        const typed = await UI.prompt('To confirm deletion, please re-type your registered email address (' + registered + ').',
            { title: 'Delete Account', okText: 'Delete', danger: true, placeholder: registered });
        if (typed === null) return;
        if (typed.trim().toLowerCase() !== registered.toLowerCase()) {
            await UI.alert('Incorrect email address! Account deletion cancelled.', { title: 'Cancelled' });
            return;
        }
        try {
            const r = await UDB.authFetch('/api/auth/delete', 'POST');
            if (!r.ok) throw new Error(r.data.message || 'Could not delete the account.');
        } catch (e) {
            await UI.alert(e.message, { title: 'Error' });
            return;
        }
        ['currentUser', 'userEmail', 'userName', 'isLoggedIn'].forEach(k => localStorage.removeItem(k));
        await UI.alert('Your account has been successfully deleted.', { title: 'Account Deleted' });
        location.href = 'home.html';
    };
})();