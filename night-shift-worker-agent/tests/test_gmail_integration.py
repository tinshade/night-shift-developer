import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv


load_dotenv()

# 1. Configuration details
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465  # Secure SSL port
SENDER_EMAIL = os.environ.get("GOOGLE_EMAIL_ID", "")
# Paste your 16-character App Password here (no spaces)
SENDER_PASSWORD = os.environ.get("GOOGLE_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("GOOGLE_EMAIL_ID", "")

# 2. Construct the email metadata and content
message = MIMEMultipart()
message["From"] = SENDER_EMAIL
message["To"] = RECIPIENT_EMAIL
message["Subject"] = "Local Python Test Email"

body = "Hello! This email was sent locally from a Python script using Gmail SMTP."
message.attach(MIMEText(body, "plain"))

try:
    # 3. Establish a secure connection and send the email
    print("Connecting to Gmail SMTP server...")
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        print("Login successful! Sending email...")
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, message.as_string())
        
    print("Email sent successfully!")

except Exception as e:
    print(f"An error occurred: {e}")