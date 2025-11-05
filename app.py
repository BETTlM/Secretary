import os
import firebase_admin
from firebase_admin import auth, credentials
from flask import (
    Flask, request, abort, jsonify, make_response, session, url_for, g, redirect
)
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timedelta, timezone
from functools import wraps
from dotenv import load_dotenv

# Load all environment variables from .env
load_dotenv()

# Import all helper logic
# We will create/update these files in the next steps
from core_logic import (
    send_whatsapp_message, 
    call_gemini_api, 
    create_notion_page, 
    get_google_service_from_token, 
    create_google_calendar_event
)
from firebase_helpers import (
    db, 
    get_user_by_phone,
    get_profile_by_user_id,
    create_profile_if_not_exists,
    save_phone_number,
    save_user_notion_details,
    save_user_google_token,
    add_scheduled_event,
    verify_session_cookie,
    get_user_stats, # New feature-rich function
    get_recent_activity # New feature-rich function
)

app = Flask(__name__)

# --- CRITICAL: CORS Configuration ---
# This tells your backend to accept requests from your new frontend.
# You MUST replace "https://your-frontend-domain.com" with your Vercel URL later.
CORS(app, 
   supports_credentials=True, 
   origins=[
       "http://localhost:3000", 
       "https://your-frontend-domain.com"
   ]
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN")
GOOGLE_CREDS_FILE = 'credentials.json'
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

#################################################
# SECTION 1: WHATSAPP BOT WEBHOOK
#################################################

@app.route("/whatsapp-webhook", methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        else:
            print("Webhook verification failed: Bad token")
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
                    send_whatsapp_message(from_number, f"Hi! I don't recognize your number. Please sign up at {FRONTEND_URL} to use this service.")
                    return "OK", 200
                
                user_local_time = datetime.now().isoformat()
                event_data = call_gemini_api(message_body, user_local_time)
                
                if not event_data:
                    send_whatsapp_message(from_number, "Sorry, I had a problem understanding that. Please try again.")
                    return "OK", 200

                title = event_data.get('title')
                deadline_str = event_data.get('deadline_utc')
                
                if not title or not deadline_str:
                    send_whatsapp_message(from_number, "Sorry, I understood the event but couldn't find a clear title or deadline. Please try again.")
                    return "OK", 200

                priority = event_data.get('priority', 'medium')
                
                try:
                    deadline_utc = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    reminder_time_utc = deadline_utc - timedelta(hours=1)
                    now_utc = datetime.now(timezone.utc)
                except Exception as e:
                    print(f"Error parsing deadline string '{deadline_str}': {e}")
                    send_whatsapp_message(from_number, "Sorry, I couldn't parse the deadline format from the AI.")
                    return "OK", 200

                reminder_message = ""
                if reminder_time_utc > now_utc:
                    add_scheduled_event(
                        user_id=user_profile['id'],
                        phone_number=from_number,
                        title=title,
                        deadline_utc=deadline_utc,
                        reminder_time_utc=reminder_time_utc
                    )
                    reminder_message = "I'll send you a reminder 1 hour before it's due."
                else:
                    reminder_message = "The 1-hour reminder time is in the past, so a reminder won't be sent."
                
                if (user_profile.get('sync_notion') and 
                    user_profile.get('notion_api_key') and 
                    user_profile.get('notion_database_id')):
                    create_notion_page(user_profile['notion_api_key'], user_profile['notion_database_id'], title, deadline_str, priority)
                
                if (user_profile.get('sync_calendar') and 
                    user_profile.get('google_refresh_token')):
                    service = get_google_service_from_token(user_profile['google_refresh_token'])
                    if service:
                        create_google_calendar_event(service, title, deadline_str)
                
                reply_message = (
                    f"✅ *Event Synced!*\n\n"
                    f"*Event:* {title}\n"
                    f"*Deadline:* {deadline_str}\n"
                    f"*Priority:* {priority.capitalize()}\n\n"
                    f"{reminder_message}"
                )
                send_whatsapp_message(from_number, reply_message)
                
        except Exception as e:
            print(f"Error processing message: {e}")
        
        return "OK", 200
    
    else:
        abort(405)

#################################################
# SECTION 2: API & FIREBASE AUTH
#################################################

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_cookie = request.cookies.get('firebase_session')
        if not session_cookie:
            return jsonify({"error": "Not authenticated. Please log in."}), 401
        
        user = verify_session_cookie(session_cookie)
        if not user:
            return jsonify({"error": "Session cookie invalid or expired. Please log in again."}), 401
        
        g.user_id = user['uid']
        g.email = user.get('email', '')
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def home():
    return jsonify({"status": "AutoSync API is live and running"}), 200

@app.route("/session-login", methods=['POST'])
def session_login():
    try:
        id_token = request.json['idToken']
        expires_in = timedelta(days=14)
        session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
        
        response = make_response(jsonify({"status": "success"}))
        expires = datetime.now() + expires_in
        response.set_cookie(
            'firebase_session', 
            session_cookie, 
            expires=expires, 
            httponly=True, 
            secure=True, 
            samesite='None'
        )
        return response
    except Exception as e:
        print(f"Error creating session cookie: {e}")
        return abort(401, 'Failed to create session.')

@app.route("/logout", methods=['POST'])
def logout():
    response = make_response(jsonify({"status": "success"}))
    response.set_cookie('firebase_session', '', expires=0, httponly=True, secure=True, samesite='None')
    return response

@app.route("/create-profile", methods=['POST'])
@login_required
def create_profile():
    profile = create_profile_if_not_exists(g.user_id, g.email)
    return jsonify(profile), 200

#################################################
# SECTION 3: API - DATA & DASHBOARD
#################################################

@app.route("/api/v1/user/profile", methods=['GET'])
@login_required
def get_user_profile():
    profile = get_profile_by_user_id(g.user_id)
    if not profile:
        profile = create_profile_if_not_exists(g.user_id, g.email)
        
    return jsonify(profile)

@app.route("/api/v1/user/stats", methods=['GET'])
@login_required
def get_stats():
    stats = get_user_stats(g.user_id)
    return jsonify(stats)

@app.route("/api/v1/user/activity", methods=['GET'])
@login_required
def get_activity():
    page = request.args.get('page', 1, type=int)
    activity = get_recent_activity(g.user_id, page=page)
    return jsonify(activity)

@app.route("/api/v1/settings/phone", methods=['POST'])
@login_required
def save_phone():
    phone = request.json['phone']
    if not phone:
        return jsonify({"error": "Phone number is required."}), 400
    save_phone_number(g.user_id, phone)
    return jsonify({"status": "success", "phone": phone}), 200

@app.route("/api/v1/settings/notion", methods=['POST'])
@login_required
def save_notion():
    notion_key = request.json.get('notion_key')
    notion_db_id = request.json.get('notion_db_id')
    
    if not notion_key or not notion_db_id:
        return jsonify({"error": "Both Notion Key and Database ID are required."}), 400
        
    save_user_notion_details(g.user_id, notion_key, notion_db_id)
    return jsonify({"status": "success"}), 200

#################################################
# SECTION 4: GOOGLE CALENDAR OAUTH FLOW
#################################################

@app.route("/api/v1/connect/google-calendar-url", methods=['GET'])
@login_required
def get_google_calendar_url():
    state_token = auth.create_custom_token(g.user_id).decode('utf-8')
    session['google_oauth_state'] = state_token

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline', 
        prompt='consent',
        state=state_token
    )
    
    return jsonify({"url": authorization_url})

@app.route("/google-auth-callback-calendar")
def google_auth_callback_calendar():
    state = request.args.get('state')
    
    try:
        decoded_token = auth.verify_id_token(state)
        user_id = decoded_token['uid']
    except Exception as e:
        print(f"Invalid state token in Google callback: {e}")
        return redirect(f"{FRONTEND_URL}/dashboard?error=invalid_state")

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=state,
        redirect_uri=url_for('google_auth_callback_calendar', _external=True)
    )
    
    try:
        flow.fetch_token(authorization_response=request.url)
        refresh_token = flow.credentials.refresh_token
        
        if not refresh_token:
             return redirect(f"{FRONTEND_URL}/dashboard?error=no_refresh_token")

        save_user_google_token(user_id, refresh_token)
        return redirect(f"{FRONTEND_URL}/dashboard?calendar_success=true")
        
    except Exception as e:
        print(f"Error in calendar callback: {e}")
        return redirect(f"{FRONTEND_URL}/dashboard?error=calendar_failed")

if __name__ == "__main__":
    app.run(port=os.environ.get("PORT", 5000), debug=True)