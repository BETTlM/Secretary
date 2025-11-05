import os
import json
import requests
import google.generativeai as genai
from notion_client import Client
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
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
        response.raise_for_status()
        print(f"WhatsApp message sent to {to_number}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send WhatsApp message: {e}")

def call_gemini_api(text: str):
    """Sends text to Gemini and gets structured JSON back."""
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash',
                                  generation_config={"response_mime_type": "application/json"})
    
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    current_time_ist = datetime.now(ist_tz)
    today_date_str = current_time_ist.strftime("%Y-%m-%d %H:%M:%S %Z")

    prompt = f"""
    You are an expert event parser. Your task is to extract a 'title', 'deadline_utc', and 'priority' from the user's text.
    You MUST respond ONLY with a JSON object.

    **Current Time:**
    Today's date and time is: {today_date_str}
    This time is in **India Standard Time (IST, UTC+5:30)**.

    **Rules for Extraction:**
    1.  **title**: Extract the core event or task. Do NOT include the date, time, or priority words in the title.
    2.  **deadline_utc**:
        * All relative dates (like "tomorrow") and times (like "at 2pm") in the user's text are relative to the **Current Time** (which is in IST).
        * If no specific time is mentioned (e.g., "by November 22"), default the time to 5:00 PM (17:00) in **India Standard Time (IST)**.
        * After calculating the final date and time in IST, you MUST convert it to a full ISO 8601 UTC string (e.g., "YYYY-MM-DDTHH:MM:SSZ") for the final JSON output.
        * If no date or time can be found, this value MUST be `null`.
    3.  **priority**: Must be "high", "medium", or "low". If not mentioned, default to "medium".

    **Examples:**
    1.  User Text: "DSA assignment submission deadline, November 22. high priority"
        (Assuming current time is 2025-11-04 10:00:00 IST)
        {{
          "title": "DSA assignment submission",
          "deadline_utc": "2025-11-22T11:30:00Z",
          "priority": "high"
        }}
        (Calculation: "November 22" defaults to 17:00 IST -> 2025-11-22 17:00:00 IST -> 2025-11-22T11:30:00Z)

    2.  User Text: "Need to finish the project report by tomorrow at 2pm"
        (Assuming current time is 2025-11-04 10:00:00 IST)
        {{
          "title": "Finish the project report",
          "deadline_utc": "2025-11-05T08:30:00Z",
          "priority": "medium"
        }}
        (Calculation: "tomorrow" is 2025-11-05. "2pm" is 14:00 IST -> 2025-11-05 14:00:00 IST -> 2025-11-05T08:30:00Z)
        
    3.  User Text: "Buy groceries"
        {{
          "title": "Buy groceries",
          "deadline_utc": null,
          "priority": "medium"
        }}

    **User Text to Parse:**
    "{text}"
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

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

def get_google_service_from_token(refresh_token: str):
    """
    Creates a Google Calendar service object from a user's refresh token.
    This is the key to acting on their behalf.
    """
    CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=['https://www.googleapis.com/auth/calendar.events']
        )
        
        creds.refresh(Request())
        
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