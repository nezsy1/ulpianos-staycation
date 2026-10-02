import requests
import random

BASE_URL = "http://127.0.0.1:5000/api"
rand = random.randint(1000, 9999)

print("1. Register Owner & Create Unit...")
owner = requests.post(f"{BASE_URL}/users/register", json={
    "full_name": f"Juan Owner {rand}",
    "email": f"owner{rand}@gmail.com",
    "role": "Owner"
}).json()

unit = requests.post(f"{BASE_URL}/units", json={
    "unit_number": f"UNIT-{rand}",
    "owner_id": owner['user_id'],
    "price_per_night": 2500.00
}).json()
unit_id = unit['unit_id']
print(f"-> Created Unit ID: {unit_id}")

print("\n2. Register Guest & Submit Booking...")
guest = requests.post(f"{BASE_URL}/users/register", json={
    "full_name": f"Maria Guest {rand}",
    "email": f"guest{rand}@gmail.com",
    "role": "Guest"
}).json()

booking = requests.post(f"{BASE_URL}/bookings", json={
    "guest_id": guest['user_id'],
    "unit_id": unit_id,
    "check_in": "2026-10-01",
    "check_out": "2026-10-03",
    "total_amount": 5000.00
}).json()
booking_id = booking['booking_id']
print(f"-> Booking Created! Booking ID: {booking_id}")

print("\n3. Submit Payment for Audit...")
payment = requests.post(f"{BASE_URL}/payments", json={
    "booking_id": booking_id,
    "amount_paid": 5000.00,
    "payment_method": "GCash",
    "reference_number": f"GCASH-{rand}"
}).json()
payment_id = payment['payment_id']
print(f"-> Payment Recorded! Payment ID: {payment_id}")

print("\n4. Admin Verification & Guest Clearance...")
audit = requests.put(f"{BASE_URL}/payments/audit/{payment_id}", json={
    "audit_status": "Verified"
}).json()
print("-> Audit Result:", audit)