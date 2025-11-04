# app.py
import os
from flask import Flask, request, abort, render_template, redirect, session, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import google.generativeai as genai

# Import all our helper functions
from core_logic import (
    send_whatsapp_message, 
    call_gemini_api, 
    create_notion_page, 
    get_google_service_from_token, 
    create_google_calendar_event
)
from supabase_helpers import (
    get_user_by_phone, 
    save_user_notion_details, 
    save_user_google_token
)

app = Flask(__name__)

# --- SECRET CONFIGURATION ---
# This MUST be set in Render's Environment Variables
app.secret_key = os.environ.get("FLASK_SECRET_KEY") 
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # Allow http for local testing. Render will use https.

# --- PATH TO YOUR CREDENTIALS FILE ---
# This must be uploaded as a "Secret File" on Render
GOOGLE_CREDS_FILE = 'credentials.json'

#################################################
# SECTION 1: WHATSAPP BOT WEBHOOK
#################################################

@app.route("/whatsapp-webhook", methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # --- Webhook Verification (called once by Meta) ---
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        else:
            return "Error, bad token", 403
            
    elif request.method == 'POST':
        # --- Handle Incoming Messages ---
        payload = request.get_json()
        print(f"Incoming payload: {payload}")

        try:
            # Extract message details
            if 'entry' in payload and payload['entry'][0]['changes'][0]['value'].get('messages'):
                message_data = payload['entry'][0]['changes'][0]['value']['messages'][0]
                from_number = message_data['from']  # User's phone number
                message_body = message_data['text']['body']
                
                print(f"Message from {from_number}: {message_body}")

                # --- CORE LOGIC ---
                
                # 1. Find user in database
                user = get_user_by_phone(from_number)
                if not user:
                    send_whatsapp_message(from_number, "Hi! I don't recognize you. Please sign up at [Your Website URL] to use this service.")
                    return "OK", 200

                # 2. Call Gemini to parse
                event_data = call_gemini_api(message_body)
                if not event_data or 'title' not in event_data or 'deadline_utc' not in event_data:
                    send_whatsapp_message(from_number, "Sorry, I couldn't understand the date or event. Please try again.")
                    return "OK", 200

                title = event_data.get('title')
                deadline = event_data.get('deadline_utc')
                priority = event_data.get('priority', 'medium')
                
                success_messages = []

                # 3. Sync to Notion (if enabled)
                if user.get('sync_notion') and user.get('notion_api_key'):
                    if create_notion_page(user['notion_api_key'], user['notion_database_id'], title, deadline, priority):
                        success_messages.append("Notion")

                # 4. Sync to Google Calendar (if enabled)
                if user.get('sync_calendar') and user.get('google_refresh_token'):
                    service = get_google_service_from_token(user['google_refresh_token'])
                    if service and create_google_calendar_event(service, title, deadline):
                        success_messages.append("Google Calendar")
                
                # 5. Send confirmation
                if not success_messages:
                    send_whatsapp_message(from_number, f"Event '{title}' created, but I couldn't sync it. Please check your settings on the website.")
                else:
                    send_whatsapp_message(from_number, f"✅ Event '{title}' synced to: {', '.join(success_messages)}")

        except Exception as e:
            print(f"Error processing message: {e}")
        
        # Always return 200 OK to Meta
        return "OK", 200
    
    else:
        abort(405) # Method Not Allowed


#################################################
# SECTION 2: USER SETUP WEBSITE
# You will need to create HTML files for these.
#################################################

@app.route("/")
def home():
    # A simple home page with a "Login" button
    # For a real SaaS, you'd have user login (e.g., Supabase Auth)
    # For now, we'll just link to the setup page.
    return 'Welcome! <a href="/setup">Set up your account</a>'

@app.route("/setup", methods=['GET', 'POST'])
def setup():
    # THIS IS A SIMPLIFIED EXAMPLE.
    # In a real app, you'd have a user session.
    # We'll use a hardcoded phone number for this example.
    # YOU MUST REPLACE THIS with a real login system.
    session['phone_number'] = "14155552671" # Hardcoded example user
    
    if request.method == 'POST':
        # This is where the user submits their Notion details
        notion_key = request.form['notion_key']
        notion_db_id = request.form['notion_db_id']
        save_user_notion_details(session['phone_number'], notion_key, notion_db_id)
        return redirect(url_for('setup'))

    # This is a basic HTML string. You should use render_template()
    return """
    <h2>Setup Your Integrations</h2>
    
    <h3>1. Connect Notion</h3>
    <form method="POST">
        Notion API Key: <input type="text" name="notion_key" /><br/>
        Notion DB ID: <input type="text" name="notion_db_id" /><br/>
        <input type="submit" value="Save Notion" />
    </form>
    
    <h3>2. Connect Google Calendar</h3>
    <a href="/connect-google">Click here to authorize Google</a>
    """

@app.route("/connect-google")
def connect_google():
    """Starts the Google OAuth flow."""
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri=url_for('google_auth_callback', _external=True)
    )
    authorization_url, state = flow.authorization_url()
    session['google_oauth_state'] = state
    return redirect(authorization_url)

@app.route("/google-auth-callback")
def google_auth_callback():
    """Handles the redirect from Google."""
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=session['google_oauth_state'],
        redirect_uri=url_for('google_auth_callback', _external=True)
    )
    
    # Exchange the code Google gave us for a token
    flow.fetch_token(authorization_response=request.url)
    
    # Get the refresh token
    refresh_token = flow.credentials.refresh_token
    
    # Get the user's phone number (from our example session)
    phone_number = session.get('phone_number') 
    
    if not phone_number:
        return "Error: No user session found. Please log in.", 400
        
    # Save the token to the database
    save_user_google_token(phone_number, refresh_token)
    
    return "Google Calendar connected successfully! You can close this tab."


# --- Run the App (for local testing) ---
if __name__ == "__main__":
    app.run(port=5000, debug=True)