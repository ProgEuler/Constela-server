# 🚀 Constela (Chahira) Backend Architecture & Services Guide

Welcome to the backend repository for **Constela (Chahira)** — a modern dating & social platform powered by **Django 5**, **Django REST Framework (DRF)**, **SimpleJWT**, and **Django Channels (WebSockets)**.

---

## 🛠️ Tech Stack & Platform Services

Here is a breakdown of every third-party platform and service integrated into this backend, along with its specific role and purpose in the application ecosystem:

| Platform / Service | Category | Purpose in Constela App |
| :--- | :--- | :--- |
| **🔥 Firebase (Google Cloud Platform)** | Authentication & Push Notifications | Handles Google Social Sign-In token verification, Android/iOS push notifications (FCM & Expo Push), and app manifest security. |
| **☁️ Cloudflare R2** | Object / Media Storage | High-speed, S3-compatible cloud storage with **$0 Egress (download) fees**. Used to store user profile photos, face verification selfies, and chat attachments without incurring bandwidth bills as the user base grows. |
| **📧 Brevo (Sendinblue)** | Email Service (SMTP) | Delivers branded transactional HTML emails for 6-digit OTP signup codes, password reset links, resend requests, and email changes. |
| **💳 RevenueCat** | Subscription & In-App Payments | Manages premium subscription tiers, in-app purchases (IAP) for iOS App Store & Google Play, entitlements, and real-time backend webhooks. |
| **🤖 OpenCV / Face Detection** | AI Security & Verification | Performs automated face detection on user-uploaded selfies to enforce account authenticity and verification badges. |

---

## 📁 Key Environment Variables (`.env`)

All third-party platform keys are centralized in `backend/.env`. Here is what each variable is for:

```env
# 1. BREVO EMAIL (SMTP) CREDENTIALS
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_brevo_smtp_user
EMAIL_HOST_PASSWORD=your_brevo_smtp_password
DEFAULT_FROM_EMAIL=no-reply@projectyard.top

# 2. CLOUDFLARE R2 MEDIA STORAGE
R2_ACCESS_KEY_ID=your_cloudflare_r2_access_key
R2_SECRET_ACCESS_KEY=your_cloudflare_r2_secret_key
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_BUCKET_NAME=constela

# 3. GOOGLE / FIREBASE OAUTH CREDENTIALS
GOOGLE_CLIENT_ID_WEB=your_google_web_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_ID_IOS=your_google_ios_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_ID_ANDROID=your_google_android_client_id.apps.googleusercontent.com

# 4. REVENUECAT SUBSCRIPTIONS
REVENUECAT_WEBHOOK_SECRET=your_revenuecat_webhook_secret_token

# 5. EXPO PUSH NOTIFICATIONS
EXPO_PUSH_ACCESS_TOKEN=your_expo_push_access_token
```

---

## 🏗️ Architecture Overview

```text
       ┌────────────────────────────────────────────────────────┐
       │                 Mobile App (React Native)              │
       └───────────┬────────────────────────────────┬───────────┘
                   │ HTTP / REST                    │ WebSockets
                   ▼                                ▼
       ┌────────────────────────────────────────────────────────┐
       │             Django 5 Backend API (Uvicorn)             │
       └─────┬──────────────┬──────────────┬──────────────┬─────┘
             │              │              │              │
             ▼              ▼              ▼              ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
       │ Firebase  │  │Cloudflare │  │  Brevo    │  │ Revenue   │
       │ Google    │  │    R2     │  │   SMTP    │  │    Cat    │
       │ Auth/Push │  │  Media    │  │  Emails   │  │ Payments  │
       └───────────┘  └───────────┘  └───────────┘  └───────────┘
```

---

## 🏃 Running The Backend Locally

1. **Activate Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```
2. **Apply Migrations**:
   ```bash
   python manage.py migrate
   ```
3. **Start Development Server**:
   ```bash
   uvicorn core.asgi:application --port 8001 --reload
   ```

---

## 📜 API Documentation
Full endpoint specs, authentication headers, request payloads, and response examples are available in [`API_DOCUMENTATION.md`](./API_DOCUMENTATION.md).
# Constela-server
