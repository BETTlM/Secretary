# 🎯 Secretary

**Automatically add deadlines from WhatsApp messages to Google Calendar & Notion.**

Secretary is a remote application that listens for forwarded WhatsApp messages (via the Meta Developer API), extracts deadlines and tasks using AI, and saves them into **Google Calendar**, **Notion**, and a **Supabase** database — so you never miss a deadline.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)  ![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)  ![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)  

---

## 🧠 How it works

1. You forward a WhatsApp message containing a task/deadline.  
2. Secretary receives the message via a Meta Webhook and a Flask server (`app.py`).  
3. It identifies the user in Supabase, then parses the message (via an AI agent) into structured data: title, date/time, priority, notes.  
4. It stores the event in the Supabase `scheduled_events` table.  
5. It creates an event in the user’s Google Calendar and adds a page in their Notion database.  
6. A scheduler (`scheduler.py`) checks for upcoming deadlines and (optionally) sends reminders before the event.  

---

## 🔍 Key Features

- **Natural-language parsing**: Understands text like “Submit report by Friday 3 PM” and extracts structured info.  
- **Two-way sync**: Automatically adds to Google Calendar **and** Notion.  
- **Centralized storage**: Events stored in Supabase for tracking and edge-case handling.  
- **Extensible tech stack**: Modular architecture means you can swap parsing, storage or notification methods.  
- **Webhook-based**: Works with Meta’s WhatsApp Business API/webhook, so you can integrate easily.

---

## 🛠 Tech Stack

- **Backend**: Python + Flask  
- **Database & Auth**: Supabase (PostgreSQL + Auth)  
- **Messaging & Webhook**: Meta Developer API (WhatsApp)  
- **Parsing/NLP**: AI agent (custom or third-party)  
- **Calendar**: Google Calendar API  
- **Knowledge / Notes**: Notion API  
- **Scheduler**: Python script run via cron/GitHub Actions to manage reminders  
- **Frontend** : HTML/Jinja2 + CSS (for dashboard)  

---

## 🚀 Getting Started

### Prerequisites  
- A WhatsApp Business API / Meta webhook set up  
- Google OAuth credentials for Calendar access  
- Notion integration token & database ID  
- A Supabase project with URL & key  
---
### Installation  
```bash
git clone https://github.com/BETTlM/Secretary.git
cd Secretary
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
---
### Configuration
create an `.env` with the following secrets:
```env
FLASK_SECRET_KEY=<your-secret>
SUPABASE_URL=<your-supabase-url>
SUPABASE_KEY=<your-supabase-key>
META_PHONE_NUMBER_ID=<whatsapp-business-phone-id>
META_ACCESS_TOKEN=<meta-access-token>
META_VERIFY_TOKEN=<your-verify-token>
GOOGLE_CLIENT_ID=<google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<google-oauth-client-secret>
NOTION_API_KEY=<notion-integration-token>
NOTION_DATABASE_ID=<notion-db-id>
```
---
## Scheduler Setup

Use a cron or GitHub Actions workflow to run scheduler.py periodically (e.g., every 5 minutes) so deadlines are picked up and processed.

---

