# scheduler.py
import os
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # Using your modern library

from dotenv import load_dotenv
load_dotenv() # Load .env variables

# --- THIS IS THE CRITICAL CHANGE ---
# We import the NEW Firebase helper functions
# We also import 'db' from firebase_helpers to ensure firebase_admin.initialize_app()
# runs first before any other function is called.
from firebase_helpers import (
    get_pending_reminders, 
    mark_reminder_as_sent, 
    db
)
from core_logic import send_whatsapp_message

SLEEP_INTERVAL = 60 # Check for new reminders every 60 seconds

def run_scheduler():
    print(f"[{datetime.now()}] Starting Firebase Reminder Scheduler... (Daemon Mode)")

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            print(f"[{now_utc.isoformat()}] Checking for pending reminders in Firestore...")

            # Get pending reminders from Firestore
            reminders = get_pending_reminders(now_utc)

            if not reminders:
                print("No reminders due right now.")
            else:
                print(f"Found {len(reminders)} reminders to send!")

            for reminder in reminders:
                try:
                    reminder_id = reminder['id']
                    user_id = reminder['user_id']
                    title = reminder['event_title']
                    deadline_utc = reminder['event_deadline_utc']

                    # Firestore returns a Timestamp; convert it to a Python datetime
                    if not isinstance(deadline_utc, datetime):
                         deadline_utc = deadline_utc.to_datetime()

                    # Convert to IST (Asia/Kolkata) for the message
                    ist_tz = ZoneInfo("Asia/Kolkata")
                    deadline_ist = deadline_utc.astimezone(ist_tz)
                    # Format as: 01:30 PM, Nov 05
                    deadline_ist_str = deadline_ist.strftime('%I:%M %p, %b %d') 

                    message = (
                        f"🔔 *REMINDER* 🔔\n\n"
                        f"This is your 1-hour reminder for the event:\n\n"
                        f"*{title}*\n\n"
                        f"It's due at *{deadline_ist_str}* (IST)."
                    )

                    # 1. Send the WhatsApp message
                    send_whatsapp_message(reminder['phone_number'], message)

                    # 2. Mark it as sent in the database
                    #    This *also* logs the activity and updates stats
                    mark_reminder_as_sent(reminder_id, user_id, title)

                    print(f"Successfully sent reminder {reminder_id} to {reminder['phone_number']}")

                except Exception as e:
                    # Log the error for a single failed reminder
                    print(f"Error processing reminder {reminder.get('id', 'unknown')}: {e}")

            print(f"Scheduler sleeping for {SLEEP_INTERVAL} seconds...")
            time.sleep(SLEEP_INTERVAL)

        except Exception as e:
            # This catches a major loop error (e.g., can't connect to DB)
            print(f"Major scheduler loop error: {e}")
            print(f"Sleeping for {SLEEP_INTERVAL} seconds before retrying...")
            time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    run_scheduler()