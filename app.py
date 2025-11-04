# app.py
import os
from flask import Flask, request, abort, render_template, redirect, session, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

# Import our helper files
from core_logic import (
    send_whatsapp_message, 
    call_gemini_api, 
    create_notion_page, 
    get_google_service_from_token, 
    create_google_calendar_event
)
from supabase_helpers import (
    supabase,
    get_user_by_phone,
    get_profile_by_user_id,
    create_profile_if_not_exists,
    save_phone_number,
    save_user_notion_details,
    save_user_google_token
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
GOOGLE_CREDS_FILE = 'credentials.json'

#################################################
# SECTION 1: WHATSAPP BOT WEBHOOK (The Bot)
#################################################

@app.route("/whatsapp-webhook", methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        else:
            return "Error, bad token", 403
            
    elif request.method == 'POST':
        payload = request.get_json()
        print(f"Incoming payload: {payload}")
        try:
            if 'entry' in payload and payload['entry'][0]['changes'][0]['value'].get('messages'):
                message_data = payload['entry'][0]['changes'][0]['value']['messages'][0]
                from_number = message_data['from']
                message_body = message_data['text']['body']
                
                # --- CORE LOGIC (Now uses the new DB helper) ---
                user_profile = get_user_by_phone(from_number)
                if not user_profile:
                    send_whatsapp_message(from_number, "Hi! I don't recognize your number. Please sign up at https://bettims-donna.onrender.com to use this service.")
                    return "OK", 200
                
                event_data = call_gemini_api(message_body)

                if not event_data:
                    send_whatsapp_message(from_number, "Sorry, I had a problem understanding that. Please try again.")
                    return "OK", 200

                title = event_data.get('title')
                deadline = event_data.get('deadline_utc') # This might be None

                if not title or not deadline:
                    send_whatsapp_message(from_number, "Sorry, I understood the event but couldn't find a clear title or deadline. Please try again.")
                    return "OK", 200

                priority = event_data.get('priority', 'medium')
                
                if user_profile.get('sync_notion'):
                    create_notion_page(user_profile['notion_api_key'], user_profile['notion_database_id'], title, deadline, priority)
                
                if user_profile.get('sync_calendar'):
                    service = get_google_service_from_token(user_profile['google_refresh_token'])
                    if service:
                        create_google_calendar_event(service, title, deadline)
                
                send_whatsapp_message(from_number, f"✅ Event '{title}' has been synced!")
        except Exception as e:
            print(f"Error processing message: {e}")
        
        return "OK", 200
    
    else:
        abort(405)

#################################################
# SECTION 2: WEBSITE & USER AUTH (The SaaS)
#################################################

@app.route("/")
def home():
    # Check if user is logged in
    user = session.get('user')
    if user:
        # Check if they have a phone number
        profile = get_profile_by_user_id(user['id'])
        if not profile.get('phone_number'):
            return redirect(url_for('onboarding'))
        return redirect(url_for('dashboard'))
    
    return redirect(url_for('login'))

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/auth/google")
def auth_google():
    """Redirects user to Google for Supabase login."""
    redirect_url = supabase.auth.sign_in_with_oauth(
        {
            "provider": "google",
            "options": {
                "redirect_to": url_for("auth_callback", _external=True)
            }
        }
    )
    return redirect(redirect_url.url)

@app.route("/auth/callback")
def auth_callback():
    """Handles the callback from Supabase (Google) Auth."""
    try:
        auth_code = request.args.get("code")
        session_data = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        
        # Store user info in Flask session
        user = session_data.user
        session['user'] = user.dict()
        
        # Create their profile in our public.user_profiles table
        create_profile_if_not_exists(user)
        
        return redirect(url_for('home'))
    except Exception as e:
        print(f"Auth callback error: {e}")
        return redirect(url_for('login'))

@app.route("/onboarding")
def onboarding():
    if not session.get('user'):
        return redirect(url_for('login'))
    return render_template("onboarding.html")

@app.route("/save-phone", methods=['POST'])
def save_phone():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
        
    phone = request.form['phone']
    save_phone_number(user['id'], phone)
    return redirect(url_for('dashboard'))

@app.route("/dashboard")
def dashboard():
    user_session = session.get('user')
    if not user_session:
        return redirect(url_for('login'))
    
    profile = get_profile_by_user_id(user_session['id'])
    return render_template(
        "dashboard.html",
        user_email=profile.get('email'),
        has_calendar_token=bool(profile.get('google_refresh_token')),
        notion_key=profile.get('notion_api_key', ''),
        notion_db_id=profile.get('notion_database_id', '')
    )

@app.route("/save-notion", methods=['POST'])
def save_notion():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    
    notion_key = request.form['notion_key']
    notion_db_id = request.form['notion_db_id']
    save_user_notion_details(user['id'], notion_key, notion_db_id)
    return redirect(url_for('dashboard'))

#################################################
# SECTION 3: GOOGLE CALENDAR (The original flow)
#################################################

@app.route("/connect-google-calendar")
def connect_google_calendar():
    """Starts the Google CALENDAR scope authorization flow."""
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
    # 'access_type=offline' is CRITICAL to get a refresh_token
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    session['google_oauth_state'] = state
    return redirect(authorization_url)

@app.route("/google-auth-callback-calendar")
def google_auth_callback_calendar():
    """Handles the callback from the CALENDAR flow."""
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
        
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=session['google_oauth_state'],
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
    
    flow.fetch_token(authorization_response=request.url)
    refresh_token = flow.credentials.refresh_token
    
    # Save the token to the user's profile
    save_user_google_token(user['id'], refresh_token)
    
    return redirect(url_for('dashboard'))


if __name__ == "__main__":
    app.run(port=5000, debug=True)