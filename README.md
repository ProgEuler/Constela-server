# Constela Backend

This is the backend for the **Constela** dating application, built using Django REST Framework (DRF) for the core API and Django Channels for real-time WebSocket communication. 

The backend is completely container-ready and built to be 100% portable, specifically optimized for seamless deployment on PaaS platforms like **Dokploy**.

---

## 🛠 Tech Stack & Third-Party Services

We utilize several external services to power core features of the app:

### 1. Firebase (Google Cloud)
* **What it does:** Powers both **Google Sign-In** and **Push Notifications (FCM)**.
* **How it works:** We use the `firebase-admin` Python SDK. Instead of mounting a physical credentials file on the server, the backend is configured to read the entire Service Account JSON directly from the `FIREBASE_CREDENTIALS_JSON` environment variable. This allows the backend to verify the cryptographic signatures of Google OAuth tokens and dispatch push notifications securely.

### 2. Cloudflare R2
* **What it does:** High-performance, zero-egress-fee object storage for user media.
* **How it works:** All profile photos and images sent in chat messages are uploaded directly to a Cloudflare R2 bucket (`constela`). We use the standard AWS S3 SDK (boto3/django-storages) configured to point to Cloudflare's S3-compatible endpoints to handle the uploads and serve the media securely.

### 3. RevenueCat
* **What it does:** Manages premium subscriptions and in-app purchases.
* **How it works:** RevenueCat calls `/api/subscription/webhook/`. Authenticated deliveries trigger server-to-server subscriber verification; the app also calls `/api/subscription/sync/` after purchase/restore. Access expires independently of webhook delivery. See [deployment requirements and tests](SUBSCRIPTION_DEPLOYMENT.md) before deploying.

### 4. WebSockets (Django Channels)
* **What it does:** Powers real-time direct messaging between matches.
* **How it works:** Users connect to `wss://<domain>/ws/chat/?token=<jwt_token>`. The backend validates the JWT in real-time and routes messages between clients instantaneously.

### 5. Brevo (Email Delivery)
* **What it does:** Sends highly-deliverable transactional emails (like OTPs and password resets).
* **How it works:** The backend leverages Django's built-in SMTP engine, configured to route through Brevo's SMTP relay servers (`smtp-relay.brevo.com`). This prevents our system emails from bouncing or ending up in the user's spam folder.

---

## 🚀 Deployment (Dokploy & Docker)

> [!NOTE]
> **Active Deployment:** This server is currently deployed and running via **Dokploy** on a VPS (accessible at [https://dokploy.constela-dating.com/](https://dokploy.constela-dating.com/)). All production backend credentials and `.env` variables can be found and managed directly within the Dokploy Environment dashboard on the VPS.

Because all sensitive configurations have been stripped out of the codebase and moved to Environment Variables, deploying the app is incredibly simple.

### Setting up the Environment
You must inject the following variables into your Dokploy (or Docker) Environment UI:

#### Django & Database
* `SECRET_KEY`: Your Django secret key.
* `DEBUG`: Set to `False` in production.
* `ALLOWED_HOSTS`: Your domain (e.g., `api.constela.com`).
* `DATABASE_URL`: A PostgreSQL connection string (e.g., `postgres://user:pass@host:5432/db`). If omitted, the server will fall back to a local SQLite file.

#### Firebase (Authentication & Push Notifications)
* `FIREBASE_CREDENTIALS_JSON`: The **full stringified JSON** of your `firebase-service-account.json` file. 
  *(Example: `{"type": "service_account", "project_id": "...", ...}`)*

#### Cloudflare R2 (Media Storage)
* `R2_ACCESS_KEY_ID`: Cloudflare R2 Access Key.
* `R2_SECRET_ACCESS_KEY`: Cloudflare R2 Secret Key.
* `R2_ENDPOINT_URL`: Your S3-compatible R2 endpoint url.
* `R2_BUCKET_NAME`: The name of your R2 bucket.

#### Email Delivery (Brevo SMTP)
* `EMAIL_HOST`: Your SMTP relay host (usually `smtp-relay.brevo.com`).
* `EMAIL_PORT`: The SMTP port (usually `587`).
* `EMAIL_USE_TLS`: Should be set to `True`.
* `EMAIL_HOST_USER`: Your Brevo SMTP login email.
* `EMAIL_HOST_PASSWORD`: Your Brevo SMTP master password.
* `DEFAULT_FROM_EMAIL`: The default outbound address (e.g., `no-reply@yourdomain.com`).

#### RevenueCat (Subscriptions)
* `REVENUECAT_WEBHOOK_SECRET`: The authorization token set in your RevenueCat webhook dashboard to secure incoming requests.

### Running the Server
Once the environment variables are injected, the server can be started securely using any standard ASGI server (like Uvicorn or Daphne) to support both HTTP and WebSocket traffic:
```bash
uvicorn core.asgi:application --host 0.0.0.0 --port 8000
```
