import os
import time
import html
import json
import smtplib
import threading
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta
from functools import wraps
from email.message import EmailMessage

# Philippine time on Render (also set TZ=Asia/Manila in the Render environment)
os.environ.setdefault('TZ', 'Asia/Manila')
if hasattr(time, 'tzset'):
    time.tzset()

from flask import Flask, request, jsonify, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash, safe_join

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
CORS(app)

# Render gives DATABASE_URL (PostgreSQL). Locally it falls back to SQLite.
db_url = os.environ.get('DATABASE_URL', 'sqlite:///staycation.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024          # photos are sent as base64
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key')
db = SQLAlchemy(app)
signer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# ---------------- PRICING (edit here) ----------------
RATE_PER_NIGHT = 2500      # good for 2 pax, per 22-hour stay
EXTRA_PER_HEAD = 500       # per extra guest beyond 2, per night
FEE_PER_NIGHT = 1000       # reservation fee, per night (deducted from total)
SECURITY_DEPOSIT = 1000    # refundable


def price(nights, pax):
    per_night = RATE_PER_NIGHT + max(0, pax - 2) * EXTRA_PER_HEAD
    total = per_night * nights
    fee = FEE_PER_NIGHT * nights
    return total, fee


# ---------------- MODELS ----------------
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)


class User(db.Model):                      # website login accounts
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Guest(db.Model):                     # ONE row per real person (repeat customers share it)
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(40))
    id_image = db.Column(db.Text)
    selfie_image = db.Column(db.Text)
    bookings = db.relationship('Booking', backref='guest', lazy=True)


class Booking(db.Model):                   # MANY rows per guest
    id = db.Column(db.Integer, primary_key=True)
    booking_ref = db.Column(db.String(20), unique=True)
    guest_id = db.Column(db.Integer, db.ForeignKey('guest.id'), nullable=False)
    pax = db.Column(db.Integer, nullable=False, default=2)
    check_in = db.Column(db.String(10), nullable=False)
    check_out = db.Column(db.String(10), nullable=False)
    nights = db.Column(db.Integer, nullable=False, default=1)
    total = db.Column(db.Integer, nullable=False)
    reservation_fee = db.Column(db.Integer, nullable=False)
    deposit = db.Column(db.Integer, nullable=False, default=SECURITY_DEPOSIT)
    status = db.Column(db.String(20), default='Pending')      # Pending, Reserved, Completed, Cancelled
    balance_paid = db.Column(db.Boolean, default=False)
    deposit_status = db.Column(db.String(20), default='Unpaid')
    damage_fee = db.Column(db.Integer, default=0)
    damage_note = db.Column(db.String(200), default='')
    remarks = db.Column(db.String(300), default='')
    payment_method = db.Column(db.String(50))
    id_image = db.Column(db.Text)
    selfie_image = db.Column(db.Text)
    payment_image = db.Column(db.Text)
    pass_no = db.Column(db.String(40))
    pass_sent_at = db.Column(db.DateTime)
    pass_sent_to = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.now)


class BlockedDate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), unique=True, nullable=False)
    reason = db.Column(db.String(200), nullable=True)


class ChatMessage(db.Model):               # old table (kept so existing databases don't break)
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(50), nullable=False)
    guest_name = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(100), nullable=True, default='default_session')
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMsg(db.Model):                   # NEW: live chat (guest <-> admin)
    __tablename__ = 'chat_msg'
    id = db.Column(db.Integer, primary_key=True)
    session = db.Column(db.String(120), nullable=False, index=True)   # = guest email
    guest_name = db.Column(db.String(100), nullable=False)
    sender = db.Column(db.String(10), nullable=False)                 # 'guest' | 'admin'
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    admin_read = db.Column(db.Boolean, default=False)                 # guest message read by admin
    seen_at = db.Column(db.DateTime)                                  # admin message seen by guest


class ChatPresence(db.Model):              # NEW: shows "Online" for the guest in the admin chat
    __tablename__ = 'chat_presence'
    session = db.Column(db.String(120), primary_key=True)
    last_seen = db.Column(db.DateTime)


with app.app_context():
    db.create_all()
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'password123')
    if not Admin.query.filter_by(username=admin_user).first():
        db.session.add(Admin(username=admin_user, password=generate_password_hash(admin_pass)))
        db.session.commit()


# ---------------- HELPERS ----------------
def pdate(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def admin_pw_ok(admin, pw):
    stored = admin.password or ''
    if stored.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored, pw)
    if stored == pw:                                   # old plain-text password: upgrade it
        admin.password = generate_password_hash(pw)
        db.session.commit()
        return True
    return False


def _token():
    return (request.headers.get('Authorization') or '').replace('Bearer ', '', 1)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            signer.loads(_token(), max_age=60 * 60 * 12, salt='admin')
        except (BadSignature, SignatureExpired):
            return jsonify({'success': False, 'message': 'Please log in again.'}), 401
        return fn(*a, **kw)
    return wrapper


def user_required(fn):
    """Guest must be signed in (registered email). The user is passed to the route."""
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            data = signer.loads(_token(), max_age=60 * 60 * 24 * 14, salt='user')
        except (BadSignature, SignatureExpired):
            return jsonify({'success': False, 'auth': True, 'message': 'Please sign in again.'}), 401
        user = db.session.get(User, data.get('id'))
        if not user:
            return jsonify({'success': False, 'auth': True, 'message': 'Please sign in again.'}), 401
        return fn(user, *a, **kw)
    return wrapper


def range_free(ci, co, exclude_id=None):
    """Nights occupied = check_in up to (not including) check_out."""
    for b in Booking.query.filter(Booking.status != 'Cancelled').all():
        if exclude_id and b.id == exclude_id:
            continue
        if ci < pdate(b.check_out) and co > pdate(b.check_in):
            return False
    for bd in BlockedDate.query.all():
        try:
            if ci <= pdate(bd.date) < co:
                return False
        except ValueError:
            pass
    return True


def booking_dict(b):
    g = b.guest
    return {
        'id': b.id, 'bookingRef': b.booking_ref,
        'bookedAt': b.created_at.strftime('%Y-%m-%d'), 'bookedTs': ms(b.created_at),
        'guestId': 'GST-%04d' % g.id, 'name': g.full_name, 'contact': g.contact or '', 'email': g.email,
        'checkIn': b.check_in, 'checkOut': b.check_out, 'nights': b.nights, 'pax': b.pax,
        'status': b.status, 'total': b.total, 'reservationFee': b.reservation_fee, 'deposit': b.deposit,
        'balancePaid': bool(b.balance_paid), 'depositStatus': b.deposit_status,
        'damageFee': b.damage_fee or 0, 'damageNote': b.damage_note or '', 'remarks': b.remarks or '',
        'paymentMethod': b.payment_method,
        'passNo': b.pass_no, 'passSentAt': ms(b.pass_sent_at), 'passSentTo': b.pass_sent_to,
    }


# ---------------- EMAIL ----------------
def send_mail(to, subject, html_body):
    """1) Brevo HTTPS API (works on Render FREE, where SMTP ports are blocked)
       2) SMTP fallback (works locally, or on a paid Render instance)"""
    brevo_key = os.environ.get('BREVO_API_KEY')
    if brevo_key:
        sender = os.environ.get('MAIL_FROM')
        if not sender:
            raise RuntimeError('Set MAIL_FROM to the sender email you verified in Brevo.')
        payload = json.dumps({
            'sender': {'name': "Ulpiano's Staycation", 'email': sender},
            'to': [{'email': to}], 'subject': subject, 'htmlContent': html_body,
        }).encode('utf-8')
        req = urllib.request.Request('https://api.brevo.com/v3/smtp/email', data=payload, method='POST',
                                     headers={'api-key': brevo_key, 'content-type': 'application/json', 'accept': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except urllib.error.HTTPError as err:
            raise RuntimeError('Brevo error %s: %s' % (err.code, err.read().decode('utf-8', 'ignore')[:200]))
        return

    user, pw = os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASS')
    if not user or not pw:
        raise RuntimeError('Email is not set up yet. Set BREVO_API_KEY + MAIL_FROM (recommended) or SMTP_USER + SMTP_PASS, then restart the server.')
    msg = EmailMessage()
    msg['Subject'], msg['To'] = subject, to
    msg['From'] = os.environ.get('MAIL_FROM', "Ulpiano's Staycation <%s>" % user)
    msg.set_content('Please view this email in an HTML-capable email app.')
    msg.add_alternative(html_body, subtype='html')
    with smtplib.SMTP(os.environ.get('SMTP_HOST', 'smtp.gmail.com'), int(os.environ.get('SMTP_PORT', 587)), timeout=20) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)


def notify_admin(subject, body):
    """Email the owner (ADMIN_NOTIFY_EMAIL) when nobody is watching the admin page."""
    to = os.environ.get('ADMIN_NOTIFY_EMAIL')
    if not to:
        return

    def run():
        try:
            send_mail(to, subject, '<p>%s</p>' % html.escape(body))
        except Exception as err:
            print('[notify_admin]', err)
    threading.Thread(target=run, daemon=True).start()


# ---------------- SERVE THE PAGES ----------------
SEARCH_DIRS = [BASE_DIR, os.path.join(BASE_DIR, 'templates'), os.path.join(BASE_DIR, 'static')]
ALLOWED_EXT = ('.html', '.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico')


def serve_frontend(filename):
    if not filename.lower().endswith(ALLOWED_EXT):
        abort(404)
    for d in SEARCH_DIRS:
        full = safe_join(d, filename)
        if full and os.path.isfile(full):
            return send_from_directory(d, filename)
    abort(404)


@app.route('/')
def home():
    return serve_frontend('home.html')


@app.route('/admin')
def admin_page():
    return serve_frontend('admin.html')


@app.route('/healthz')
def healthz():
    return 'ok'


# ---------------- WEBSITE ACCOUNTS ----------------
@app.route('/api/auth/signup', methods=['POST'])
def user_signup():
    data = request.get_json() or {}
    name = ' '.join((data.get('full_name') or '').split())
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if len(name) < 2 or not email or not password:
        return jsonify({'success': False, 'message': 'Please complete all fields.'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'This email is already registered. Please sign in.'}), 409
    db.session.add(User(full_name=name, email=email, password_hash=generate_password_hash(password)))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Account created.'}), 201


@app.route('/api/auth/login', methods=['POST'])
def user_login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'success': False, 'message': 'This email is not registered. Please sign up first.'}), 401
    if not check_password_hash(user.password_hash, data.get('password') or ''):
        return jsonify({'success': False, 'message': 'Incorrect password.'}), 401
    token = signer.dumps({'id': user.id}, salt='user')
    return jsonify({'success': True, 'token': token, 'user': {'name': user.full_name, 'email': user.email}}), 200


@app.route('/api/auth/delete', methods=['POST'])
@user_required
def user_delete(user):
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})


# ---------------- PUBLIC BOOKING API (used by home.html / index.html) ----------------
@app.route('/api/availability')
def availability():
    today = date.today()
    ranges = [{'check_in': b.check_in, 'check_out': b.check_out}
              for b in Booking.query.filter(Booking.status != 'Cancelled').all()
              if pdate(b.check_out) >= today]
    return jsonify({'ranges': ranges, 'blocked': [b.date for b in BlockedDate.query.all()]})


@app.route('/api/bookings', methods=['POST'])
@user_required
def create_booking(user):
    d = request.get_json() or {}
    name = user.full_name            # always the account name (must match the valid ID)
    email = user.email               # always the registered email
    contact = (d.get('contact') or '').strip()
    try:
        pax = int(d.get('pax'))
        ci, co = pdate(d.get('checkIn')), pdate(d.get('checkOut'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid booking details.'}), 400
    if not contact:
        return jsonify({'success': False, 'message': 'Please enter your contact number.'}), 400
    if not 1 <= pax <= 4:
        return jsonify({'success': False, 'message': 'Pax must be between 1 and 4.'}), 400
    nights = (co - ci).days
    if nights < 1 or ci < date.today():
        return jsonify({'success': False, 'message': 'Invalid dates.'}), 400
    if not range_free(ci, co):
        return jsonify({'success': False, 'message': 'Sorry, those dates were just taken.'}), 409

    guest = Guest.query.filter_by(email=email).first()           # repeat customer? reuse the same guest
    if not guest:
        guest = Guest(email=email, full_name=name)
        db.session.add(guest)
    guest.full_name, guest.contact = name, contact
    guest.id_image, guest.selfie_image = d.get('idImage'), d.get('selfieImage')
    db.session.flush()

    total, fee = price(nights, pax)
    b = Booking(guest_id=guest.id, pax=pax, check_in=ci.isoformat(), check_out=co.isoformat(), nights=nights,
                total=total, reservation_fee=fee, payment_method=d.get('paymentMethod'),
                id_image=d.get('idImage'), selfie_image=d.get('selfieImage'), payment_image=d.get('paymentImage'))
    db.session.add(b)
    db.session.flush()
    b.booking_ref = 'BK-%04d' % b.id
    db.session.commit()
    notify_admin('New reservation %s' % b.booking_ref,
                 '%s booked %s to %s (%d pax). Open the admin page to review it.' % (name, b.check_in, b.check_out, pax))
    return jsonify({'success': True, 'bookingRef': b.booking_ref}), 201


# ---------------- LIVE CHAT: GUEST SIDE ----------------
def touch_presence(session_id):
    p = db.session.get(ChatPresence, session_id)
    if p:
        p.last_seen = datetime.now()
    else:
        db.session.add(ChatPresence(session=session_id, last_seen=datetime.now()))


@app.route('/api/chat/send', methods=['POST'])
@user_required
def chat_send(user):
    text = ((request.get_json() or {}).get('message') or '').strip()[:1000]
    if not text:
        return jsonify({'success': False, 'message': 'Empty message.'}), 400
    last = ChatMsg.query.filter_by(session=user.email).order_by(ChatMsg.id.desc()).first()
    new_conversation = (not last) or (datetime.now() - last.created_at > timedelta(minutes=10))
    db.session.add(ChatMsg(session=user.email, guest_name=user.full_name, sender='guest', text=text))
    touch_presence(user.email)
    db.session.commit()
    if new_conversation:
        notify_admin('New chat message from %s' % user.full_name, text)
    return jsonify({'success': True})


@app.route('/api/chat/messages')
@user_required
def chat_messages(user):
    after = request.args.get('after', 0, type=int)
    touch_presence(user.email)
    rows = (ChatMsg.query.filter(ChatMsg.session == user.email, ChatMsg.id > after)
            .order_by(ChatMsg.id.asc()).all())
    now = datetime.now()
    for m in rows:
        if m.sender == 'admin' and not m.seen_at:
            m.seen_at = now
    db.session.commit()
    return jsonify([{'id': m.id, 'sender': m.sender, 'text': m.text, 'ts': ms(m.created_at)} for m in rows])


# ---------------- LIVE CHAT: ADMIN SIDE ----------------
@app.route('/api/admin/chats')
@admin_required
def admin_chats():
    rows = ChatMsg.query.order_by(ChatMsg.id.desc()).limit(2000).all()
    rows.reverse()
    now = datetime.now()
    online = {p.session: p.last_seen for p in ChatPresence.query.all()}
    chats = {}
    for m in rows:
        c = chats.setdefault(m.session, {
            'id': m.session, 'name': m.guest_name, 'messages': [],
            'online': bool(online.get(m.session) and (now - online[m.session]).total_seconds() < 30),
        })
        if m.sender == 'guest':
            c['name'] = m.guest_name
        c['messages'].append({
            'from': m.sender, 'text': m.text, 'ts': ms(m.created_at),
            'read': True if m.sender == 'admin' else bool(m.admin_read),
            'seen': bool(m.seen_at), 'seenAt': ms(m.seen_at),
        })
    return jsonify(list(chats.values()))


@app.route('/api/admin/chats/<sid>/read', methods=['POST'])
@admin_required
def admin_chat_read(sid):
    ChatMsg.query.filter_by(session=sid, sender='guest', admin_read=False).update({'admin_read': True})
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/chats/<sid>/reply', methods=['POST'])
@admin_required
def admin_chat_reply(sid):
    text = ((request.get_json() or {}).get('text') or '').strip()[:1000]
    if not text:
        return jsonify({'success': False, 'message': 'Empty message.'}), 400
    g = ChatMsg.query.filter_by(session=sid, sender='guest').order_by(ChatMsg.id.desc()).first()
    if not g:
        return jsonify({'success': False, 'message': 'Conversation not found.'}), 404
    db.session.add(ChatMsg(session=sid, guest_name=g.guest_name, sender='admin', text=text, admin_read=True))
    ChatMsg.query.filter_by(session=sid, sender='guest', admin_read=False).update({'admin_read': True})
    db.session.commit()
    return jsonify({'success': True})


# ---------------- ADMIN API ----------------
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    d = request.get_json() or {}
    admin = Admin.query.filter_by(username=(d.get('username') or '').strip()).first()
    if admin and admin_pw_ok(admin, d.get('password') or ''):
        return jsonify({'success': True, 'token': signer.dumps({'u': admin.username}, salt='admin')})
    return jsonify({'success': False, 'message': 'Invalid username or password.'}), 401


@app.route('/api/admin/verify-password', methods=['POST'])
@admin_required
def verify_password():
    admin = Admin.query.first()
    ok = bool(admin and admin_pw_ok(admin, (request.get_json() or {}).get('password') or ''))
    return jsonify({'success': ok}), (200 if ok else 403)


@app.route('/api/admin/bookings')
@admin_required
def admin_bookings():
    rows = Booking.query.order_by(Booking.id.desc()).all()
    return jsonify([booking_dict(b) for b in rows])


@app.route('/api/admin/bookings/<int:bid>/docs')
@admin_required
def admin_docs(bid):
    b = Booking.query.get_or_404(bid)
    return jsonify({'idImage': b.id_image or b.guest.id_image or '', 'selfieImage': b.selfie_image or b.guest.selfie_image or '',
                    'paymentImage': b.payment_image or ''})


@app.route('/api/admin/bookings/<int:bid>', methods=['PATCH'])
@admin_required
def admin_update(bid):
    b = Booking.query.get_or_404(bid)
    d = request.get_json() or {}
    if b.status in ('Completed', 'Cancelled'):
        return jsonify({'success': False, 'message': 'Completed or cancelled bookings can no longer be edited.'}), 400
    if 'status' in d:
        if d['status'] not in ('Pending', 'Reserved', 'Completed', 'Cancelled'):
            return jsonify({'success': False, 'message': 'Invalid status.'}), 400
        b.status = d['status']
        if b.status == 'Completed':
            b.balance_paid = True
    if 'remarks' in d:
        b.remarks = str(d['remarks'])[:300]
    if 'damageFee' in d:
        try:
            fee = int(float(d['damageFee']))
        except (TypeError, ValueError):
            fee = -1
        if fee < 0:
            return jsonify({'success': False, 'message': 'Invalid damage fee.'}), 400
        b.damage_fee = fee
        b.damage_note = str(d.get('damageNote', ''))[:200] if fee > 0 else ''
    if 'balancePaid' in d:
        b.balance_paid = bool(d['balancePaid'])
    if 'depositStatus' in d and d['depositStatus'] in ('Unpaid', 'Held', 'Refunded'):
        b.deposit_status = d['depositStatus']
    db.session.commit()
    return jsonify(booking_dict(b))


@app.route('/api/admin/bookings/<int:bid>/pass', methods=['POST'])
@admin_required
def admin_pass(bid):
    b = Booking.query.get_or_404(bid)
    if b.status != 'Reserved':
        return jsonify({'success': False, 'message': 'Only Reserved bookings can get a lobby pass.'}), 400
    if not b.pass_no:
        b.pass_no = 'LC-%s-%s' % (b.booking_ref.replace('BK-', ''), b.check_in.replace('-', ''))
        db.session.commit()
    return jsonify(booking_dict(b))


def build_email_html(b, terms):
    e = html.escape
    rows = [('Booking Ref', b.booking_ref), ('Stay', '%s to %s (%d night%s)' % (b.check_in, b.check_out, b.nights, '' if b.nights == 1 else 's')),
            ('Number of Pax', b.pax), ('Total Payment', 'PHP {:,}'.format(b.total)),
            ('Reservation Fee', 'PHP {:,}'.format(b.reservation_fee)),
            ('Balance upon check-in', 'PHP {:,}'.format(max(0, b.total - b.reservation_fee))),
            ('Security Deposit', 'PHP {:,} (refundable)'.format(b.deposit))]
    tr = ''.join('<tr><td style="padding:5px 0;color:#6b7280">%s</td><td style="padding:5px 0;text-align:right;font-weight:600">%s</td></tr>' % (e(str(k)), e(str(v))) for k, v in rows)
    lis = ''.join('<li style="margin-bottom:4px">%s</li>' % e(str(t)) for t in terms)
    return ('<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;max-width:560px">'
            '<p>Hi <b>%s</b>,</p><p>Thank you for booking with <b>Ulpiano\'s Staycation</b>. Your reservation is <b>confirmed</b>. '
            'Below are your booking details, lobby clearance pass, and our terms and conditions.</p>'
            '<h4 style="margin:18px 0 4px;color:#6b7280;letter-spacing:1px">BOOKING CONFIRMATION</h4><table style="width:100%%;border-collapse:collapse">%s</table>'
            '<h4 style="margin:18px 0 4px;color:#6b7280;letter-spacing:1px">LOBBY CLEARANCE PASS</h4>'
            '<div style="border:2px solid #1f2937;border-radius:10px;padding:16px;text-align:center">'
            '<b>ALPINA HEIGHTS CONDOMINIUM PROPERTY MANAGEMENT OFFICE (PMO)</b><br>'
            '<small style="color:#6b7280">Paranaque City, Metro Manila - Near SM Bicutan - Official Lobby Clearance</small>'
            '<p style="margin:12px 0 2px">Pass No.: <b>%s</b></p><p style="margin:2px 0">Guest: <b>%s</b></p><p style="margin:2px 0">Stay: <b>%s to %s</b></p>'
            '<small style="color:#6b7280">Please present this pass at the lobby.</small></div>'
            '<h4 style="margin:18px 0 4px;color:#6b7280;letter-spacing:1px">TERMS AND CONDITIONS</h4><ol style="padding-left:18px">%s</ol>'
            '<p>By checking in, you agree to the terms above. See you soon!</p><p>Warm regards,<br><b>Ulpiano\'s Staycation</b></p></div>'
            ) % (e(b.guest.full_name), tr, e(b.pass_no or ''), e(b.guest.full_name), e(b.check_in), e(b.check_out), lis)


@app.route('/api/admin/bookings/<int:bid>/send-pass', methods=['POST'])
@admin_required
def admin_send_pass(bid):
    b = Booking.query.get_or_404(bid)
    d = request.get_json() or {}
    to = (d.get('to') or '').strip()
    if not b.pass_no:
        return jsonify({'success': False, 'message': 'Generate the pass first.'}), 400
    if '@' not in to:
        return jsonify({'success': False, 'message': 'Enter a valid email address.'}), 400
    try:
        send_mail(to, d.get('subject') or 'Booking Confirmation & Lobby Pass', build_email_html(b, d.get('terms') or []))
    except RuntimeError as err:
        return jsonify({'success': False, 'message': str(err)}), 503
    except Exception as err:
        return jsonify({'success': False, 'message': 'Could not send the email: %s' % err}), 502
    b.pass_sent_at, b.pass_sent_to = datetime.now(), to
    db.session.commit()
    return jsonify(booking_dict(b))


@app.route('/api/admin/blocked-dates', methods=['GET', 'POST'])
@admin_required
def manage_blocked_dates():
    if request.method == 'GET':
        return jsonify([{'id': x.id, 'date': x.date, 'reason': x.reason} for x in BlockedDate.query.all()])
    d = request.get_json() or {}
    if not d.get('date'):
        return jsonify({'success': False, 'message': 'Date is required.'}), 400
    db.session.add(BlockedDate(date=d['date'], reason=d.get('reason', 'Maintenance')))
    db.session.commit()
    return jsonify({'success': True}), 201


@app.route('/api/admin/blocked-dates/<date_str>', methods=['DELETE'])
@admin_required
def delete_blocked_date(date_str):
    x = BlockedDate.query.filter_by(date=date_str).first()
    if not x:
        return jsonify({'success': False, 'message': 'Not found.'}), 404
    db.session.delete(x)
    db.session.commit()
    return jsonify({'success': True})


# Any other file (home.html, index.html, login.html, success.html, shared.js, images...)
@app.route('/<path:filename>')
def frontend_files(filename):
    return serve_frontend(filename)


if __name__ == '__main__':
    app.run(debug=True)