# Competitor Intelligence & Price/Schedule Monitoring Pipeline
> **Automated Monitoring Service for Impact Fitness Studio (Akash)**  
> **Tech Stack:** Changedetection.io, Python, Apprise, Next.js / Supabase ready  
> **License:** Apache 2.0 (Keep `LICENSE` file intact for redistribution / white-labeling)

---

## 1. Quick Start & Architecture Overview

This pipeline monitors competitor gyms and fitness studios in Bengaluru (Indiranagar / Koramangala / nearby) to track changes in:
- **Pricing structures** (quarterly passes, annual plans, personal training add-ons)
- **Class schedules & batches** (morning/evening slots, new HIIT/CrossFit batches)
- **New promotional offerings & seasonal discounts**

### Running Changedetection.io

#### Option A: Native Local Run (Already configured & active on port 5000)
Run inside the project root:
```powershell
.\changedetection-env\Scripts\changedetection.io.exe -p 5000 -d changedetection-data -h 127.0.0.1
```
Open **`http://127.0.0.1:5000`** in your browser.

#### Option B: Docker (When Docker is installed)
```bash
docker run -d --name changedetection \
  -p 5000:5000 \
  -v ${PWD}/changedetection-data:/datastore \
  --restart unless-stopped \
  dgtlmoon/changedetection.io
```

---

## 2. Currently Monitored Competitors

The following live competitors near Impact Fitness Studio are currently configured in your local datastore with targeted CSS selectors:

| Competitor Gym | Target URL | Tracked Scope | CSS Selector |
| :--- | :--- | :--- | :--- |
| **Academy of Strength (Indiranagar)** | `https://www.academyofstrength.in/` | In-Center & Online Batch Schedules | `#comp-l6oxx6yc` |
| **Chisel Fitness (Bengaluru)** | `https://chisel.co.in/` | Programs, Offerings & Services | `#section-7HirWN3kG` |
| **The Tribe Fitness Club (Indiranagar)** | `https://thetribefitness.com/` | Main Classes & Programs Container | `main#PAGES_CONTAINER` |

---

## 3. How to Add a Watch with CSS/XPath Selectors

Tracking an entire webpage produces noise (footer copyright year changes, dynamic testimonials, cookie notices). Use CSS or XPath selectors to restrict monitoring to the exact pricing card or schedule grid.

### Method 1: Via the Web UI (`http://127.0.0.1:5000`)
1. On the home page, enter the competitor URL in the top box and click **Watch**.
2. Click **Edit** next to the newly created watch.
3. Switch to the **Filters & Triggers** tab.
4. Under **CSS/XPath Filters**, enter your selector:
   - For CSS ID: `#pricing-table` or `section.batch-schedule`
   - For XPath: `//section[@id='comp-l6oxx6yc']` or `//div[contains(@class, 'pricing-card')]`
5. *(Optional)* Under **Subtractive Selectors**, remove elements like timestamps or badges:
   - Example: `.last-updated, .announcement-banner`
6. Click **Save**.

### Method 2: Via the REST API
You can automate adding watches programmatically using the REST API:

```python
import urllib.request
import json

API_KEY = "b81f1afddc963552f17a20150ddb7ab0"  # Found in Settings -> API

payload = {
    "url": "https://www.academyofstrength.in/",
    "title": "Academy of Strength - Batch Schedule",
    "tag": "competitor-gyms",
    "include_filters": ["#comp-l6oxx6yc"]
}

req = urllib.request.Request(
    "http://127.0.0.1:5000/api/v1/watch",
    data=json.dumps(payload).encode("utf-8"),
    headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
    method="POST"
)

with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
```

---

## 4. Notification Setup (Email & Webhook)

Changedetection uses **Apprise** syntax for multi-channel alerting.

### Step 1: Open Notification Settings
Go to `http://127.0.0.1:5000/settings#notifications` (or click **Edit > Notifications** on an individual watch).

### Step 2: Configure Notification URLs

#### For Email Alerting (SMTP / Gmail / SendGrid):
```text
mailto://your_email@gmail.com:your_app_password@smtp.gmail.com:587?to=you@domain.com
```

#### For Webhook Integration (Next.js / Supabase / Slack):
```text
json://http://localhost:3000/api/webhooks/changedetection
```
*(Or for Discord / Slack)*:
```text
slack://TokenA/TokenB/TokenC
discord://WebhookID/WebhookToken
```

### Step 3: Notification Template Tokens
Paste this custom template into **Notification Body**:

```jinja2
🚨 COMPETITOR CHANGE ALERT: {{watch_title}}
URL: {{watch_url}}
Diff View: {{diff_url}}

--- DETECTED CHANGES ---
{{diff}}
-----------------------
```

**Key Available Tokens:**
- `{{watch_title}}`: Name/Title of the gym
- `{{watch_url}}`: Competitor webpage URL
- `{{diff}}`: Formatted diff showing `(added)`, `(removed)`, `(changed)` lines
- `{{diff_patch}}`: Standard git-style unified diff (`+`, `-`)
- `{{diff_url}}`: Direct link to visual comparison page in Changedetection

---

## 5. Client Summary Generator (`competitor_diff_summary.py`)

Akash does not want to read raw HTML diffs or git-style code patches. `competitor_diff_summary.py` automatically parses diffs, classifies lines into **Pricing Changes**, **Schedule Changes**, and **Program Additions**, and produces an executive plain-English brief.

### Usage Commands:

#### 1. Live Intelligence Check (Current Tracked Gyms):
```powershell
.\changedetection-env\Scripts\python.exe competitor_diff_summary.py
```

#### 2. Client Proof Simulation (For instant demo with Akash):
```powershell
.\changedetection-env\Scripts\python.exe competitor_diff_summary.py --simulate
```
*Outputs a realistic price drop and morning slot addition to show Akash exactly what the service delivers before waiting for live site edits.*

#### 3. JSON Output (To feed into Next.js / Supabase):
```powershell
.\changedetection-env\Scripts\python.exe competitor_diff_summary.py --json
```

---

## 6. Real-World Gotchas & How to Handle Them

### Gotcha 1: Dynamic / Client-Side Rendered (CSR) SPAs
- **The Issue:** Many modern gym websites (built on Wix, Squarespace, React, Next.js) load schedule tables and pricing cards via JavaScript after initial HTML load. A basic HTTP client (`html_requests`) only sees the empty shell or loading skeleton.
- **The Solution:**
  1. For local Docker deployment, attach a browserless container:
     ```yaml
     services:
       changedetection:
         image: dgtlmoon/changedetection.io
         environment:
           - PLAYWRIGHT_DRIVER_URL=ws://playwright-chrome:3000
       playwright-chrome:
         image: browserless/chrome
     ```
  2. In Changedetection Settings -> **Requests**, set **Fetch Backend** to `Playwright Chrome`.
  3. Set a **Render Delay** (e.g. 3-5 seconds) under watch settings to allow dynamic pricing calculators to fully hydrate before taking the snapshot.

### Gotcha 2: Rate Limiting & 429 Too Many Requests
- **The Issue:** Aggressive rechecks trigger HTTP 429 errors or IP bans (we saw this when querying Wix-hosted sites in tight loops).
- **The Solution:**
  - Gym pricing and schedules rarely change more than once a week. Set **Time Between Check** to **6 to 24 hours** (not every 5 minutes).
  - Enable **Jitter** in settings (e.g. ±15% randomness) so requests don't hit the competitor's server at the exact same second each day.

### Gotcha 3: Anti-Bot, WAFs & Cloudflare
- **The Issue:** Cloudflare or AWS WAF blocks default Python/cURL user-agents.
- **The Solution:**
  - In Changedetection -> **Settings -> Requests -> Extra Headers**, set a standard desktop browser User-Agent:
    ```text
    User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36
    ```
  - For sites with heavy anti-bot protections, Changedetection supports residential/datacenter proxies under **Settings -> Proxies**.

---

## 7. Next.js & Supabase Integration Blueprint

To turn this into a recurring paid dashboard service (₹X setup + ₹X/month):
1. **Webhook Ingestion:** In your Next.js app, add `app/api/webhooks/competitor-diff/route.ts` listening for POST requests from Changedetection (`json://`).
2. **Supabase Schema:** Store alerts in a table:
   ```sql
   create table competitor_alerts (
     id uuid primary key default gen_random_uuid(),
     competitor_name text not null,
     competitor_url text not null,
     change_type text check (change_type in ('pricing', 'schedule', 'program')),
     summary_text text not null,
     detected_at timestamp with time zone default now()
   );
   ```
3. **Client UI:** Akash logs in to view his live competitor feed alongside his Impact Fitness Studio metrics.
