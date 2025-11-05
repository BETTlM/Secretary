# firebase_helpers.py
import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime, timezone

# --- INITIALIZATION ---
# This automatically finds 'serviceAccountKey.json' in the same folder
try:
    # Check if the app is already initialized (prevents crash on reload)
    if not firebase_admin._apps:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"FATAL: Could not initialize Firebase Admin. {e}")
    # This will crash the app, which is good. It can't run without Firebase.

db = firestore.client()

# --- AUTH & PROFILE FUNCTIONS ---

def verify_session_cookie(session_cookie):
    """Verifies a Flask session cookie and returns the user's decoded token."""
    try:
        # This checks if the cookie is valid
        decoded_token = auth.verify_session_cookie(session_cookie, check_revoked=True)
        return decoded_token
    except Exception as e:
        print(f"Error verifying session cookie: {e}")
        return None

def create_profile_if_not_exists(user_id, email):
    """Creates a user profile in Firestore when they sign up."""
    profile_ref = db.collection('user_profiles').document(user_id)
    if not profile_ref.get().exists:
        profile_ref.set({
            'id': user_id, # Store the ID in the doc as well
            'email': email,
            'phone_number': None,
            'sync_notion': True,
            'sync_calendar': True,
            'notion_api_key': None,
            'notion_database_id': None,
            'google_refresh_token': None
        })
        print(f"Created new profile for user {user_id}")

    # Return the profile data
    return profile_ref.get().to_dict()

def get_profile_by_user_id(user_id):
    """Finds a user profile by their auth ID for the website."""
    try:
        doc = db.collection('user_profiles').document(user_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error getting profile by ID: {e}")
        return None

def get_user_by_phone(phone_number: str):
    """Finds a user profile by their phone number for the bot."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        # Firestore requires us to query for the field
        users_ref = db.collection('user_profiles').where('phone_number', '==', cleaned_phone).limit(1).stream()

        for doc in users_ref:
            # Return the first match
            return doc.to_dict()
        return None # No user found
    except Exception as e:
        print(f"Error getting user by phone: {e}")
        return None

def save_phone_number(user_id: str, phone_number: str):
    """Updates a user's profile with their phone number."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        db.collection('user_profiles').document(user_id).update({
            "phone_number": cleaned_phone
        })
    except Exception as e:
        print(f"Error saving phone number: {e}")

def save_user_notion_details(user_id: str, api_key: str, db_id: str):
    """Updates a user's Notion credentials."""
    try:
        db.collection('user_profiles').document(user_id).update({
            "notion_api_key": api_key,
            "notion_database_id": db_id
        })
    except Exception as e:
        print(f"Error saving Notion details: {e}")

def save_user_google_token(user_id: str, refresh_token: str):
    """Saves the Google Calendar Refresh Token."""
    try:
        db.collection('user_profiles').document(user_id).update({
            "google_refresh_token": refresh_token
        })
    except Exception as e:
        print(f"Error saving Google token: {e}")

# --- SCHEDULER FUNCTIONS ---

def add_scheduled_event(user_id: str, phone_number: str, title: str, deadline_utc: datetime, reminder_time_utc: datetime):
    """Adds a new event to the scheduler collection."""
    try:
        # We use the user_id from Firebase Auth as the 'user_id'
        doc_ref = db.collection('scheduled_events').document()
        doc_ref.set({
            "user_id": user_id,
            "phone_number": phone_number,
            "event_title": title,
            "event_deadline_utc": deadline_utc, # Firestore handles datetime objects
            "reminder_time_utc": reminder_time_utc,
            "reminder_sent": False
        })
    except Exception as e:
        print(f"Error adding scheduled event: {e}")

def get_pending_reminders(now_utc: datetime):
    """Fetches all reminders that are due to be sent."""
    try:
        reminders_query = db.collection('scheduled_events') \
                            .where('reminder_sent', '==', False) \
                            .where('reminder_time_utc', '<=', now_utc) \
                            .stream()

        pending_reminders = []
        for doc in reminders_query:
            data = doc.to_dict()
            data['id'] = doc.id # Add the document ID for updating
            pending_reminders.append(data)
        return pending_reminders
    except Exception as e:
        print(f"Error fetching pending reminders: {e}")
        return []

def mark_reminder_as_sent(event_id: str):
    """Marks a reminder as sent so it doesn't send again."""
    try:
        db.collection('scheduled_events').document(event_id).update({
            "reminder_sent": True
        })
    except Exception as e:
        print(f"Error marking reminder as sent: {e}")