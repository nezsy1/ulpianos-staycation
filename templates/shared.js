/* shared.js - talks to the Flask server (app.py). Used by home.html and index.html */
const UDB = (() => {
    const RATE = 2500, EXTRA = 500, FEE = 1000;           // keep in sync with app.py
    // On Render (or when opened from Flask on port 5000) use relative URLs.
    // Only when the page is opened from a file or another local port (Live Server) call Flask directly.
    const host = location.hostname;
    const devOther = location.protocol === 'file:' || ((host === 'localhost' || host === '127.0.0.1') && location.port !== '5000');
    const API = devOther ? 'http://127.0.0.1:5000' : '';
    let avail = { ranges: [], blocked: [] };

    const parse = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
    const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    const token = () => { try { return (JSON.parse(localStorage.getItem('currentUser')) || {}).token || ''; } catch (e) { return ''; } };

    return {
        API,

        // Request with the signed-in guest's token. Sends the guest back to login if the session expired.
        async authFetch(path, method = 'GET', body) {
            const r = await fetch(API + path, {
                method,
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
                body: body ? JSON.stringify(body) : undefined
            });
            let data = {};
            try { data = await r.json(); } catch (e) {}
            if (r.status === 401 && data.auth) {
                localStorage.removeItem('currentUser');
                location.href = 'login.html';
                throw new Error(data.message || 'Please sign in again.');
            }
            return { ok: r.ok, status: r.status, data };
        },

        // Load booked / blocked dates from the server
        async sync() {
            try {
                const r = await fetch(API + '/api/availability', { cache: 'no-store' });
                if (r.ok) avail = await r.json();
            } catch (e) { console.warn('Could not load availability', e); }
        },

        // Is this single night already taken? (for disabling dates in the calendar)
        isTaken(dateStr) {
            if (avail.blocked.includes(dateStr)) return true;
            return avail.ranges.some(r => dateStr >= r.check_in && dateStr < r.check_out);
        },

        // Are ALL nights between check-in and check-out free?
        rangeFree(ci, co) {
            if (!ci || !co || co <= ci) return false;
            for (let d = parse(ci), end = parse(co); d < end; d.setDate(d.getDate() + 1)) {
                if (this.isTaken(iso(d))) return false;
            }
            return true;
        },

        nights(ci, co) { return Math.round((parse(co) - parse(ci)) / 86400000); },

        price(nights, pax) {
            const total = (RATE + Math.max(0, pax - 2) * EXTRA) * nights;
            const fee = FEE * nights;
            return { nights, total, fee, balance: Math.max(0, total - fee) };
        },

        fmtRange(ci, co) {
            const a = parse(ci), b = parse(co), f = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            return f(a) + ' - ' + f(b) + ', ' + b.getFullYear();
        },

        peso(n) { return '₱' + Number(n || 0).toLocaleString('en-US'); },

        // Shrink a photo so it is small enough to save (max 1000px, JPEG)
        compress(file, maxW = 1000, quality = 0.72) {
            return new Promise((resolve, reject) => {
                const fr = new FileReader();
                fr.onerror = () => reject(new Error('Could not read the image.'));
                fr.onload = () => {
                    const img = new Image();
                    img.onerror = () => reject(new Error('Invalid image file.'));
                    img.onload = () => {
                        const scale = Math.min(1, maxW / img.width);
                        const c = document.createElement('canvas');
                        c.width = Math.round(img.width * scale);
                        c.height = Math.round(img.height * scale);
                        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
                        resolve(c.toDataURL('image/jpeg', quality));
                    };
                    img.src = fr.result;
                };
                fr.readAsDataURL(file);
            });
        },

        // Save the reservation on the server (name + email always come from the signed-in account)
        async createBooking(payload) {
            const r = await this.authFetch('/api/bookings', 'POST', payload);
            if (!r.ok) throw new Error(r.data.message || 'Could not save your reservation. Please try again.');
            return r.data;      // { success, bookingRef }
        }
    };
})();