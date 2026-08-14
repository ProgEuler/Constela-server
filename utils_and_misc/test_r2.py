import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

import boto3
from django.conf import settings
from botocore.config import Config

s3 = boto3.client('s3',
    endpoint_url=settings.AWS_S3_ENDPOINT_URL,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

try:
    print("Testing head object on non-existent key...")
    s3.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key="doesnotexist.txt")
except Exception as e:
    print("Error:", str(e))
