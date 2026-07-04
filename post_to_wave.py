#!/usr/bin/env python3
"""Post Cloud Report PNG to 6529.io Cloud Report wave."""
import json, urllib.request, sys, os

WAVE_ID = 'adcf0172-a667-40c9-8547-dea279194366'
API = 'https://api.6529.io/api'

token = os.environ.get('TOKEN_6529')
if not token:
    print("ERROR: TOKEN_6529 not set")
    sys.exit(1)

img_path = sys.argv[1] if len(sys.argv) > 1 else 'cloud_report.png'
caption = sys.argv[2] if len(sys.argv) > 2 else "Cloud Report update"

headers = {'Authorization': f'Bearer {token}'}

# Step 1: Start upload
data = json.dumps({"file_name": "cloud_report.png", "content_type": "image/png"}).encode()
req = urllib.request.Request(f'{API}/drop-media/multipart-upload', data=data,
    headers={**headers, 'Content-Type': 'application/json'}, method='POST')
r1 = json.loads(urllib.request.urlopen(req).read())
upload_id, key = r1['upload_id'], r1['key']

# Step 2: Get part URL
data2 = json.dumps({"upload_id": upload_id, "key": key, "part_no": 1}).encode()
req2 = urllib.request.Request(f'{API}/drop-media/multipart-upload/part', data=data2,
    headers={**headers, 'Content-Type': 'application/json'}, method='POST')
r2 = json.loads(urllib.request.urlopen(req2).read())

# Step 3: Upload to S3
with open(img_path, 'rb') as f:
    file_data = f.read()
req3 = urllib.request.Request(r2['upload_url'], data=file_data,
    headers={'Content-Type': 'image/png'}, method='PUT')
resp3 = urllib.request.urlopen(req3)
etag = resp3.headers['ETag'].strip('"')

# Step 4: Complete upload
data4 = json.dumps({"upload_id": upload_id, "key": key, "parts": [{"part_no": 1, "etag": etag}]}).encode()
req4 = urllib.request.Request(f'{API}/drop-media/multipart-upload/completion', data=data4,
    headers={**headers, 'Content-Type': 'application/json'}, method='POST')
r4 = json.loads(urllib.request.urlopen(req4).read())

# Step 5: Post drop with image
drop_data = json.dumps({
    "wave_id": WAVE_ID,
    "drop_type": "CHAT",
    "parts": [{"content": caption, "media": [{
        "url": r4['media_url'], "mime_type": "image/png",
        "media_upload_id": r4.get('media_upload_id')
    }]}]
}).encode()
req5 = urllib.request.Request(f'{API}/drops', data=drop_data,
    headers={**headers, 'Content-Type': 'application/json'}, method='POST')
r5 = json.loads(urllib.request.urlopen(req5).read())
print(f"Posted to wave! Serial: {r5.get('serial_no')}")