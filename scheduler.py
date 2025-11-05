import os
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

from supabase_helpers import get_pending_reminders, mark_reminder_as_sent
from core_logic import send_whatsapp_message

SLEEP_INTERVAL = 60 

def run_scheduler():
    print("Starting reminder scheduler...")
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            print(f"[{now_utc.isoformat()}] Checking for pending reminders...")
            reminders = get_pending_reminders(now_utc)
            
            if not reminders:
                print("No reminders due right now.")
            else:
                print(f"Found {len(reminders)} reminders to send!")
            for reminder in reminders:
                try:
                    deadline_str = reminder['event_deadline_utc']
                    deadline_utc = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))

                    ist_tz = ZoneInfo("Asia/Kolkata")
                    deadline_ist = deadline_utc.astimezone(ist_tz)
                    deadline_ist_str = deadline_ist.strftime('%Y-%m-%d %H:%M')
                    
                    message = (
                        f"🔔 *REMINDER* 🔔\n\n"
                        f"This is a 1-hour reminder for your event:\n\n"
                        f"*{reminder['event_title']}*\n\n"
                        f"It's due at *{deadline_ist_str}* (IST)."
                    )
                    send_whatsapp_message(reminder['phone_number'], message)
                    mark_reminder_as_sent(reminder['id'])
                    print(f"Successfully sent reminder {reminder['id']} to {reminder['phone_number']}")
                except Exception as e:
                    print(f"Error processing reminder {reminder['id']}: {e}")

            print(f"Scheduler sleeping for {SLEEP_INTERVAL} seconds...")
            time.sleep(SLEEP_INTERVAL)

        except Exception as e:
            print(f"Major scheduler loop error: {e}")
            time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    run_scheduler()