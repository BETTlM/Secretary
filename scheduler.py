import os
import time
from datetime import datetime, timezone

# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

# Import our helper functions
from supabase_helpers import get_pending_reminders, mark_reminder_as_sent
from core_logic import send_whatsapp_message

# How often the scheduler wakes up to check for reminders (in seconds)
SLEEP_INTERVAL = 60 

def run_scheduler():
    print("Starting reminder scheduler...")
    while True:
        try:
            # 1. Get current time in UTC
            now_utc = datetime.now(timezone.utc)
            
            # 2. Check the database for any reminders that are due
            print(f"[{now_utc.isoformat()}] Checking for pending reminders...")
            reminders = get_pending_reminders(now_utc)
            
            if not reminders:
                print("No reminders due right now.")
            else:
                print(f"Found {len(reminders)} reminders to send!")
            
            # 3. Process each reminder
            for reminder in reminders:
                try:
                    # Format the deadline to the user's local time (approximated)
                    # This is a complex problem, but we can make a good guess.
                    # For a true SaaS, you'd store the user's timezone.
                    # For now, we'll just show the UTC time.
                    deadline_str = reminder['event_deadline_utc']
                    
                    # Create the reminder message
                    message = (
                        f"🔔 *REMINDER* 🔔\n\n"
                        f"This is a 1-hour reminder for your event:\n\n"
                        f"*{reminder['event_title']}*\n\n"
                        f"It's due at *{deadline_str}* (UTC)."
                    )
                    
                    # 4. Send the WhatsApp message
                    send_whatsapp_message(reminder['phone_number'], message)
                    
                    # 5. Mark it as sent in the database
                    mark_reminder_as_sent(reminder['id'])
                    
                    print(f"Successfully sent reminder {reminder['id']} to {reminder['phone_number']}")
                
                except Exception as e:
                    print(f"Error processing reminder {reminder['id']}: {e}")

            # 6. Go to sleep
            print(f"Scheduler sleeping for {SLEEP_INTERVAL} seconds...")
            time.sleep(SLEEP_INTERVAL)

        except Exception as e:
            print(f"Major scheduler loop error: {e}")
            # Don't crash the whole scheduler, just wait and try again
            time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    run_scheduler()