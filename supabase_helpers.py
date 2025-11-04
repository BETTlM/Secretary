import os
from supabase import create_client, Client
from gotrue.types import User

# Initialize Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user_by_phone(phone_number: str):
    """
    Finds a user profile by their phone number.
    This is for the WHATSAPP BOT to use.
    """
    try:
        response = supabase.table("user_profiles").select("*").eq("phone_number", phone_number).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting user by phone: {e}")
        return None

def get_profile_by_user_id(user_id: str):
    """
    Finds a user profile by their auth ID.
    This is for the WEBSITE to use.
    """
    try:
        response = supabase.table("user_profiles").select("*").eq("id", user_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting profile by ID: {e}")
        return None

def create_profile_if_not_exists(user: User):
    """
    When a user logs in with Google, this creates their
    profile in our 'user_profiles' table.
    """
    try:
        # Check if profile already exists
        existing = get_profile_by_user_id(user.id)
        if existing:
            return existing
        
        # Create new profile
        response = supabase.table("user_profiles").insert({
            "id": user.id,
            "email": user.email
        }).execute()
        
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Error creating profile: {e}")

def save_phone_number(user_id: str, phone_number: str):
    """
    Updates a user's profile with their phone number from onboarding.
    """
    try:
        # Clean the number (remove '+', 'whatsapp:', etc.)
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