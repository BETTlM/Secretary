import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime, timezone

# --- INITIALIZATION ---
try:
    if not firebase_admin._apps:
        # We're on the server, use the service key
        cred = credentials.Certificate('serviceAccountKey.json')
        print("Initializing Firebase Admin SDK from serviceAccountKey.json...")
        firebase_admin.initialize_app(cred)
    else:
        print("Firebase Admin SDK already initialized.")
except Exception as e:
    print(f"FATAL: Could not initialize Firebase Admin. {e}")
    # This will crash the app, which is what we want if we can't connect to the DB.

db = firestore.client()

#################################################
# SECTION 1: AUTH & PROFILE HELPERS
#################################################

def verify_session_cookie(session_cookie):
    """
    Verifies the Flask session cookie against Firebase Auth.
    Returns the decoded user token if valid, else None.
    """
    try:
        decoded_token = auth.verify_session_cookie(session_cookie, check_revoked=True)
        return decoded_token
    except auth.InvalidSessionCookieError:
        print("Invalid session cookie. Please log in again.")
        return None
    except Exception as e:
        print(f"Error verifying session cookie: {e}")
        return None

def create_profile_if_not_exists(user_id, email):
    """
    Creates a new user profile document in Firestore.
    This is called the first time a user signs up.
    """
    profile_ref = db.collection('user_profiles').document(user_id)
    profile_snapshot = profile_ref.get()
    
    if not profile_snapshot.exists:
        print(f"Creating new profile for user {user_id} with email {email}...")
        profile_data = {
            'id': user_id,
            'email': email,
            'phone_number': None,
            'created_at': firestore.SERVER_TIMESTAMP,
            'is_pro': False, # For future monetization
            'sync_notion': False,
            'sync_calendar': False,
            'notion_api_key': None,
            'notion_database_id': None,
            'google_refresh_token': None,
            'stats_total_synced': 0,
            'stats_reminders_sent': 0
        }
        profile_ref.set(profile_data)
        return profile_data
    
    print(f"Profile for {user_id} already exists.")
    return profile_snapshot.to_dict()

def get_profile_by_user_id(user_id):
    """Finds and returns a user profile document by their auth ID."""
    try:
        doc = db.collection('user_profiles').document(user_id).get()
        if doc.exists:
            return doc.to_dict()
        print(f"Profile not found for user {user_id}")
        return None
    except Exception as e:
        print(f"Error getting profile by ID {user_id}: {e}")
        return None

def get_user_by_phone(phone_number: str):
    """Finds a user profile by their WhatsApp phone number."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        users_ref = db.collection('user_profiles').where('phone_number', '==', cleaned_phone).limit(1).stream()
        
        for doc in users_ref:
            # Found the user
            return doc.to_dict()
        
        print(f"No user found for phone number {cleaned_phone}")
        return None
    except Exception as e:
        print(f"Error getting user by phone {phone_number}: {e}")
        return None

def save_phone_number(user_id: str, phone_number: str):
    """Updates a user's profile with their phone number."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        db.collection('user_profiles').document(user_id).update({
            "phone_number": cleaned_phone
        })
        print(f"Saved phone number for user {user_id}")
    except Exception as e:
        print(f"Error saving phone number for user {user_id}: {e}")

def save_user_notion_details(user_id: str, api_key: str, db_id: str):
    """Updates a user's Notion credentials."""
    try:
        db.collection('user_profiles').document(user_id).update({
            "notion_api_key": api_key, # NOTE: In production, you'd encrypt this
            "notion_database_id": db_id,
            "sync_notion": True # Automatically enable sync
        })
        print(f"Saved Notion details for user {user_id}")
    except Exception as e:
        print(f"Error saving Notion details for user {user_id}: {e}")

def save_user_google_token(user_id: str, refresh_token: str):
    """Saves the Google Calendar Refresh Token."""
    try:
        db.collection('user_profiles').document(user_id).update({
            "google_refresh_token": refresh_token, # NOTE: In production, you'd encrypt this
            "sync_calendar": True # Automatically enable sync
        })
        print(f"Saved Google token for user {user_id}")
    except Exception as e:
        print(f"Error saving Google token for user {user_id}: {e}")

#################################################
# SECTION 2: SCHEDULER & ACTIVITY LOG HELPERS
#################################################

def add_scheduled_event(user_id: str, phone_number: str, title: str, deadline_utc: datetime, reminder_time_utc: datetime):
    """Adds a new event to the scheduler collection AND logs the activity."""
    try:
        # 1. Add the event to be scheduled
        event_ref = db.collection('scheduled_events').document()
        event_ref.set({
            "user_id": user_id,
            "phone_number": phone_number,
            "event_title": title,
            "event_deadline_utc": deadline_utc,
            "reminder_time_utc": reminder_time_utc,
            "reminder_sent": False
        })
        
        # 2. Add this action to the user's activity feed (for the rich dashboard)
        _log_activity(
            user_id=user_id,
            icon="FiCheckCircle", # Icon name from react-icons
            title="Event Synced",
            description=f"'{title}' was successfully added to your sync queue."
        )
        
        # 3. Update the user's stats
        _update_user_stat(user_id, 'stats_total_synced')

        print(f"Successfully scheduled event for {user_id}: {title}")
        
    except Exception as e:
        print(f"Error adding scheduled event for user {user_id}: {e}")

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
            data['id'] = doc.id # Add the document ID
            pending_reminders.append(data)
        return pending_reminders
    except Exception as e:
        print(f"Error fetching pending reminders: {e}")
        return []

def mark_reminder_as_sent(event_id: str, user_id: str, title: str):
    """
    Marks a reminder as sent AND logs the activity.
    This is called by the scheduler.
    """
    try:
        # 1. Mark the event as sent
        db.collection('scheduled_events').document(event_id).update({
            "reminder_sent": True
        })
        
        # 2. Log this action to the user's activity feed
        _log_activity(
            user_id=user_id,
            icon="FiCalendar", # Icon name from react-icons
            title="Reminder Sent",
            description=f"A 1-hour reminder for '{title}' was sent to your WhatsApp."
        )
        
        # 3. Update the user's stats
        _update_user_stat(user_id, 'stats_reminders_sent')
        
        print(f"Successfully marked reminder {event_id} as sent.")
        
    except Exception as e:
        print(f"Error marking reminder {event_id} as sent: {e}")

#################################################
# SECTION 3: NEW FEATURE-RICH DASHBOARD FUNCTIONS
#################################################

def _log_activity(user_id: str, icon: str, title: str, description: str):
    """
    Internal helper to add an item to a user's activity feed.
    This creates a new document in a subcollection.
    """
    try:
        activity_ref = db.collection('user_profiles').document(user_id).collection('activity_feed').document()
        activity_ref.set({
            "timestamp": firestore.SERVER_TIMESTAMP,
            "icon": icon,
            "title": title,
            "description": description
        })
    except Exception as e:
        print(f"Error logging activity for user {user_id}: {e}")

def _update_user_stat(user_id: str, stat_field: str):
    """
    Internal helper to atomically increment a user's stats.
    e.g., 'stats_total_synced' or 'stats_reminders_sent'
    """
    try:
        profile_ref = db.collection('user_profiles').document(user_id)
        profile_ref.update({
            stat_field: firestore.Increment(1)
        })
    except Exception as e:
        print(f"Error incrementing stat {stat_field} for user {user_id}: {e}")

def get_user_stats(user_id: str):
    """
    Fetches the user's aggregated stats for the dashboard.
    """
    profile = get_profile_by_user_id(user_id)
    if profile:
        return {
            "totalSynced": profile.get('stats_total_synced', 0),
            "remindersSent": profile.get('stats_reminders_sent', 0)
        }
    return {"totalSynced": 0, "remindersSent": 0}

def get_recent_activity(user_id: str, page: int = 1, limit: int = 5):
    """
    Fetches a paginated list of a user's recent activity for the dashboard feed.
    """
    try:
        # Order by timestamp in descending order
        query = db.collection('user_profiles').document(user_id) \
                  .collection('activity_feed') \
                  .order_by('timestamp', direction=firestore.Query.DESCENDING) \
                  .limit(limit)
        
        # Handle pagination (basic, not cursor-based for simplicity)
        if page > 1:
            # Get the last document from the previous page
            offset_query = db.collection('user_profiles').document(user_id) \
                             .collection('activity_feed') \
                             .order_by('timestamp', direction=firestore.Query.DESCENDING) \
                             .limit((page - 1) * limit) \
                             .get()
            
            if offset_query:
                last_doc = offset_query[-1]
                query = query.start_after(last_doc)
        
        docs = query.stream()
        
        activity_list = []
        for doc in docs:
            activity = doc.to_dict()
            # Convert Firestore timestamp to ISO 8601 string for JSON
            activity['id'] = doc.id
            activity['timestamp'] = activity['timestamp'].isoformat()
            activity_list.append(activity)
            
        return activity_list
    except Exception as e:
        print(f"Error getting recent activity for user {user_id}: {e}")
        return []