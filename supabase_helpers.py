import os
from supabase import create_client, Client
from gotrue.types import User
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def sign_up_with_email(email, password):
    """Signs up a new user."""
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        if response.user:
            create_profile_if_not_exists(response.user)
        return response, None
    except Exception as e:
        return None, e

def sign_in_with_email(email, password):
    """Signs in an existing user."""
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return response, None
    except Exception as e:
        return None, e

def get_user_by_phone(phone_number: str):
    """Finds a user profile by their phone number for the bot."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        response = supabase.table("user_profiles").select("*").eq("phone_number", cleaned_phone).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting user by phone: {e}")
        return None

def get_profile_by_user_id(user_id: str):
    """Finds a user profile by their auth ID for the website."""
    try:
        response = supabase.table("user_profiles").select("*").eq("id", user_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting profile by ID: {e}")
        return None

def create_profile_if_not_exists(user: User):
    """Creates a user profile when they sign up."""
    try:
        existing = get_profile_by_user_id(user.id)
        if existing:
            return existing
        response = supabase.table("user_profiles").insert({
            "id": user.id,
            "email": user.email
        }).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Error creating profile: {e}")

def save_phone_number(user_id: str, phone_number: str):
    """Updates a user's profile with their phone number."""
    try:
        cleaned_phone = "".join(filter(str.isdigit, phone_number))
        supabase.table("user_profiles").update({
            "phone_number": cleaned_phone
        }).eq("id", user_id).execute()
    except Exception as e:
        print(f"Error saving phone number: {e}")

def save_user_notion_details(user_id: str, api_key: str, db_id: str):
    """Updates a user's Notion credentials."""
    try:
        supabase.table("user_profiles").update({
            "notion_api_key": api_key,
            "notion_database_id": db_id
        }).eq("id", user_id).execute()
    except Exception as e:
        print(f"Error saving Notion details: {e}")

def save_user_google_token(user_id: str, refresh_token: str):
    """Saves the Google Calendar Refresh Token."""
    try:
        supabase.table("user_profiles").update({
            "google_refresh_token": refresh_token
        }).eq("id", user_id).execute()
    except Exception as e:
        print(f"Error saving Google token: {e}")

def add_scheduled_event(user_id: str, phone_number: str, title: str, deadline_utc: datetime, reminder_time_utc: datetime):
    """Adds a new event to the scheduler table."""
    try:
        response = supabase.table("scheduled_events").insert({
            "user_id": user_id,
            "phone_number": phone_number,
            "event_title": title,
            "event_deadline_utc": deadline_utc.isoformat(),
            "reminder_time_utc": reminder_time_utc.isoformat()
        }).execute()
        return response
    except Exception as e:
        print(f"Error adding scheduled event: {e}")
        return None

def get_pending_reminders(now_utc: datetime):
    """Fetches all reminders that are due to be sent."""
    try:
        response = supabase.table("scheduled_events").select("*").eq("reminder_sent", False).lte("reminder_time_utc", now_utc.isoformat()).execute()
        return response.data
    except Exception as e:
        print(f"Error fetching pending reminders: {e}")
        return []

def mark_reminder_as_sent(event_id: int):
    """Marks a reminder as sent so it doesn't send again."""
    try:
        supabase.table("scheduled_events").update({
            "reminder_sent": True
        }).eq("id", event_id).execute()
    except Exception as e:
        print(f"Error marking reminder as sent: {e}")