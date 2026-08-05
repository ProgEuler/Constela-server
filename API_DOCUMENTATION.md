# Chahira — Complete API Documentation

> **Base URL:** `http://127.0.0.1:8000/api`
>
> **Authentication:** All endpoints (except Auth) require a Bearer token.
> ```
> Authorization: Bearer <access_token>
> ```

---

# 📁 1. Auth

All endpoints in this section are **public** (no token required), except `face-verify` and `profile onboarding`.

---

### 1.1 Sign Up

Creates a new user account and sends an OTP to the provided email.

| Property | Value |
|---|---|
| **URL** | `/api/auth/signup/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPassword123!"
}
```

**Success Response (201):**
```json
{
  "message": "Registration successful. OTP sent to email.",
  "email": "user@example.com"
}
```

**Error Response (400):**
```json
{
  "email": ["user with this email already exists."]
}
```

---

### 1.2 Verify OTP

Verifies the OTP sent to the user's email. On success, activates the account and returns JWT tokens.

| Property | Value |
|---|---|
| **URL** | `/api/auth/verify-otp/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "email": "user@example.com",
  "otp": "9394"
}
```

**Success Response (200):**
```json
{
  "message": "OTP verification successful.",
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs...",
  "role": "member"
}
```

> ⚠️ **Important:** Store both `access` and `refresh` tokens securely. The `access` token is used for all subsequent API calls. The `refresh` token is used to get a new `access` token when it expires.

**Error Response (400):**
```json
{
  "error": "Invalid OTP or email."
}
```

---

### 1.3 Sign In (Login)

Authenticates a user and returns JWT tokens.

| Property | Value |
|---|---|
| **URL** | `/api/auth/login/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPassword123!"
}
```

**Success Response (200):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Error Response (401):**
```json
{
  "detail": "No active account found with the given credentials"
}
```

---

### 1.4 Token Refresh

Gets a new access token using the refresh token.

| Property | Value |
|---|---|
| **URL** | `/api/auth/token/refresh/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Success Response (200):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIs..."
}
```

---

### 1.5 Check Username Availability

Checks if a username is already taken. Used during profile onboarding.

| Property | Value |
|---|---|
| **URL** | `/api/auth/check-username/?username=<username>` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ❌ None |

**Query Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `username` | string | ✅ | The username to check (3-30 chars) |

**Success Response (200) — Available:**
```json
{
  "available": true,
  "message": "Username is available."
}
```

**Success Response (200) — Taken:**
```json
{
  "available": false,
  "message": "Username is already taken."
}
```

---

### 1.6 Forgot Password

Sends a 6-digit reset code to the user's email.

| Property | Value |
|---|---|
| **URL** | `/api/auth/forgot-password/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Success Response (200):**
```json
{
  "message": "If the account exists, a reset code has been sent."
}
```

> Note: Always returns 200 to prevent email enumeration.

---

### 1.7 Reset Password

Verifies the reset code and updates the password.

| Property | Value |
|---|---|
| **URL** | `/api/auth/reset-password/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ❌ None |

**Request Body:**
```json
{
  "email": "user@example.com",
  "code": "824796",
  "new_password": "NewSuperPassword123!"
}
```

**Success Response (200):**
```json
{
  "message": "Password has been reset successfully."
}
```

**Error Response (400):**
```json
{
  "error": "Invalid email or verification code."
}
```

---

### 1.8 Profile Onboarding (Create/Update Profile)

Consolidated endpoint to submit all onboarding steps AND upload profile photos simultaneously. This is a **multipart/form-data** request.

| Property | Value |
|---|---|
| **URL** | `/api/profile/me/` |
| **Method** | `PUT` or `PATCH` |
| **Content-Type** | `multipart/form-data` |
| **Auth** | ✅ Bearer Token |

**Form Data Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | text | ✅ | Display name (3-30 chars) |
| `age` | text | ✅ | User's age |
| `height_cm` | text | ❌ | Height in centimeters |
| `weight_kg` | text | ❌ | Weight in kilograms |
| `gender` | text | ✅ | `man`, `woman`, `non_binary` |
| `marital_status` | text | ❌ | `single`, `divorced`, `widowed`, `separated`, `married` |
| `education_level` | text | ❌ | `below`, `bachelor`, `master`, `phd` |
| `spoken_languages` | text | ❌ | Comma-separated: `"English, ASL"` or JSON: `["English", "ASL"]` |
| `city` | text | ❌ | City name |
| `country` | text | ❌ | Country name |
| `latitude` | text | ❌ | GPS latitude (float) |
| `longitude` | text | ❌ | GPS longitude (float) |
| `looking_for` | text | ❌ | `serious`, `friendship`, `casual`, `undecided` |
| `has_children` | text | ❌ | `true` / `false` |
| `wants_children` | text | ❌ | `true` / `false` |
| `smoking` | text | ❌ | `true` / `false` |
| `alcohol` | text | ❌ | `true` / `false` |
| `pets` | text | ❌ | `true` / `false` |
| `sport` | text | ❌ | `No Sport`, `Moderate`, `Intense` |
| `eating_habits` | text | ❌ | `Balanced`, `Vegetarian`, `Vegan`, etc. |
| `second_degree_humor` | text | ❌ | `true` / `false` |
| `qualities` | text | ❌ | JSON array: `["Authenticity", "Loyalty"]` |
| `interests` | text | ❌ | Comma-separated: `"Coding, Math"` or JSON array |
| `recharge_methods` | text | ❌ | Comma-separated or JSON array |
| `exhaust_triggers` | text | ❌ | JSON array: `["Bright lights", "Loud noises"]` |
| `emotional_needs` | text | ❌ | JSON array: `["Predictability", "Clear communication"]` |
| `soothe_methods` | text | ❌ | JSON array |
| `neurotype_labels` | text | ❌ | JSON array: `["ADHD", "Autism"]` |
| `photo1` | file | ❌ | First profile photo (image file) |
| `photo2` | file | ❌ | Second profile photo (image file) |
| `photo3` | file | ❌ | Third profile photo (image file) |

> **Note on list fields:** `qualities`, `interests`, `recharge_methods`, `exhaust_triggers`, `emotional_needs`, `soothe_methods`, `spoken_languages`, `neurotype_labels` accept either:
> - A JSON array string: `["item1", "item2"]`
> - A comma-separated string: `"item1, item2"`

**Success Response (200):**
Returns the full updated profile object (see `GET /api/profile/me/` response below).

---

### 1.9 Get My Profile

Returns the authenticated user's full profile data.

| Property | Value |
|---|---|
| **URL** | `/api/profile/me/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
{
  "id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
  "user": {
    "id": "a1b2c3d4-...",
    "email": "user@example.com",
    "role": "member"
  },
  "username": "SamWander",
  "age": 25,
  "height_cm": 175,
  "weight_kg": 70,
  "gender": "woman",
  "marital_status": "single",
  "education_level": "bachelor",
  "spoken_languages": ["English", "ASL"],
  "city": "London",
  "country": "UK",
  "latitude": 51.5074,
  "longitude": -0.1278,
  "looking_for": "friendship",
  "has_children": false,
  "wants_children": false,
  "smoking": false,
  "alcohol": false,
  "pets": true,
  "sport": "Moderate",
  "eating_habits": "Balanced",
  "second_degree_humor": true,
  "neurotype_labels": ["ADHD"],
  "qualities": ["Authenticity", "Loyalty", "Reliability"],
  "interests": ["Coding", "Math", "Patterns"],
  "recharge_methods": ["Silence", "Cocoon Spaces"],
  "exhaust_triggers": ["Bright lights", "Loud noises"],
  "emotional_needs": ["Predictability", "Clear communication"],
  "soothe_methods": ["Silence or soft sounds", "Chosen solitude"],
  "subscription_tier": "freemium",
  "subscription_expires": null,
  "is_verified": true,
  "is_deactivated": false,
  "profile_completion_pct": 85,
  "face_verification_status": "none",
  "photos": [
    {
      "id": "c5d6e7f8-...",
      "image": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/...",
      "is_main": true,
      "is_verified": false,
      "uploaded_at": "2026-06-27T08:00:00Z"
    }
  ]
}
```

---

### 1.10 Face Verify (Selfie Submission)

Uploads a selfie for face verification. The backend validates the image and marks the profile as "pending" admin review.

| Property | Value |
|---|---|
| **URL** | `/api/auth/face-verify/` |
| **Method** | `POST` |
| **Content-Type** | `multipart/form-data` |
| **Auth** | ✅ Bearer Token |

**Form Data Fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `selfie` | file | ✅ | Image file (JPEG, PNG, WebP, HEIC). Max 10 MB. |

**Success Response (200):**
```json
{
  "status": "pending",
  "message": "Selfie submitted successfully. Your face verification is pending review."
}
```

**Error Responses:**
```json
// 400 — No file
{ "error": "No selfie image provided. Send the image under the key 'selfie'." }

// 400 — Invalid image
{ "error": "Invalid image file. Please send a valid JPEG, PNG, WebP, or HEIC photo." }

// 400 — Too large
{ "error": "Image too large. Maximum size is 10 MB." }
```

---

# 📁 2. Matches (Dating)

All endpoints require Bearer token authentication.

---

### 2.1 Perfect Match (Discover Cards)

Returns compatible profiles sorted by compatibility score. Supports basic and advanced filters. This powers the main "swipe card" screen.

| Property | Value |
|---|---|
| **URL** | `/api/matching/perfect-match/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Query Parameters (all optional):**

| Param | Type | Tier | Description |
|---|---|---|---|
| `age_min` | int | Free | Minimum age |
| `age_max` | int | Free | Maximum age |
| `gender` | string | Free | `man`, `woman`, `non_binary` (comma-separated for multiple) |
| `height_min` | int | Free | Min height in cm |
| `height_max` | int | Free | Max height in cm |
| `marital_status` | string | Free | `single`, `divorced`, `widowed`, `separated`, `married` (comma-separated) |
| `city` | string | Free | City name (partial match) |
| `country` | string | Free | Country name (partial match) |
| `looking_for` | string | Free | `serious`, `friendship`, `casual`, `undecided` (comma-separated) |
| `spoken_languages` | string | Free | Comma-separated language names |
| `distance_max` | float | Free | Max distance in km (requires user lat/lng set) |
| `neurotype` | string | Free | Comma-separated neurotype labels |
| `education_level` | string | 💎 Premium | `below`, `bachelor`, `master`, `phd` |
| `smoking` | bool | 💎 Premium | `true` / `false` |
| `alcohol` | bool | 💎 Premium | `true` / `false` |
| `pets` | bool | 💎 Premium | `true` / `false` |
| `sport` | string | 💎 Premium | `No Sport`, `Moderate`, `Intense` |
| `eating_habits` | string | 💎 Premium | e.g. `Balanced` |
| `second_degree_humor` | bool | 💎 Premium | `true` / `false` |
| `interests` | string | 💎 Premium | Comma-separated |
| `emotional_needs` | string | 💎 Premium | Comma-separated |
| `soothe_methods` | string | 💎 Premium | Comma-separated |
| `recharge_methods` | string | 💎 Premium | Comma-separated |
| `exhaust_triggers` | string | 💎 Premium | Comma-separated |

**Success Response (200):**
```json
[
  {
    "id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "username": "Sam",
    "age": 28,
    "gender": "woman",
    "city": "Sydney",
    "country": "Australia",
    "bio": "Authenticity • Loves coding, math, patterns, and random fact",
    "tags": ["Authenticity", "Loyalty"],
    "photo": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/seed_sam",
    "compatibility_score": 87,
    "distance": 12.4
  }
]
```

> `distance` is `null` if either user has no coordinates set.

**Error Response (403) — Freemium using premium filters:**
```json
{
  "error": "Upgrade to Premium to access advanced filters like Education, Lifestyle, and Sensory Profile preferences."
}
```

---

### 2.2 Card Swipe (Like / Dislike)

Records a like or dislike action on a profile card. If both users have liked each other, a mutual match is created.

| Property | Value |
|---|---|
| **URL** | `/api/matching/<target_profile_uuid>/action/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "action": "liked"
}
```
> Valid values: `"liked"` (swipe right) or `"disliked"` (swipe left)

**Success Response (200):**
```json
{
  "status": "liked",
  "is_mutual_match": false
}
```

**Success Response (200) — Mutual Match:**
```json
{
  "status": "matched",
  "is_mutual_match": true
}
```

**Error Response (403) — Daily limit reached:**
```json
{ "error": "Daily like limit (20) reached. Upgrade to Premium for more." }
```

> **Daily Like Limits:**
> | Tier | Limit |
> |---|---|
> | Freemium | 20 likes/day |
> | Light | 50 likes/day |
> | Plus | Unlimited |

---

### 2.3 Get Profile Details

View another user's full profile (used when tapping a card or a match).

| Property | Value |
|---|---|
| **URL** | `/api/profiles/<profile_uuid>/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
Returns the full `UserProfile` object (same shape as `GET /api/profile/me/` response).

---

### 2.4 Save Profile (Bookmark)

Saves a profile to your bookmarked/saved list.

| Property | Value |
|---|---|
| **URL** | `/api/matching/<target_profile_uuid>/save/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{
  "message": "Profile saved successfully.",
  "target_profile_id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d"
}
```

---

### 2.5 Unsave Profile

Removes a profile from your saved list.

| Property | Value |
|---|---|
| **URL** | `/api/matching/<target_profile_uuid>/unsave/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{
  "message": "Profile unsaved successfully.",
  "target_profile_id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d"
}
```

---

### 2.6 List Saved Matches

Returns all profiles you have bookmarked.

| Property | Value |
|---|---|
| **URL** | `/api/matching/saved/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "a1b2c3d4-...",
    "user": "b14dc0b9-...",
    "target_profile": "d67fcd1d-...",
    "created_at": "2026-06-27T10:00:00Z"
  }
]
```

---

### 2.7 Your Mutual Matches

Returns all profiles you've mutually matched with (both liked each other). These are your active dating connections.

| Property | Value |
|---|---|
| **URL** | `/api/matching/matches/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "match_id": "e6b0dae3-...",
    "matched_at": "2026-06-27T09:00:00Z",
    "profile": {
      "id": "b14dc0b9-...",
      "username": "Sam",
      "age": 28,
      "gender": "woman",
      "city": "Sydney",
      "country": "Australia",
      "subscription_tier": "plus",
      "neurotype_labels": ["ADHD"],
      "qualities": ["Authenticity"],
      "interests": ["Coding"],
      "recharge_methods": ["Silence"],
      "soothe_methods": ["Chosen solitude"],
      "sport": "Moderate",
      "spoken_languages": ["English"],
      "is_verified": true,
      "photos": [
        {
          "id": "c5d6e7f8-...",
          "image": "https://res.cloudinary.com/...",
          "is_main": true,
          "is_verified": false,
          "uploaded_at": "2026-06-27T08:00:00Z"
        }
      ]
    }
  }
]
```

---

### 2.8 Likes Sent

Returns all profiles you've liked (and whether they matched back).

| Property | Value |
|---|---|
| **URL** | `/api/matching/likes-sent/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "profile": { "id": "...", "username": "Sam", "..." : "..." },
    "status": "SENT",
    "created_at": "2026-06-27T10:00:00Z"
  },
  {
    "profile": { "id": "...", "username": "Elena", "..." : "..." },
    "status": "MATCHED",
    "created_at": "2026-06-27T09:00:00Z"
  }
]
```

---

### 2.9 Likes Received

Returns profiles who liked you. **💎 Premium only.**

| Property | Value |
|---|---|
| **URL** | `/api/matching/likes-received/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
Returns an array of `UserProfileBasic` objects (same shape as `profile` in mutual matches).

**Error Response (403):**
```json
{ "error": "Upgrade to Premium to see who liked you." }
```

---

### 2.10 Report User

Reports a user for misconduct.

| Property | Value |
|---|---|
| **URL** | `/api/reports/create/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "reported_user": "<target_profile_uuid>",
  "reason": "fake_profile",
  "description": "Optional extra details"
}
```

> **Valid reasons:** `fake_profile`, `offensive_language`, `harassment`, `sexually_explicit_content`, `impersonation`, `other`

**Success Response (201):**
```json
{
  "id": "a1b2c3d4-...",
  "reporter": "my-profile-uuid",
  "reported_user": "<target_profile_uuid>",
  "reason": "fake_profile",
  "description": "Optional extra details",
  "status": "pending",
  "created_at": "2026-06-27T10:00:00Z"
}
```

---

### 2.11 Block User

Blocks a user. Also removes any existing match and friendship with them.

| Property | Value |
|---|---|
| **URL** | `/api/blocks/<target_profile_uuid>/block/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (201):**
```json
{ "message": "Sam has been blocked." }
```

---

### 2.12 Unblock User

| Property | Value |
|---|---|
| **URL** | `/api/blocks/<target_profile_uuid>/block/` |
| **Method** | `DELETE` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
{ "message": "Sam has been unblocked." }
```

---

### 2.13 List Blocked Users

| Property | Value |
|---|---|
| **URL** | `/api/blocks/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "block_id": "a1b2c3d4-...",
    "profile_id": "b14dc0b9-...",
    "username": "Sam",
    "blocked_at": "2026-06-27T10:00:00Z"
  }
]
```

---

### 2.14 Check Block Status

| Property | Value |
|---|---|
| **URL** | `/api/blocks/<target_profile_uuid>/status/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
{
  "profile_id": "b14dc0b9-...",
  "is_blocked": true
}
```

---

# 📁 3. Friends

All endpoints require Bearer token authentication.

---

### 3.1 Friend Suggestions

Returns a list of suggested profiles to send friend requests to. Excludes blocked users and existing friends.

| Property | Value |
|---|---|
| **URL** | `/api/friends/suggestions/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Query Parameters (all optional):**
| Param | Type | Description |
|---|---|---|
| `search` | string | Search by username |
| `age_min` | int | Minimum age |
| `age_max` | int | Maximum age |
| `gender` | string | `man`, `woman`, `non_binary` (comma-separated) |

**Success Response (200):**
```json
[
  {
    "id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "username": "Sam",
    "age": 28,
    "tags": ["Authenticity", "Coding"],
    "bio": "Loves coding, math, and patterns",
    "photo": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/seed_sam"
  }
]
```

---

### 3.2 Pending Friend Requests (Incoming)

Returns friend requests you've received that are awaiting your response.

| Property | Value |
|---|---|
| **URL** | `/api/friends/requests/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da",
    "sender_id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "username": "Sam",
    "photo": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/seed_sam",
    "subtitle": "2 mutual friends • Sydney",
    "mutual_friends_count": 2,
    "location": "Sydney"
  }
]
```

> The `id` field is the **friendship ID**, used for accepting/declining.

---

### 3.3 Send Friend Request

Sends a friend request to another user.

| Property | Value |
|---|---|
| **URL** | `/api/friends/send_request/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "user_id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d"
}
```

> `user_id` is the **profile UUID** (not the auth user UUID).

**Success Response (201):**
```json
{ "message": "Request sent." }
```

**Error Response (400):**
```json
{ "error": "Blocked." }
```

---

### 3.4 Accept Friend Request

| Property | Value |
|---|---|
| **URL** | `/api/friends/<friendship_id>/accept/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{ "message": "Friend request accepted." }
```

**Error Response (403):**
```json
{ "error": "Unauthorized." }
```

---

### 3.5 Decline Friend Request

| Property | Value |
|---|---|
| **URL** | `/api/friends/<friendship_id>/decline/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{ "message": "Friend request declined." }
```

---

# 📁 4. Community (Chat Rooms)

All endpoints require Bearer token authentication. **💎 Premium only** — Freemium users get a 403.

---

### 4.1 List Community Rooms

Returns all available community chat rooms.

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "7ea0139d-7fc5-431c-9a46-db267816566f",
    "name": "ADHD Hub",
    "member_count": 1200,
    "member_avatars": [
      "https://res.cloudinary.com/.../seed_sam",
      "https://res.cloudinary.com/.../seed_alex",
      "https://res.cloudinary.com/.../seed_sophie"
    ],
    "is_joined": false
  }
]
```

> `member_avatars` contains up to 3 Cloudinary URLs for the overlapping avatar circles on the UI card.

**Error Response (403):**
```json
{ "error": "Upgrade to Premium to access Community Chat Rooms." }
```

---

### 4.2 Search Community Rooms

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/?search=<query>` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Query Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `search` | string | ✅ | Search by room name or description |

**Success Response (200):**
Same shape as "List Community Rooms".

---

### 4.3 Join Room

Adds the current user to a room's member list.

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/<room_uuid>/join/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{
  "message": "Successfully joined ADHD Hub.",
  "room_id": "7ea0139d-7fc5-431c-9a46-db267816566f",
  "member_count": 1201
}
```

---

### 4.4 Leave Room

Removes the current user from a room's member list.

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/<room_uuid>/leave/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{
  "message": "Successfully left ADHD Hub.",
  "room_id": "7ea0139d-7fc5-431c-9a46-db267816566f",
  "member_count": 1199
}
```

---

### 4.5 Get Room Chat Messages

Retrieves the latest 50 messages in a room, ordered chronologically (oldest first).

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/<room_uuid>/messages/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "69705bb7-1a3a-4ff6-a16f-2c0c61fcc109",
    "room": "7ea0139d-7fc5-431c-9a46-db267816566f",
    "sender": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "sender_name": "Samantha",
    "sender_photo": "https://res.cloudinary.com/.../seed_sam",
    "content": "Hi @Nico Alexis I'm very excited to start working on this project.",
    "timestamp": "2026-06-27T13:45:00.000000Z"
  },
  {
    "id": "12844e81-5a7d-4bd5-87b9-07809082eadb",
    "room": "7ea0139d-7fc5-431c-9a46-db267816566f",
    "sender": "66cc7492-7e8e-4387-a11d-bc77a75a440d",
    "sender_name": "Nico Alexis",
    "sender_photo": "https://res.cloudinary.com/.../seed_nico",
    "content": "Of course, thank you for joining 🤩",
    "timestamp": "2026-06-27T13:50:00.000000Z"
  }
]
```

> Use the `timestamp` field on the frontend to group messages under date headers like "Yesterday" or "Today".

---

### 4.6 Send Message to Room

Posts a new message to a community chat room. **The user must have joined the room first.**

| Property | Value |
|---|---|
| **URL** | `/api/chat/rooms/<room_uuid>/send/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "content": "I like this approach 👍"
}
```

**Success Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "room": "7ea0139d-7fc5-431c-9a46-db267816566f",
  "sender": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
  "sender_name": "Samantha",
  "sender_photo": "https://res.cloudinary.com/.../seed_sam",
  "content": "I like this approach 👍",
  "timestamp": "2026-06-27T14:50:00.000000Z"
}
```

**Error Responses:**
```json
// 403 — Not a member
{ "error": "You must join this room before you can send messages." }

// 400 — Empty message
{ "error": "Content required." }
```

---

# 📁 5. Messages (Direct Messaging)

All endpoints require Bearer token authentication.

---

### 5.1 Dating Threads (Inbox)

Returns all your mutual matches as message threads, sorted by most recent message.

| Property | Value |
|---|---|
| **URL** | `/api/messages/threads/?type=dating` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Query Parameters:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | string | ❌ | `dating` | `dating` or `friends` |

**Success Response (200):**
```json
[
  {
    "profile": {
      "id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
      "username": "Sam",
      "photo": "https://res.cloudinary.com/.../seed_sam"
    },
    "last_message": "That sounds like a great plan!",
    "last_message_time": "2026-06-27T10:45:00.000000Z",
    "unread_count": 1
  },
  {
    "profile": {
      "id": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da",
      "username": "David",
      "photo": "https://res.cloudinary.com/.../seed_david"
    },
    "last_message": "You've matched! Say hi.",
    "last_message_time": "2026-06-26T09:00:00.000000Z",
    "unread_count": 0
  }
]
```

> If no messages exist yet, `last_message` defaults to `"You've matched! Say hi."` for dating or `"You are now friends! Say hi."` for friends.

---

### 5.2 Friends Threads (Inbox)

Returns all your accepted friends as message threads.

| Property | Value |
|---|---|
| **URL** | `/api/messages/threads/?type=friends` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
Same shape as Dating Threads. `last_message` defaults to `"You are now friends! Say hi."` when no messages exist.

---

### 5.3 Get Conversation History (Direct Messages)

Retrieves the full message history between you and another user. Also marks all incoming unread messages as read.

| Property | Value |
|---|---|
| **URL** | `/api/chat/direct/history/<recipient_profile_id>/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "a1b2c3d4-...",
    "sender": "b14dc0b9-...",
    "receiver": "d67fcd1d-...",
    "sender_name": "Sam",
    "receiver_name": "David",
    "sender_photo": "https://res.cloudinary.com/.../seed_sam",
    "receiver_photo": "https://res.cloudinary.com/.../seed_david",
    "content": "Hi! I'm excited to start working on this project.",
    "timestamp": "2026-06-27T13:45:00.000000Z",
    "read_at": null
  },
  {
    "id": "e5f6g7h8-...",
    "sender": "d67fcd1d-...",
    "receiver": "b14dc0b9-...",
    "sender_name": "David",
    "receiver_name": "Sam",
    "sender_photo": "https://res.cloudinary.com/.../seed_david",
    "receiver_photo": "https://res.cloudinary.com/.../seed_sam",
    "content": "That sounds great!",
    "timestamp": "2026-06-27T14:00:00.000000Z",
    "read_at": "2026-06-27T14:05:00.000000Z"
  }
]
```

> **How to determine message direction on the frontend:**
> Compare `sender` UUID to the logged-in user's profile ID.
> - If `sender === myProfileId` → **outgoing** (right-aligned bubble)
> - If `sender !== myProfileId` → **incoming** (left-aligned bubble)

---

### 5.4 Send Direct Message

Sends a new direct message to another user.

| Property | Value |
|---|---|
| **URL** | `/api/chat/direct/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "receiver": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da",
  "content": "Hey! How are you?"
}
```

**Success Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "sender": "b14dc0b9-...",
  "receiver": "d67fcd1d-...",
  "sender_name": "Sam",
  "receiver_name": "David",
  "sender_photo": "https://res.cloudinary.com/.../seed_sam",
  "receiver_photo": "https://res.cloudinary.com/.../seed_david",
  "content": "Hey! How are you?",
  "timestamp": "2026-06-27T15:00:00.000000Z",
  "read_at": null
}
```

**Error Responses:**
```json
// 400 — Blocked
{ "error": "Blocked." }

// 403 — Freemium monthly limit
{ "error": "Freemium tier allows only 1 new message thread initiation per month. Upgrade to send more." }

// 403 — Light monthly limit
{ "error": "Premium Light allows only 3 new message thread initiations per month. Upgrade to Premium Plus for unlimited." }
```

> **New Thread Limits (per month):**
> | Tier | New Threads/Month |
> |---|---|
> | Freemium | 1 |
> | Light | 3 |
> | Plus | Unlimited |
>
> Once a thread is open, there are no limits on messages within it.

---

# 📁 6. Settings & Safety

All endpoints require Bearer token authentication.

---

### 6.1 Change Password

| Property | Value |
|---|---|
| **URL** | `/api/settings/change-password/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "current_password": "OldPassword123!",
  "new_password": "NewPassword456!"
}
```

**Success Response (200):**
```json
{ "message": "Password changed successfully." }
```

**Error Response (400):**
```json
{ "error": "Invalid current password." }
```

---

### 6.2 Deactivate Account

| Property | Value |
|---|---|
| **URL** | `/api/settings/deactivate/` |
| **Method** | `POST` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Request Body:** None

**Success Response (200):**
```json
{ "message": "Account deactivated successfully." }
```

---

### 6.3 Upgrade Subscription

Upgrades or downgrades the user's subscription tier.

| Property | Value |
|---|---|
| **URL** | `/api/subscription/upgrade/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Bearer Token |

**Request Body:**
```json
{
  "tier": "plus",
  "amount": 19.99,
  "stripe_charge_id": "ch_1234567890"
}
```

> **Valid tiers:** `freemium`, `light`, `plus`
> `amount` and `stripe_charge_id` are optional. Defaults are used if omitted.

**Success Response (200):**
```json
{
  "message": "Subscription tier updated to plus.",
  "subscription_tier": "plus",
  "subscription_expires": "2026-07-27T10:00:00.000000Z",
  "transaction": {
    "id": "a1b2c3d4-...",
    "user": "b14dc0b9-...",
    "plan_name": "Premium Plus",
    "amount": "19.99",
    "status": "successful",
    "stripe_charge_id": "ch_1234567890",
    "created_at": "2026-06-27T10:00:00.000000Z"
  }
}
```

---

### 6.4 Transaction History

Returns all past subscription transactions.

| Property | Value |
|---|---|
| **URL** | `/api/subscription/history/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "a1b2c3d4-...",
    "user": "b14dc0b9-...",
    "plan_name": "Premium Plus",
    "amount": "19.99",
    "status": "successful",
    "stripe_charge_id": "ch_1234567890",
    "created_at": "2026-06-27T10:00:00.000000Z"
  }
]
```

---

# 📁 7. Photos

All endpoints require Bearer token authentication.

---

### 7.1 Upload Photo

Uploads a new profile photo. Uses Cloudinary cloud storage.

| Property | Value |
|---|---|
| **URL** | `/api/photos/` |
| **Method** | `POST` |
| **Content-Type** | `multipart/form-data` |
| **Auth** | ✅ Bearer Token |

**Form Data Fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `image_upload` | file | ✅ | The image file |
| `is_main` | text | ❌ | `true` to set as main photo |

**Success Response (201):**
```json
{
  "id": "c5d6e7f8-...",
  "profile": "b14dc0b9-...",
  "image": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/...",
  "is_main": true,
  "is_verified": false,
  "uploaded_at": "2026-06-27T08:00:00Z"
}
```

---

### 7.2 Update Photo

Replaces an existing photo. The old Cloudinary image is automatically deleted.

| Property | Value |
|---|---|
| **URL** | `/api/photos/<photo_uuid>/` |
| **Method** | `PUT` or `PATCH` |
| **Content-Type** | `multipart/form-data` |
| **Auth** | ✅ Bearer Token |

**Form Data Fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `image_upload` | file | ❌ | New image file |
| `is_main` | text | ❌ | `true` / `false` |

---

### 7.3 Delete Photo

Deletes a photo. The Cloudinary asset is automatically cleaned up.

| Property | Value |
|---|---|
| **URL** | `/api/photos/<photo_uuid>/` |
| **Method** | `DELETE` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (204):** No content.

---

### 7.4 List My Photos

| Property | Value |
|---|---|
| **URL** | `/api/photos/` |
| **Method** | `GET` |
| **Content-Type** | None |
| **Auth** | ✅ Bearer Token |

**Success Response (200):**
```json
[
  {
    "id": "c5d6e7f8-...",
    "profile": "b14dc0b9-...",
    "image": "https://res.cloudinary.com/dl83bpmyz/image/upload/v1/media/profile_photos/...",
    "is_main": true,
    "is_verified": false,
    "uploaded_at": "2026-06-27T08:00:00Z"
  }
]
```

---

# 📁 8. Dashboard (Admin APIs)

All admin endpoints require an admin-role Bearer token.

---

### 8.1 System Statistics Dashboard

| Property | Value |
|---|---|
| **URL** | `/api/admin/dashboard/stats/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

**Success Response (200):**
```json
{
  "total_users": 1500,
  "active_premium": 320,
  "pending_verifications": 15,
  "unresolved_reports": 8,
  "total_revenue": "45230.50"
}
```

---

### 8.2 Master User List

| Property | Value |
|---|---|
| **URL** | `/api/admin/users/?search=<query>` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `search` | string | Search by username or email |

---

### 8.3 List Pending Photo Verifications

| Property | Value |
|---|---|
| **URL** | `/api/admin/verifications/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

---

### 8.4 Approve / Reject Photo Verification

| Property | Value |
|---|---|
| **URL** | `/api/admin/verifications/<profile_uuid>/action/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Admin Token |

**Request Body:**
```json
{ "action": "approve" }
```
> Valid values: `"approve"` or `"reject"`

---

### 8.5 Matches Dashboard

| Property | Value |
|---|---|
| **URL** | `/api/admin/matches/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

---

### 8.6 Subscriptions Dashboard

| Property | Value |
|---|---|
| **URL** | `/api/admin/subscriptions/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

---

### 8.7 Payments Dashboard

| Property | Value |
|---|---|
| **URL** | `/api/admin/payments/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

---

### 8.8 Reports Dashboard

| Property | Value |
|---|---|
| **URL** | `/api/admin/reports/dashboard/` |
| **Method** | `GET` |
| **Auth** | ✅ Admin Token |

---

### 8.9 Update User Role

| Property | Value |
|---|---|
| **URL** | `/api/admin/users/<profile_uuid>/role/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Super Admin Token |

**Request Body:**
```json
{ "role": "moderator" }
```

---

### 8.10 Gift Subscription to User

| Property | Value |
|---|---|
| **URL** | `/api/admin/users/<profile_uuid>/gift/` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth** | ✅ Admin Token |

**Request Body:**
```json
{
  "tier": "plus",
  "days": 30
}
```

---

# 📋 Quick Reference: All UUIDs

All IDs in this API are **UUID v4** strings (e.g., `"b14dc0b9-354c-4b6f-b942-3f67d2bfff3d"`).

| Entity | Where to find the UUID |
|---|---|
| **My Profile ID** | `GET /api/profile/me/` → `id` field |
| **Other Profile ID** | From search results, suggestions, match cards, thread data |
| **Friendship ID** | `GET /api/friends/requests/` → `id` field |
| **Room ID** | `GET /api/chat/rooms/` → `id` field |
| **Photo ID** | `GET /api/photos/` → `id` field |
| **Message ID** | From conversation history → `id` field |

---

# 📋 Quick Reference: Subscription Tiers

| Feature | Freemium | Light (€9.99/mo) | Plus (€19.99/mo) |
|---|---|---|---|
| Daily Likes | 20 | 50 | Unlimited |
| New DM Threads/Month | 1 | 3 | Unlimited |
| See Who Liked You | ❌ | ✅ | ✅ |
| Advanced Match Filters | ❌ | ✅ | ✅ |
| Community Chat Rooms | ❌ | ✅ | ✅ |

---

# 🔌 9. WebSockets API

The Chahira real-time system uses WebSockets (via Django Channels) for instant messaging, read receipts, and active status tracking.

> **WebSocket Base URL:** `ws://127.0.0.1:8000/ws`
>
> **Authentication:** Pass the user's JWT access token as a query parameter:
> `ws://127.0.0.1:8000/ws/chat/?token=<access_token>`

---

## 9.1 Chat WebSocket (`/ws/chat/`)

Handles DMs, Room joins, message transmissions, read receipts, and pings.

### 9.1.1 Keep-Alive Heartbeat (Ping/Pong)
Clients should send a ping message every 30 seconds to prevent connection timeouts.
* **Client Request:**
```json
{
  "type": "ping"
}
```
* **Server Response:**
```json
{
  "type": "pong"
}
```

---

### 9.1.2 Send Direct Message (DM)
Sends a private message to a matched user or accepted friend.
* **Client Request:**
```json
{
  "type": "direct_message",
  "recipient_id": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da",
  "content": "Hey, are we still meeting tomorrow?",
  "temp_id": "client-side-unique-temp-id"
}
```
* **Server Broadcast (sent to both sender and recipient inboxes):**
```json
{
  "type": "direct_message",
  "message": {
    "id": "e6b0dae3-f156-45ee-ac60-e630445ca80b",
    "sender": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "receiver": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da",
    "sender_name": "Sam",
    "receiver_name": "David",
    "sender_photo": "https://res.cloudinary.com/.../seed_sam",
    "receiver_photo": "https://res.cloudinary.com/.../seed_david",
    "content": "Hey, are we still meeting tomorrow?",
    "timestamp": "2026-06-27T10:15:00.000000Z",
    "read_at": null
  },
  "temp_id": "client-side-unique-temp-id"
}
```

---

### 9.1.3 DM Read Receipts
Notifies the server when a user reads messages.
* **Client Request:**
```json
{
  "type": "read_receipt",
  "message_ids": [
    "e6b0dae3-f156-45ee-ac60-e630445ca80b"
  ]
}
```
* **Server Broadcast (sent back to the original message sender):**
```json
{
  "type": "read_receipt",
  "message_ids": [
    "e6b0dae3-f156-45ee-ac60-e630445ca80b"
  ],
  "reader_id": "d67fcd1d-89c5-478f-b372-c4cbf6d9f9da"
}
```

---

### 9.1.4 Enter Community Chat Room
Tells the server the client has opened a community chat room screen. The server adds the client's socket to the room broadcast group.
* **Client Request:**
```json
{
  "type": "enter_room",
  "room_id": "7ea0139d-7fc5-431c-9a46-db267816566f"
}
```
* **Server Response:** None (silent join)

---

### 9.1.5 Leave Community Chat Room
Tells the server the client has exited the chat room screen.
* **Client Request:**
```json
{
  "type": "leave_room",
  "room_id": "7ea0139d-7fc5-431c-9a46-db267816566f"
}
```
* **Server Response:** None (silent leave)

---

### 9.1.6 Send Room Message
Sends a message to an active community chat room.
* **Client Request:**
```json
{
  "type": "room_message",
  "room_id": "7ea0139d-7fc5-431c-9a46-db267816566f",
  "content": "Awesome, thanks for sharing!",
  "temp_id": "client-side-unique-temp-id"
}
```
* **Server Broadcast (sent to all users currently subscribed to the room group):**
```json
{
  "type": "room_message",
  "message": {
    "id": "69705bb7-1a3a-4ff6-a16f-2c0c61fcc109",
    "room": "7ea0139d-7fc5-431c-9a46-db267816566f",
    "sender": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
    "sender_name": "Sam",
    "sender_photo": "https://res.cloudinary.com/.../seed_sam",
    "content": "Awesome, thanks for sharing!",
    "timestamp": "2026-06-27T10:17:00.000000Z"
  },
  "temp_id": "client-side-unique-temp-id"
}
```

---

## 9.2 Status WebSocket (`/ws/status/`)

Tracks online presence. When a user connects, their status broadcasts as `"online"` to all accepted friends. On disconnect, it broadcasts as `"offline"`.

* **Connection URL:**
`ws://127.0.0.1:8000/ws/status/?token=<access_token>`

* **Server Broadcast (sent to connected friends when user's status changes):**
```json
{
  "type": "status_update",
  "profile_id": "b14dc0b9-354c-4b6f-b942-3f67d2bfff3d",
  "status": "online"
}
```
*(Status value will be `"online"` or `"offline"`)*

