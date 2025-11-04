import os
import json
import requests
import google.generativeai as genai
from notion_client import Client
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def send_whatsapp_message(to_number: str, text: str):
    """Sends a reply message using the Meta Graph API."""
    PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID")
    ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
    
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    
    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise an error for bad status codes
        print(f"WhatsApp message sent to {to_number}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send WhatsApp message: {e}")

# --- 2. GEMINI FUNCTION ---
def call_gemini_api(text: str):
    """Sends text to Gemini and gets structured JSON back."""
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash',
                                  generation_config={"response_mime_type": "application/json"})
    
    prompt = f"""
    You are an event parsing assistant. Analyze the following text and extract 
    the event title, deadline (as an ISO 8601 UTC string), and priority.

    Priority must be "high", "medium", or "low". Default to "medium".
    Assume the current year is {datetime.now().year}.
    If no specific time is mentioned, default to 5:00 PM in the user's timezone.
    For deadlines like "tomorrow", calculate the date based on today: {datetime.now().isoformat()}

    Respond ONLY with a JSON object.

    Text: "{text}"
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

# --- 3. NOTION FUNCTION ---
def create_notion_page(api_key: str, db_id: str, title: str, deadline: str, priority: str):
    """Creates a new page in a user's specific Notion database."""
    try:
        notion = Client(auth=api_key)
        
        new_page_data = {
            "parent": {"database_id": db_id},
            "properties": {
                "Title": {"title": [{"text": {"content": title}}]},
                "Deadline": {"date": {"start": deadline}},
                "Priority": {"select": {"name": priority}}
            }
        }
        notion.pages.create(**new_page_data)
        print("Notion page created.")
        return True
    except Exception as e:
        print(f"Notion API error: {e}")
        return False

# --- 4. GOOGLE CALENDAR FUNCTIONS ---
def get_google_service_from_token(refresh_token: str):
    """
    Creates a Google Calendar service object from a user's refresh token.
    This is the key to acting on their behalf.
    """
    CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    try:
        creds = Credentials(
            token=None,  # No access token, we have a refresh token
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=['https://www.googleapis.com/auth/calendar.events']
        )
        
        creds.refresh(requests.Request())
        
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Google service: {e}")
        return None

def create_google_calendar_event(service, title: str, deadline_utc: str):
    """Creates a new event in the user's Google Calendar."""
    try:
        end_time = datetime.fromisoformat(deadline_utc.replace('Z', '+00:00'))
        start_time = end_time - timedelta(hours=1)

        event = {
          'summary': title,
          'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
          'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'},
        }
        service.events().insert(calendarId='primary', body=event).execute()
        print("Google Calendar event created.")
        return True
    except Exception as e:
        print(f"Google Calendar API error: {e}")
        return False