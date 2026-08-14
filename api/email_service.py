import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

def _get_base_html_template(title: str, subtitle: str, body_text: str, code: str, expiry_minutes: int = 10, security_note: str = None) -> str:
    """
    Generates a responsive, beautifully styled HTML email template for Constela.
    """
    if security_note is None:
        security_note = "For your security, never share this code with anyone. Constela staff will never ask for your verification code."

    # Format code nicely (e.g. 123 456 or just large spaced numbers)
    formatted_code = f"{code[:3]} {code[3:]}" if len(code) == 6 else code

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #F4F5F8;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #2D3748;
      -webkit-font-smoothing: antialiased;
    }}
    .wrapper {{
      width: 100%;
      table-layout: fixed;
      background-color: #F4F5F8;
      padding: 40px 0;
    }}
    .container {{
      max-width: 520px;
      margin: 0 auto;
      background-color: #FFFFFF;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 25px rgba(0,0,0,0.06);
    }}
    .header {{
      background: linear-gradient(135deg, #DE4177 0%, #F45B90 100%);
      background-color: #DE4177;
      padding: 36px 32px;
      text-align: center;
    }}
    .logo-text {{
      color: #FFFFFF;
      font-size: 32px;
      font-weight: 800;
      letter-spacing: -0.5px;
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }}
    .logo-sub {{
      color: rgba(255, 255, 255, 0.85);
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      margin-top: 4px;
    }}
    .content {{
      padding: 36px 32px;
      text-align: center;
    }}
    .title {{
      font-size: 22px;
      font-weight: 700;
      color: #1A202C;
      margin-top: 0;
      margin-bottom: 12px;
    }}
    .body-text {{
      font-size: 15px;
      line-height: 1.6;
      color: #4A5568;
      margin-bottom: 28px;
    }}
    .code-box {{
      background-color: #FFF5F8;
      border: 2px dashed #DE4177;
      border-radius: 12px;
      padding: 20px 16px;
      margin: 0 auto 28px auto;
      max-width: 320px;
    }}
    .code-label {{
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: #DE4177;
      margin-bottom: 8px;
    }}
    .code-number {{
      font-family: 'SF Mono', Consolas, Monaco, 'Courier New', monospace;
      font-size: 38px;
      font-weight: 800;
      letter-spacing: 8px;
      color: #DE4177;
      margin: 0;
    }}
    .expiry-tag {{
      font-size: 13px;
      color: #718096;
      margin-top: 8px;
      font-weight: 500;
    }}
    .divider {{
      height: 1px;
      background-color: #EDF2F7;
      margin: 28px 0;
    }}
    .security-note {{
      background-color: #F7FAFC;
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 13px;
      color: #718096;
      line-height: 1.5;
      text-align: left;
    }}
    .footer {{
      background-color: #FAFCFE;
      padding: 24px 32px;
      text-align: center;
      border-top: 1px solid #EDF2F7;
    }}
    .footer-text {{
      font-size: 12px;
      color: #A0AEC0;
      line-height: 1.5;
      margin: 0;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="header">
        <h1 class="logo-text">Constela</h1>
        <div class="logo-sub">Connect Mindfully</div>
      </div>
      <div class="content">
        <h2 class="title">{title}</h2>
        <p class="body-text">{body_text}</p>
        
        <div class="code-box">
          <div class="code-label">Verification Code</div>
          <div class="code-number">{code}</div>
          <div class="expiry-tag">⏱ Valid for {expiry_minutes} minutes</div>
        </div>

        <div class="security-note">
          🔒 <strong>Security Tip:</strong> {security_note}
        </div>
      </div>
      <div class="footer">
        <p class="footer-text">
          Sent with ❤️ from the Constela Team.<br>
          If you didn't request this email, please ignore it or contact support.
        </p>
      </div>
    </div>
  </div>
</body>
</html>
"""
    return html


def send_signup_verification_email(recipient_email: str, otp_code: str, username: str = None):
    """Sends account verification code upon sign up."""
    greeting = f"Hi {username}," if username else "Welcome!"
    subject = "Verify your Constela Account"
    title = "Verify Your Account"
    body_text = f"{greeting} Welcome to Constela! We're excited to have you join our community. Please enter the 6-digit code below to verify your email address and get started."

    plain_message = f"Welcome to Constela!\n\nYour account verification code is: {otp_code}\n\nThis code will expire in 10 minutes."
    html_message = _get_base_html_template(
        title=title,
        subtitle="Account Verification",
        body_text=body_text,
        code=otp_code,
        expiry_minutes=10
    )

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"✅ Signup verification email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send signup verification email to {recipient_email}: {e}")
        return False


def send_resend_otp_email(recipient_email: str, otp_code: str, username: str = None):
    """Sends a new verification OTP code when user clicks resend."""
    greeting = f"Hi {username}," if username else "Hello,"
    subject = "Your New Constela Verification Code"
    title = "New Verification Code"
    body_text = f"{greeting} Here is your requested verification code. Please enter it in the app to continue."

    plain_message = f"Your new Constela verification code is: {otp_code}\n\nThis code will expire in 10 minutes."
    html_message = _get_base_html_template(
        title=title,
        subtitle="New Verification Code",
        body_text=body_text,
        code=otp_code,
        expiry_minutes=10
    )

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"✅ Resend OTP email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send resend OTP email to {recipient_email}: {e}")
        return False


def send_password_reset_email(recipient_email: str, otp_code: str, username: str = None):
    """Sends a password reset code."""
    greeting = f"Hi {username}," if username else "Hello,"
    subject = "Reset Your Constela Password"
    title = "Password Reset Request"
    body_text = f"{greeting} We received a request to reset the password for your Constela account. Enter the security code below to reset your password."
    security_note = "If you didn't request a password reset, your account is safe and you can safely ignore this email."

    plain_message = f"Reset your Constela password\n\nYour reset code is: {otp_code}\n\nThis code will expire in 10 minutes."
    html_message = _get_base_html_template(
        title=title,
        subtitle="Password Reset",
        body_text=body_text,
        code=otp_code,
        expiry_minutes=10,
        security_note=security_note
    )

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"✅ Password reset email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send password reset email to {recipient_email}: {e}")
        return False


def send_email_change_email(recipient_email: str, otp_code: str, username: str = None):
    """Sends verification code to verify a new email address change."""
    greeting = f"Hi {username}," if username else "Hello,"
    subject = "Verify Your New Email Address"
    title = "Email Change Verification"
    body_text = f"{greeting} You requested to update your email address on Constela to {recipient_email}. Please enter the code below to confirm this change."

    plain_message = f"Verify your new email address for Constela\n\nYour OTP code is: {otp_code}\n\nThis code will expire in 10 minutes."
    html_message = _get_base_html_template(
        title=title,
        subtitle="Email Change Verification",
        body_text=body_text,
        code=otp_code,
        expiry_minutes=10
    )

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"✅ Email change verification sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send email change OTP to {recipient_email}: {e}")
        return False
