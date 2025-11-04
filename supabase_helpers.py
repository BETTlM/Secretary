import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user_by_phone(phone_number: str):
    """
    Fetches a user's profile from the database using their phone number.
    Remember, Meta sends numbers like '14155552671', not 'whatsapp:+1...'.
    You may need to clean the 'from_number' in app.py before calling this.
    """
    try:
        response = supabase.table("users").select("*").eq("id", phone_number).execute()
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting user: {e}")
        return None

def create_user_record(phone_number: str):
    """
    Creates a new, basic user record.
    This would be called from your web portal, not the bot.
    """
    try:
        response = supabase.table("users").insert({
            "id": phone_number,
            "sync_notion": False,
            "sync_calendar": True
        }).execute()
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error creating user: {e}")
        return None

def save_user_notion_details(phone_number: str, api_key: str, db_id: str):
    """
    Updates a user's record with their Notion credentials.
    """
    try:
        supabase.table("users").update({
            "notion_api_key": api_key,
            "notion_database_id": db_id
        }).eq("id", phone_number).execute()
    except Exception as e:
        print(f"Error saving Notion details: {e}")

def save_user_google_token(phone_number: str, refresh_token: str):
    """
    Saves the all-important Google Refresh Token to the user's record.
    """
    try:
        supabase.table("users").update({
            "google_refresh_token": refresh_token
        }).eq("id", phone_number).execute()
    except Exception as e:
        print(f"Error saving Google token: {e}")

def update_user_sync_preference(phone_number: str, service: str, status: bool):
    """
    Toggles syncing on or off (e.g., service='sync_notion', status=False)
    """
    try:
        supabase.table("users").update({
            service: status
        }).eq("id", phone_number).execute()
    except Exception as e:
        print(f"Error updating sync preference: {e}")