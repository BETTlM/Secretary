import os
from flask import Flask, request, abort, render_template, redirect, session, url_for, flash
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timedelta, timezone # <-- NEW IMPORT

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
    sign_up_with_email,
    sign_in_with_email,
    get_user_by_phone,
    get_profile_by_user_id,
    create_profile_if_not_exists,
    save_phone_number,
    save_user_notion_details,
    save_user_google_token,
    add_scheduled_event  # <-- NEW IMPORT
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
GOOGLE_CREDS_FILE = 'credentials.json'

#################################################
# SECTION 1: WHATSAPP BOT WEBHOOK (Updated)
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
                
                user_profile = get_user_by_phone(from_number)
                if not user_profile:
                    send_whatsapp_message(from_number, "Hi! I don't recognize your number. Please sign up at https://bettims-donna.onrender.com to use this service.")
                    return "OK", 200
                
                # We pass the current time to the prompt for better accuracy
                user_local_time = datetime.now().isoformat()
                event_data = call_gemini_api(message_body, user_local_time)
                
                if not event_data:
                    send_whatsapp_message(from_number, "Sorry, I had a problem understanding that. Please try again.")
                    return "OK", 200

                title = event_data.get('title')
                deadline_str = event_data.get('deadline_utc') # This is a STRING
                
                if not title or not deadline_str:
                    send_whatsapp_message(from_number, "Sorry, I understood the event but couldn't find a clear title or deadline. Please try again.")
                    return "OK", 200

                priority = event_data.get('priority', 'medium')
                
                # --- NEW SCHEDULER LOGIC ---
                try:
                    # 1. Convert deadline string to a real datetime object
                    deadline_utc = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    
                    # 2. Calculate the reminder time (1 hour before)
                    reminder_time_utc = deadline_utc - timedelta(hours=1)
                    
                except Exception as e:
                    print(f"Error parsing deadline string '{deadline_str}': {e}")
                    send_whatsapp_message(from_number, "Sorry, I couldn't parse the deadline format from the AI.")
                    return "OK", 200

                # 3. Save the event to the database for the scheduler
                add_scheduled_event(
                    user_id=user_profile['id'],
                    phone_number=from_number,
                    title=title,
                    deadline_utc=deadline_utc,
                    reminder_time_utc=reminder_time_utc
                )
                
                # --- SYNC TO OTHER SERVICES ---
                if (user_profile.get('sync_notion') and 
                    user_profile.get('notion_api_key') and 
                    user_profile.get('notion_database_id')):
                    create_notion_page(user_profile['notion_api_key'], user_profile['notion_database_id'], title, deadline_str, priority)
                
                if (user_profile.get('sync_calendar') and 
                    user_profile.get('google_refresh_token')):
                    service = get_google_service_from_token(user_profile['google_refresh_token'])
                    if service:
                        create_google_calendar_event(service, title, deadline_str)
                
                # 4. Send the NEW, enhanced confirmation message
                reply_message = (
                    f"✅ *Event Synced!*\n\n"
                    f"*Event:* {title}\n"
                    f"*Deadline:* {deadline_str}\n"
                    f"*Priority:* {priority.capitalize()}\n\n"
                    f"I'll send you a reminder 1 hour before it's due."
                )
                send_whatsapp_message(from_number, reply_message)
                
        except Exception as e:
            print(f"Error processing message: {e}")
        
        return "OK", 200
    
    else:
        abort(405)

#################################################
# SECTION 2: WEBSITE & USER AUTH (Unchanged)
#################################################

@app.route("/")
def home():
    user = session.get('user')
    if user:
        profile = get_profile_by_user_id(user['id'])
        if not profile or not profile.get('phone_number'):
            return redirect(url_for('onboarding'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route("/register", methods=['POST'])
def handle_register():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for('register'))
        
    response, error = sign_up_with_email(email, password)
    
    if error:
        flash(f"Sign up failed: {error}", "error")
        return redirect(url_for('register'))
    elif response.user:
        flash("Registration successful! Please check your email to verify.", "info")
        return redirect(url_for('login'))
        
    return redirect(url_for('register'))

@app.route("/login", methods=['POST'])
def handle_login():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for('login'))

    response, error = sign_in_with_email(email, password)

    if error:
        flash(f"Login failed: {error}", "error")
        return redirect(url_for('login'))
    elif response.session:
        session['user'] = response.user.dict()
        return redirect(url_for('home'))
        
    return redirect(url_for('login'))

@app.route("/auth/google")
def auth_google():
    """Redirects user to Google for Supabase login."""
    try:
        redirect_url = supabase.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": url_for("auth_callback", _external=True)
                }
            }
        )
        return redirect(redirect_url.url)
    except Exception as e:
        print(f"Error in /auth/google: {e}")
        flash("Could not connect to Google Sign-In.", "error")
        return redirect(url_for('login'))


@app.route("/auth/callback")
def auth_callback():
    """Handles the callback from Supabase (Google) Auth."""
    try:
        auth_code = request.args.get("code")
        session_data = supabase.auth.exchange_code_for_session(auth_code)
        
        user = session_data.user
        session['user'] = user.dict()
        
        create_profile_if_not_exists(user)
        
        return redirect(url_for('home'))
    except Exception as e:
        print(f"Auth callback error: {e}")
        flash("An error occurred during sign-in. Please try again.", "error")
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
    if not profile:
        flash("Could not find user profile. Please log in again.", "error")
        session.clear()
        return redirect(url_for('login'))

    return render_template(
        "dashboard.html",
        user_email=profile.get('email'),
        user_phone=profile.get('phone_number', 'Not Set'),
        has_calendar_token=bool(profile.get('google_refresh_token')),
        has_notion_keys=bool(profile.get('notion_api_key'))
    )

@app.route("/setup-notion")
def setup_notion():
    user_session = session.get('user')
    if not user_session:
        return redirect(url_for('login'))
    
    profile = get_profile_by_user_id(user_session['id'])
    return render_template(
        "setup_notion.html",
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
    flash("Notion settings saved successfully!", "info")
    return redirect(url_for('dashboard'))

#################################################
# SECTION 3: GOOGLE CALENDAR (Unchanged)
#################################################

@app.route("/connect-google-calendar")
def connect_google_calendar():
    """Starts the Google CALENDAR scope authorization flow."""
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
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
    
    try:
        flow.fetch_token(authorization_response=request.url)
        refresh_token = flow.credentials.refresh_token
        save_user_google_token(user['id'], refresh_token)
        flash("Google Calendar connected successfully!", "info")
    except Exception as e:
        print(f"Error in calendar callback: {e}")
        flash("Failed to connect Google Calendar.", "error")
    
    return redirect(url_for('dashboard'))


if __name__ == "__main__":
    app.run(port=5000, debug=True)