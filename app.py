import os
import json  # Import json for parsing metadata
from flask import (
    Flask, request, abort, render_template, 
    redirect, session, url_for, flash
)
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timedelta, timezone
from functools import wraps # We'll use this for a login decorator

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
    add_scheduled_event
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
GOOGLE_CREDS_FILE = 'credentials.json'

#################################################
# SECTION 1: WHATSAPP BOT WEBHOOK (Unchanged)
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
                
                # Get current time for the prompt
                user_local_time = datetime.now().isoformat()
                event_data = call_gemini_api(message_body)
                
                if not event_data:
                    send_whatsapp_message(from_number, "Sorry, I had a problem understanding that. Please try again.")
                    return "OK", 200

                title = event_data.get('title')
                deadline_str = event_data.get('deadline_utc')
                
                if not title or not deadline_str:
                    send_whatsapp_message(from_number, "Sorry, I understood the event but couldn't find a clear title or deadline. Please try again.")
                    return "OK", 200

                priority = event_data.get('priority', 'medium')
                
                # --- NEW LOGIC TO CHECK REMINDER TIME ---
                will_send_reminder = False
                reminder_message = ""

                try:
                    # 1. Convert deadline string to a real datetime object
                    deadline_utc = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    
                    # 2. Calculate the reminder time (1 hour before)
                    reminder_time_utc = deadline_utc - timedelta(hours=1)
                    
                    # 3. Get the current time in UTC
                    now_utc = datetime.now(timezone.utc)
                    
                    # 4. Check if the reminder time is in the future
                    if reminder_time_utc > now_utc:
                        will_send_reminder = True
                        add_scheduled_event(
                            user_id=user_profile['id'],
                            phone_number=from_number,
                            title=title,
                            deadline_utc=deadline_utc,
                            reminder_time_utc=reminder_time_utc
                        )
                        reminder_message = "I'll send you a reminder 1 hour before it's due."
                    else:
                        reminder_message = "The 1-hour reminder time for this event is already in the past, so a reminder won't be sent."
                    
                except Exception as e:
                    print(f"Error parsing deadline or scheduling: {e}")
                    reminder_message = "Sorry, I couldn't parse the deadline to schedule a reminder."                
                # Sync to Notion
                if (user_profile.get('sync_notion') and 
                    user_profile.get('notion_api_key') and 
                    user_profile.get('notion_database_id')):
                    create_notion_page(user_profile['notion_api_key'], user_profile['notion_database_id'], title, deadline_str, priority)
                
                # Sync to Google Calendar
                if (user_profile.get('sync_calendar') and 
                    user_profile.get('google_refresh_token')):
                    service = get_google_service_from_token(user_profile['google_refresh_token'])
                    if service:
                        create_google_calendar_event(service, title, deadline_str)
                
                # Send confirmation reply
                reply_message = (
                    f"✅ *Event Synced!*\n\n"
                    f"*Event:* {title}\n"
                    f"*Deadline:* {deadline_str[:-10:]}\n"
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
# SECTION 2: WEBSITE & USER AUTH (Rebuilt)
#################################################

# --- Auth Helper ---
def login_required(f):
    """A decorator to protect routes that require a login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Homepage & Auth Routes ---
@app.route("/")
def home():
    """Renders the public homepage or redirects to dashboard if logged in."""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template("index.html")

@app.route("/login")
def login_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template("login.html")

@app.route("/register")
def register_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('login_page'))

@app.route("/register", methods=['POST'])
def handle_register():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for('register_page'))
        
    response, error = sign_up_with_email(email, password)
    
    if error:
        flash(f"Sign up failed: {error}", "error")
        return redirect(url_for('register_page'))
    elif response.user:
        
        # --- FIX #1: Ensure profile is created for email sign-ups ---
        # This ensures that email/pass users also get a profile
        # in your 'profiles' table, just like OAuth users.
        try:
            create_profile_if_not_exists(response.user)
        except Exception as e:
            print(f"Error creating profile for new email user: {e}")
            # Don't block registration, but log the error
        # --- END OF FIX #1 ---

        flash("Registration successful! Please check your email to verify.", "info")
        return redirect(url_for('login_page'))
        
    return redirect(url_for('register_page'))

@app.route("/login", methods=['POST'])
def handle_login():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for('login_page'))

    response, error = sign_in_with_email(email, password)

    if error:
        flash(f"Login failed: {error}", "error")
        return redirect(url_for('login_page'))
    elif response.session:
        session['user'] = response.user.dict()
        return redirect(url_for('check_onboarding'))
        
    return redirect(url_for('login_page'))

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
        return redirect(url_for('login_page'))


@app.route("/auth/callback")
def auth_callback():
    """Handles the callback from Supabase (Google) Auth."""
    try:
        auth_code = request.args.get("code")
        
        # --- THIS IS THE FIX ---
        # The library expects a dictionary, not a string
        supabase.auth.exchange_code_for_session({"auth_code": auth_code})
        # --- END OF FIX ---

        user_response = supabase.auth.get_user()
        user = user_response.user

        if not user:
            print("DEBUG: User object is None after auth exchange.")
            raise Exception("User is None after auth exchange.")

        # --- FIX #2: Clean the user object before passing to helper ---
        # The error 'str' object has no attribute 'get' is likely
        # because user.user_metadata is a JSON string, not a dict.
        # This code checks and parses it, preventing the error.
        if isinstance(user.user_metadata, str):
            try:
                user.user_metadata = json.loads(user.user_metadata)
            except json.JSONDecodeError:
                print(f"Warning: could not parse user_metadata string: {user.user_metadata}")
                user.user_metadata = {} # Default to empty dict
        
        if isinstance(user.app_metadata, str):
            try:
                user.app_metadata = json.loads(user.app_metadata)
            except json.JSONDecodeError:
                print(f"Warning: could not parse app_metadata string: {user.app_metadata}")
                user.app_metadata = {}
        # --- END OF FIX #2 ---

        session['user'] = user.dict()
        create_profile_if_not_exists(user) # This should now work safely

        return redirect(url_for('check_onboarding'))

    except Exception as e:
        print(f"Auth callback error: {e}")
        import traceback
        print(traceback.format_exc())
        flash("An error occurred during sign-in. Please try again.", "error")
        return redirect(url_for('login_page'))

# --- Main App Routes ---

@app.route("/check-onboarding")
@login_required
def check_onboarding():
    """Checks if user has a phone number, routes to onboarding or dashboard."""
    user_id = session['user']['id']
    profile = get_profile_by_user_id(user_id)
    if not profile or not profile.get('phone_number'):
        return redirect(url_for('onboarding'))
    return redirect(url_for('dashboard'))

@app.route("/onboarding")
@login_required
def onboarding():
    return render_template("onboarding.html")

@app.route("/save-phone", methods=['POST'])
@login_required
def save_phone():
    user_id = session['user']['id']
    phone = request.form['phone']
    save_phone_number(user_id, phone)
    flash("Phone number saved!", "info")
    return redirect(url_for('dashboard'))

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session['user']['id']
    profile = get_profile_by_user_id(user_id)
    if not profile:
        flash("Could not find user profile. Please log in again.", "error")
        session.clear()
        return redirect(url_for('login_page'))

    # This context dictionary now includes all the data for the bento box
    context = {
        "user_email": profile.get('email'),
        "user_phone": profile.get('phone_number', ''),
        "has_calendar_token": bool(profile.get('google_refresh_token')),
        "has_notion_keys": bool(profile.get('notion_api_key')),
        "notion_key": profile.get('notion_api_key', ''),
        "notion_db_id": profile.get('notion_database_id', '')
    }
    return render_template("dashboard.html", **context)

@app.route("/save-notion", methods=['POST'])
@login_required
def save_notion():
    user_id = session['user']['id']
    notion_key = request.form['notion_key']
    notion_db_id = request.form['notion_db_id']
    save_user_notion_details(user_id, notion_key, notion_db_id)
    flash("Notion settings saved successfully!", "info")
    return redirect(url_for('dashboard'))

#################################################
# SECTION 3: GOOGLE CALENDAR (Protected)
#################################################

@app.route("/connect-google-calendar")
@login_required
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
@login_required
def google_auth_callback_calendar():
    """Handles the callback from the CALENDAR flow."""
    user_id = session['user']['id']
    
    # Check for state to prevent CSRF
    if 'google_oauth_state' not in session or session['google_oauth_state'] != request.args.get('state'):
        flash("Invalid state. Authentication request denied.", "error")
        return redirect(url_for('dashboard'))

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=session['google_oauth_state'],
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
    
    try:
        flow.fetch_token(authorization_response=request.url)
        refresh_token = flow.credentials.refresh_token
        
        if not refresh_token:
             # This happens if the user has already approved the app and doesn't
             # re-consent. The 'prompt=consent' in the authorization_url
             # is meant to force this, but we handle it just in case.
             flash("Could not get a refresh token. Please make sure you are granting offline access.", "error")
             return redirect(url_for('dashboard'))

        save_user_google_token(user_id, refresh_token)
        flash("Google Calendar connected successfully!", "info")
    except Exception as e:
        print(f"Error in calendar callback: {e}")
        flash("Failed to connect Google Calendar. Please try again.", "error")
    
    return redirect(url_for('dashboard'))


if __name__ == "__main__":
    # Note: Render uses its own web server (like Gunicorn).
    # It will use the 'app' object.
    # For local testing, 'debug=True' is fine.
    # Render will set the PORT, so you should listen on 0.0.0.0
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)