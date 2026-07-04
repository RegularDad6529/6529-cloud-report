#!/usr/bin/env python3
"""
6529 Cloud Report v10 — Static PIL PNG (2x supersampled) + weather-only animation HTML.
No text animation = no overlap. Mask sized to wordcloud's natural fill (~850px).
"""
import json, urllib.request, re, time, math, random, base64
from collections import Counter
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from wordcloud import WordCloud, STOPWORDS
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
from datetime import datetime, timezone, timedelta

# === Config ===
TOKEN = json.load(open('/home/prenode/.hermes/profiles/themanager/6529_tokens.json'))['token']
API_BASE = 'https://api.6529.io/api'
OUTPUT_PNG = '/tmp/6529_weather.png'  # may be overridden by --output flag below
OUTPUT_HTML = '/tmp/6529_cloud_report_v10.html'
FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT_REGULAR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

W, H = 1350, 1080  # Final output
SS = 2  # Supersample factor
RW, RH = W * SS, H * SS  # Render at 2700x2160

# Mask: wide horizontal cloud shape for landscape format
# wordcloud fills ~850px at 1x → ~1700px at 2x
# Make mask 1750px wide x 1200px tall (at 2x) → wide landscape cloud
# Mask: smaller than canvas so blue background is visible around cloud
# Cloud fills ~80% of canvas, leaving blue sky around it
MASK_W = RW  # full canvas — no rectangle
MASK_H = RH  # full canvas
MASK_XO = 0
MASK_YO = 0

DIVE_BAR_ID = 'b38288e6-ca9d-45ce-8323-3dc5e094f04e'
DIVE_BAR_DROPS = 600
NUM_WAVES = 12
DROPS_PER_WAVE = 240
IGNORE_USERS = {'gray', 'karen_intern'}
IGNORE_WAVES = {'pause', 'wip', 'Available works', 'Series/Collections'}

EXTRA_STOPWORDS = {
    'http', 'https', 'www', 'com', 'org', 'gif', 'jpg', 'png', 'img',
    'giphy', 'cloudfront', '6529', 'io', 'also', 'one', 'really', 'even',
    'would', 'could', 'should', 'much', 'like', 'just', 'get', 'got',
    'going', 'know', 'think', 'yeah', 'yes', 'lol', 'ha', 'haha',
    'right', 'well', 'still', 'back', 'thing', 'things', 'make', 'made',
    'good', 'great', 'nice', 'cool', 'awesome', 'love',
    'want', 'need', 'look', 'see', 'say', 'said', 'way', 'time',
    'day', 'today', 'now', 'then', 'here', 'there', 'what', 'who',
    'how', 'why', 'when', 'where', 'this', 'that', 'these', 'those',
    'the', 'and', 'but', 'for', 'with', 'not', 'have', 'has', 'had',
    'are', 'was', 'were', 'been', 'being', 'from', 'into', 'onto',
    'your', 'their', 'they', 'them', 'his', 'her', 'she', 'him',
    'you', 'me', 'my', 'we', 'us', 'our', 'about', 'some', 'any',
    'all', 'each', 'every', 'other', 'more', 'most', 'such', 'than',
    'too', 'very', 'can', 'will', 'may', 'might', 'must', 'shall',
    'out', 'up', 'down', 'off', 'over', 'under', 'again', 'only',
    'so', 'if', 'or', 'as', 'at', 'by', 'be', 'do', 'did', 'does',
    'an', 'no', 'it', 'its', 'is', 'in', 'on', 'to', 'of', 'a',
    'anon', 'bot', 'drop', 'drops', 'reply', 'replies', 'serial',
    'png', 'webp', 'jpeg', 'image', 'upload', 'http', 'https',
}

def api_get(path):
    req = urllib.request.Request(f'{API_BASE}/{path}',
        headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/json',
                 'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())

def fetch_wave_drops(wave_id, limit=30):
    all_drops = []
    offset = 0
    while len(all_drops) < limit:
        try:
            data = api_get(f'drops?wave_id={wave_id}&limit=10&offset={offset}')
            drops = data if isinstance(data, list) else data.get('drops', data.get('data', []))
            if not drops:
                break
            all_drops.extend(drops)
            offset += len(drops)
            if len(drops) < 10:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f'  Error: {e}')
            break
    return all_drops[:limit]

def extract_text(drop):
    parts = drop.get('parts', [])
    texts = []
    for part in parts:
        content = part.get('content', '')
        if content and content.strip():
            texts.append(content.strip())
    return ' '.join(texts)

def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

def get_weather_palette(s):
    """New color scheme:
    Background: bright blue at +1, black at -1
    Cloud fill: grayscale — lighter gray at +1, darker at -1
    Words: contrast cloud fill — positive=white, negative=dark gray, neutral=mid gray
    """
    s = max(-1, min(1, s))
    # Background: bright blue (80,150,230) at +1 → black (0,0,0) at -1
    t = (s + 1) / 2  # 0 at -1, 1 at +1
    bg1 = lerp_color((0, 0, 0), (60, 110, 180), t)
    bg2 = lerp_color((0, 0, 0), (80, 150, 230), t)
    bg3 = lerp_color((0, 0, 0), (100, 170, 240), t)
    # Cloud fill: light gray (200) at +1 → dark gray (50) at -1
    gray_val = int(50 + t * 150)  # 50..200
    cloud_fill_color = (gray_val, gray_val, gray_val)
    # Word colors: contrast against cloud fill
    # Positive words: white (255,255,255) at +1
    # Negative words: dark gray (30,30,30) at -1
    # Neutral words: mid gray that contrasts cloud fill
    text_c = (255, 255, 255) if s > 0 else (200, 200, 200)
    accent_c = lerp_color((100, 100, 100), (200, 200, 200), (s + 1) / 2)
    label = 'SUNNY' if s > 0.4 else 'PARTLY CLOUDY' if s > 0.15 else 'OVERCAST' if s > -0.15 else 'RAINY' if s > -0.4 else 'STORMY'
    return (label, [bg1, bg2, bg3], text_c, accent_c, cloud_fill_color)

def render_weather_bg(weather_label, colors, w, h):
    """Render weather background at render resolution (2x).
    Clean gradient with subtle texture — no heavy blurs that cause mushiness."""
    img = Image.new('RGB', (w, h))
    draw = ImageDraw.Draw(img)
    c1, c2, c3 = colors
    for y in range(h):
        t = y / h
        if t < 0.5:
            r = c1[0] + (c2[0] - c1[0]) * (t * 2)
            g = c1[1] + (c2[1] - c1[1]) * (t * 2)
            b = c1[2] + (c2[2] - c1[2]) * (t * 2)
        else:
            t2 = (t - 0.5) * 2
            r = c2[0] + (c3[0] - c2[0]) * t2
            g = c2[1] + (c3[1] - c2[1]) * t2
            b = c2[2] + (c3[2] - c2[2]) * t2
        draw.line([(0, y), (w, y)], fill=(int(r), int(g), int(b)))

    # Very subtle radial light for depth — single layer, no stacking
    if weather_label == 'SUNNY':
        cx, cy = w - 360, 240
        glow = Image.new('L', (w, h), 0)
        gd = ImageDraw.Draw(glow)
        for r in range(500, 0, -8):
            v = int(12 * (1 - r/500))
            if v > 0:
                gd.ellipse([cx-r, cy-r, cx+r, cy+r], fill=v)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=30))
        warm = Image.new('RGB', (w, h), (200, 170, 100))
        img = Image.composite(Image.blend(img, warm, 0.15), img, glow)

    # Subtle vignette — very light, just for depth
    vignette = Image.new('L', (w, h), 0)
    vignette_draw = ImageDraw.Draw(vignette)
    cx, cy = w // 2, h // 2
    max_dist = math.sqrt(cx**2 + cy**2)
    for r in range(int(max_dist), 0, -3):
        alpha = int(12 * (r / max_dist) ** 2)  # very light
        vignette_draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=alpha)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=40))  # tight blur, no mush
    dark_overlay = Image.new('RGB', (w, h), (0, 0, 0))
    img = Image.composite(img, dark_overlay,
        Image.eval(vignette, lambda v: 255 - v))
    return img

import sys
CACHE_FILE = '/tmp/cloud_word_freq_cache.json'
USE_CACHE = '--cached' in sys.argv
DAILY_MODE = '--daily' in sys.argv
OVERRIDE_SENTIMENT = None
OUTPUT_PATH = None
for i, arg in enumerate(sys.argv):
    if arg == '--sentiment' and i + 1 < len(sys.argv):
        OVERRIDE_SENTIMENT = float(sys.argv[i + 1])
    if arg == '--output' and i + 1 < len(sys.argv):
        OUTPUT_PATH = sys.argv[i + 1]

def is_within_24h(drop, cutoff_ts):
    """Check if a drop was created within the last 24 hours.
    created_at is a Unix timestamp in milliseconds."""
    created = drop.get('created_at', 0)
    if not created:
        return False
    try:
        # created_at is in milliseconds, cutoff_ts is in seconds
        return created / 1000 >= cutoff_ts
    except:
        return False

def fetch_daily_drops(wave_id, cutoff_ts, max_fetch=200):
    """Fetch drops from a wave, keeping only those from the last 24 hours."""
    all_drops = []
    offset = 0
    while len(all_drops) < max_fetch:
        try:
            data = api_get(f'drops?wave_id={wave_id}&limit=10&offset={offset}')
            drops = data if isinstance(data, list) else data.get('drops', data.get('data', []))
            if not drops:
                break
            # Filter to last 24h
            recent = [d for d in drops if is_within_24h(d, cutoff_ts)]
            all_drops.extend(recent)
            # If the oldest drop in this batch is older than 24h, we can stop
            oldest = drops[-1]
            if not is_within_24h(oldest, cutoff_ts):
                break
            offset += len(drops)
            if len(drops) < 10:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f'  Error: {e}')
            break
    return all_drops

def count_daily_drops(wave_id, cutoff_ts, sample_size=30):
    """Quick count of drops in the last 24h (fetches a small sample)."""
    drops = fetch_wave_drops(wave_id, sample_size)
    return len([d for d in drops if is_within_24h(d, cutoff_ts)])

def fetch_and_process_daily():
    """Daily mode: fetch only drops from the past 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cutoff_ts = cutoff.timestamp()
    print(f'Daily mode: fetching drops since {cutoff.isoformat()}')

    # Fetch all waves
    print('Fetching waves...')
    waves_data = api_get('waves?limit=50')
    waves = waves_data if isinstance(waves_data, list) else waves_data.get('waves', waves_data.get('data', []))

    # Count recent activity per wave (quick sample)
    print('Counting drops in last 24h per wave...')
    wave_activity = []
    for w in waves:
        wid = w['id']
        wname = w.get('name', 'unknown')
        if any(skip.lower() in wname.lower() for skip in IGNORE_WAVES):
            continue
        if wid == DIVE_BAR_ID:
            continue  # dive bar is always included
        try:
            count = count_daily_drops(wid, cutoff_ts, sample_size=30)
            if count > 0:
                wave_activity.append((w, count))
                print(f'  {wname[:30]:30s} → {count} drops (last 24h)')
        except:
            pass
        time.sleep(0.3)

    wave_activity.sort(key=lambda x: x[1], reverse=True)
    top_waves = [x[0] for x in wave_activity[:5]]  # top 5 busiest
    print(f'\nTop 5 busiest waves today: {[w.get("name","?")[:20] for w in top_waves]}')

    # Fetch all drops
    all_text = []
    wave_names = []

    # Dive bar — get ALL drops from last 24h
    print(f'\n  DIVE BAR → fetching last 24h...')
    dive_drops = fetch_daily_drops(DIVE_BAR_ID, cutoff_ts, max_fetch=500)
    wave_names.append('Dive Bar')
    for drop in dive_drops:
        author = drop.get('author', {})
        handle = author.get('handle', '') if isinstance(author, dict) else str(author)
        if handle.lower() in IGNORE_USERS:
            continue
        text = extract_text(drop)
        if text and len(text) > 3:
            all_text.append(text)
    print(f'    → {len(dive_drops)} drops, {len([t for t in all_text])} text samples')

    # Top 5 busiest waves
    for w in top_waves:
        wid = w['id']
        wname = w.get('name', 'unknown')
        wave_names.append(wname)
        drops = fetch_daily_drops(wid, cutoff_ts, max_fetch=200)
        print(f'  {wname[:30]:30s} → {len(drops)} drops')
        for drop in drops:
            author = drop.get('author', {})
            handle = author.get('handle', '') if isinstance(author, dict) else str(author)
            if handle.lower() in IGNORE_USERS:
                continue
            text = extract_text(drop)
            if text and len(text) > 3:
                all_text.append(text)

    print(f'\nTotal text samples: {len(all_text)}')
    if len(all_text) < 10:
        print('WARNING: Very few drops in the last 24h — cloud will be sparse')

    # Process text (same as full mode)
    combined = ' '.join(all_text)
    combined = re.sub(r'https?://\S+', '', combined)
    words = re.findall(r'\b[a-zA-Z]{2,}\b', combined.lower())
    all_stopwords = STOPWORDS | EXTRA_STOPWORDS
    filtered = [w for w in words if w not in all_stopwords]

    word_freq = Counter(filtered)
    bigram_counts = Counter()
    for i in range(len(filtered) - 1):
        bg = f'{filtered[i]} {filtered[i+1]}'
        bigram_counts[bg] += 1

    bigram_word_count = Counter()
    eligible_bigrams = [(bg, count) for bg, count in bigram_counts.items() if count >= 2]
    eligible_bigrams.sort(key=lambda x: x[1], reverse=True)

    for bg, count in eligible_bigrams:
        w1, w2 = bg.split()
        if bigram_word_count[w1] >= 2 or bigram_word_count[w2] >= 2:
            continue
        word_freq[bg] = int(count * 2.5)
        bigram_word_count[w1] += 1
        bigram_word_count[w2] += 1

    bigram_component_words = set()
    for bg in list(word_freq.keys()):
        if ' ' in bg:
            for w in bg.split():
                bigram_component_words.add(w)
    for w in bigram_component_words:
        word_freq.pop(w, None)

    # Sentiment
    analyzer = SentimentIntensityAnalyzer()
    sentiment_scores = [analyzer.polarity_scores(t)['compound'] for t in all_text]
    avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0

    # Save cache
    with open(CACHE_FILE, 'w') as f:
        json.dump({
            'word_freq': dict(word_freq),
            'sentiment': avg_sentiment,
            'wave_names': wave_names,
            'drop_count': len(all_text),
            'word_count': len(word_freq),
            'mode': 'daily',
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        }, f)
    print(f'Cached to {CACHE_FILE}')

    return word_freq, avg_sentiment, wave_names, len(all_text)

def fetch_and_process():
    """Fetch drops from API and process into word_freq, sentiment, wave_names."""
    print('Fetching waves...')
    waves_data = api_get('waves?limit=50')
    waves = waves_data if isinstance(waves_data, list) else waves_data.get('waves', waves_data.get('data', []))

    print('Counting recent drops per wave...')
    wave_activity = []
    for w in waves:
        wid = w['id']
        wname = w.get('name', 'unknown')
        if any(skip.lower() in wname.lower() for skip in IGNORE_WAVES):
            continue
        try:
            data = api_get(f'drops?wave_id={wid}&limit=50')
            count = len(data) if isinstance(data, list) else 0
            wave_activity.append((w, count))
        except:
            pass
    wave_activity.sort(key=lambda x: x[1], reverse=True)
    top_waves = [x[0] for x in wave_activity[:NUM_WAVES]]

    print('\nFetching drops...')
    all_text = []
    wave_names = []

    print(f'  DIVE BAR → {DIVE_BAR_DROPS} drops...')
    dive_drops = fetch_wave_drops(DIVE_BAR_ID, DIVE_BAR_DROPS)
    wave_names.append('Dive Bar')
    for drop in dive_drops:
        author = drop.get('author', {})
        handle = author.get('handle', '') if isinstance(author, dict) else str(author)
        if handle.lower() in IGNORE_USERS:
            continue
        text = extract_text(drop)
        if text and len(text) > 3:
            all_text.append(text)

    for w in top_waves:
        wid = w['id']
        wname = w.get('name', 'unknown')
        if wid == DIVE_BAR_ID:
            continue
        wave_names.append(wname)
        drops = fetch_wave_drops(wid, DROPS_PER_WAVE)
        print(f'  {wname[:30]:30s} → {len(drops)} drops')
        for drop in drops:
            author = drop.get('author', {})
            handle = author.get('handle', '') if isinstance(author, dict) else str(author)
            if handle.lower() in IGNORE_USERS:
                continue
            text = extract_text(drop)
            if text and len(text) > 3:
                all_text.append(text)

    print(f'\nTotal text samples: {len(all_text)}')

    # Process text
    combined = ' '.join(all_text)
    combined = re.sub(r'https?://\S+', '', combined)
    words = re.findall(r'\b[a-zA-Z]{2,}\b', combined.lower())
    all_stopwords = STOPWORDS | EXTRA_STOPWORDS
    filtered = [w for w in words if w not in all_stopwords]

    word_freq = Counter(filtered)
    bigram_counts = Counter()
    for i in range(len(filtered) - 1):
        bg = f'{filtered[i]} {filtered[i+1]}'
        bigram_counts[bg] += 1

    bigram_word_count = Counter()
    eligible_bigrams = [(bg, count) for bg, count in bigram_counts.items() if count >= 3]
    eligible_bigrams.sort(key=lambda x: x[1], reverse=True)

    for bg, count in eligible_bigrams:
        w1, w2 = bg.split()
        if bigram_word_count[w1] >= 2 or bigram_word_count[w2] >= 2:
            continue
        word_freq[bg] = int(count * 2.5)
        bigram_word_count[w1] += 1
        bigram_word_count[w2] += 1

    bigram_component_words = set()
    for bg in list(word_freq.keys()):
        if ' ' in bg:
            for w in bg.split():
                bigram_component_words.add(w)
    for w in bigram_component_words:
        word_freq.pop(w, None)

    # Sentiment
    analyzer = SentimentIntensityAnalyzer()
    sentiment_scores = [analyzer.polarity_scores(t)['compound'] for t in all_text]
    avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0

    # Save cache
    with open(CACHE_FILE, 'w') as f:
        json.dump({
            'word_freq': dict(word_freq),
            'sentiment': avg_sentiment,
            'wave_names': wave_names,
            'drop_count': len(all_text),
            'word_count': len(word_freq),
        }, f)
    print(f'Cached to {CACHE_FILE}')

    return word_freq, avg_sentiment, wave_names, len(all_text)

def load_cache():
    """Load cached data instead of fetching from API."""
    print(f'Loading cached data from {CACHE_FILE}...')
    with open(CACHE_FILE) as f:
        d = json.load(f)
    word_freq = Counter(d['word_freq'])
    print(f'  {len(word_freq)} words, sentiment={d["sentiment"]:.3f}, {d["drop_count"]} drops')
    return word_freq, d['sentiment'], d['wave_names'], d['drop_count']

def main():
    print('=== 6529 Cloud Report v10 ===')
    print(f'Render: {RW}x{RH} → {W}x{H} (2x supersample)')
    print(f'Mask: {MASK_W}x{MASK_H} at offset ({MASK_XO}, {MASK_YO})')

    if USE_CACHE:
        word_freq, avg_sentiment, wave_names, drop_count = load_cache()
    elif DAILY_MODE:
        word_freq, avg_sentiment, wave_names, drop_count = fetch_and_process_daily()
    else:
        word_freq, avg_sentiment, wave_names, drop_count = fetch_and_process()

    if OVERRIDE_SENTIMENT is not None:
        print(f'  Override sentiment: {avg_sentiment:.3f} → {OVERRIDE_SENTIMENT}')
        avg_sentiment = OVERRIDE_SENTIMENT

    print(f'\nTop 30 words/phrases:')
    for word, count in word_freq.most_common(30):
        print(f'  {word:25s} x{count}')

    weather, colors, text_color, accent, cloud_fill_color = get_weather_palette(avg_sentiment)
    print(f'\nSentiment: {avg_sentiment:.3f} → {weather}')

    # === Render background at 2x ===
    print('Rendering weather background (2x)...')
    bg = render_weather_bg(weather, colors, RW, RH)

    # === Build cloud mask (at 2x render resolution) ===
    print('Building cloud mask...')
    mask = Image.new('L', (MASK_W, MASK_H), 255)  # 255 = blocked
    mask_draw = ImageDraw.Draw(mask)

    cloud_left = 100     # minimal blue sky on left
    cloud_top = 340       # expanded cloud, lowered for centering
    cloud_right = MASK_W - 100   # minimal blue sky on right
    cloud_bottom = MASK_H - 200  # extend bottom even further
    cloud_w = cloud_right - cloud_left
    cloud_h = cloud_bottom - cloud_top

    def blob(xf, yf, rf):
        cx = int(cloud_left + cloud_w * xf)
        cy = int(cloud_top + cloud_h * yf)
        r = int(min(cloud_w, cloud_h) * rf)
        mask_draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=0)

    # Bottom row — wide flat base, kept away from edges
    for i in range(11):
        blob(0.08 + i * 0.084, 0.84, 0.14 + 0.02 * math.sin(i * 0.9))
    # Extra lower fill row — adds mass to bottom of cloud
    for i in range(9):
        blob(0.12 + i * 0.095, 0.90, 0.11 + 0.015 * math.sin(i * 1.1))
    # Central fill — prevents donut hole
    blob(0.50, 0.52, 0.28)
    blob(0.30, 0.52, 0.20)
    blob(0.70, 0.52, 0.20)
    # Middle row — fills the body
    for i in range(9):
        blob(0.10 + i * 0.10, 0.58, 0.10 + 0.012 * math.sin(i * 1.3))
    # Top crown bumps — kept away from edges, better top-right coverage
    crown = [
        (0.08, 0.48, 0.08), (0.18, 0.35, 0.10), (0.30, 0.22, 0.11),
        (0.42, 0.10, 0.12), (0.50, 0.06, 0.13), (0.58, 0.10, 0.12),
        (0.66, 0.14, 0.11), (0.74, 0.20, 0.11), (0.82, 0.28, 0.10),
        (0.90, 0.36, 0.08),
        # Dense top-right coverage (12-3 o'clock)
        (0.62, 0.12, 0.09), (0.70, 0.16, 0.09), (0.78, 0.22, 0.09),
        (0.84, 0.30, 0.08), (0.88, 0.38, 0.07),
        (0.66, 0.08, 0.08), (0.74, 0.12, 0.08), (0.80, 0.18, 0.08),
    ]
    for xf, yf, rf in crown:
        blob(xf, yf, rf)
    # Fillers — horizontal spread, kept away from edges
    fillers = [
        (0.14, 0.68, 0.08), (0.25, 0.68, 0.08), (0.36, 0.68, 0.08),
        (0.47, 0.68, 0.08), (0.58, 0.68, 0.08), (0.69, 0.68, 0.08),
        (0.80, 0.68, 0.08), (0.91, 0.68, 0.08),
        (0.20, 0.42, 0.06), (0.32, 0.33, 0.06), (0.42, 0.24, 0.06),
        (0.52, 0.24, 0.06), (0.62, 0.30, 0.06), (0.75, 0.38, 0.06),
        (0.64, 0.20, 0.07), (0.72, 0.28, 0.07), (0.80, 0.35, 0.07),
        (0.68, 0.15, 0.06), (0.76, 0.22, 0.06), (0.84, 0.30, 0.06),
        (0.58, 0.18, 0.06), (0.86, 0.40, 0.06),
        (0.22, 0.25, 0.06), (0.28, 0.18, 0.06), (0.36, 0.22, 0.06),
        (0.16, 0.32, 0.06), (0.12, 0.40, 0.06),
        (0.40, 0.38, 0.05), (0.48, 0.35, 0.05), (0.56, 0.38, 0.05),
        (0.34, 0.45, 0.05), (0.66, 0.45, 0.05),
        # Targeted gap fillers (from scipy gap analysis)
        # Gap at 3.4oclock frac(0.47,0.22) 60x68px
        (0.47, 0.22, 0.06),
        # Gap at 1.9oclock frac(0.58,0.25) 68x34px
        (0.58, 0.25, 0.06),
        # Gap at 1.0oclock frac(0.67,0.29) 37x86px
        (0.67, 0.29, 0.06), (0.67, 0.32, 0.05),
        # Gap at 4.8oclock frac(0.37,0.29) 60x56px
        (0.37, 0.29, 0.06),
        # Gap at 5.4oclock frac(0.26,0.31) 42x37px
        (0.26, 0.31, 0.05),
        # Gap at 6.2oclock frac(0.15,0.47) 56x69px
        (0.15, 0.47, 0.06),
        # Extra connectors to prevent future gaps
        (0.45, 0.30, 0.05), (0.55, 0.32, 0.05),
        (0.70, 0.35, 0.05), (0.80, 0.42, 0.05),
        (0.85, 0.45, 0.05), (0.90, 0.48, 0.05),
        (0.25, 0.40, 0.05), (0.35, 0.38, 0.05),
    ]
    for xf, yf, rf in fillers:
        blob(xf, yf, rf)

    # Hard mask
    hard_mask = mask.filter(ImageFilter.GaussianBlur(radius=5))
    hard_mask = hard_mask.point(lambda p: 0 if p < 128 else 255)

    # === Word cloud at 2x ===
    print('Generating word cloud (2x)...')

    # Per-word sentiment colors with seasonal palettes
    vader = SentimentIntensityAnalyzer()
    word_sentiments = {}
    for word in word_freq.keys():
        word_sentiments[word] = vader.polarity_scores(word)['compound']

    # Spring palette (positive) — deep, saturated colors that pop against gray cloud
    SPRING_COLORS = [
        (40, 160, 60),     # deep grass green
        (100, 180, 50),    # forest lime
        (220, 60, 140),    # hot pink
        (240, 160, 30),    # golden yellow
        (50, 130, 220),    # deep sky blue
        (130, 80, 220),    # deep lavender
        (30, 170, 130),    # deep teal
        (230, 110, 50),    # coral
        (180, 50, 100),    # magenta
        (60, 140, 40),     # pine green
    ]
    # Halloween palette (negative) — deep, rich darks with hue still visible
    HALLOWEEN_COLORS = [
        (200, 80, 10),     # deep pumpkin
        (90, 30, 130),     # deep witch purple
        (150, 25, 25),     # blood red
        (60, 35, 20),      # dark earth
        (70, 40, 110),     # midnight purple
        (170, 70, 20),     # burnt orange
        (40, 25, 50),      # near-black purple
        (110, 50, 30),     # dark rust
        (80, 60, 20),      # dark olive
        (130, 40, 60),     # dark maroon
    ]

    # Overall sentiment drives intensity
    overall_t = max(-1, min(1, avg_sentiment))  # -1 to +1

    def color_func(word, font_size, position, orientation, **kwargs):
        s = word_sentiments.get(word, 0)
        if overall_t >= 0:
            # SPRING — use the deep palette colors directly
            base = random.choice(SPRING_COLORS)
            # Per-word: positive words get a slight brightness lift, negative words stay deep
            if s > 0.3:
                # Strong positive — brighten slightly toward full saturation
                lift = 0.1 + 0.1 * overall_t
                r = min(255, int(base[0] + (255 - base[0]) * lift))
                g = min(255, int(base[1] + (255 - base[1]) * lift))
                b = min(255, int(base[2] + (255 - base[2]) * lift))
            else:
                r, g, b = base
            return (r, g, b)
        else:
            # HALLOWEEN — use the deep palette colors, darken slightly at extremes
            base = random.choice(HALLOWEEN_COLORS)
            if s < -0.3:
                # Strong negative — darken further
                factor = 0.7 + 0.2 * (1 + overall_t)  # 0.7 at -1, 0.9 at neutral-
                r = int(base[0] * factor)
                g = int(base[1] * factor)
                b = int(base[2] * factor)
            else:
                r, g, b = base
            return (r, g, b)

    wc = WordCloud(
        width=MASK_W, height=MASK_H,
        background_color=None,
        mode='RGBA',
        mask=np.array(hard_mask),
        color_func=color_func,
        max_words=140,
        min_font_size=22,
        max_font_size=160,
        relative_scaling=0.6,
        prefer_horizontal=0.95,
        margin=10,
        collocations=False,
        random_state=42,
        font_path=FONT_PATH,
    )
    wc.generate_from_frequencies(word_freq)
    wc_img = wc.to_image()

    # Apply mask alpha — but preserve wordcloud's own transparency between words
    # wordcloud with background_color=None has transparent background between words
    # We want: inside cloud = wordcloud's own alpha (words visible, gaps transparent)
    #          outside cloud = fully transparent
    mask_inv = hard_mask.point(lambda p: 255 if p == 0 else 0)
    if wc_img.mode != 'RGBA':
        wc_img = wc_img.convert('RGBA')
    wc_arr = np.array(wc_img)
    # Combine: use minimum of wordcloud alpha and mask alpha
    # This preserves transparency between words while cutting outside cloud
    wc_arr[:, :, 3] = np.minimum(wc_arr[:, :, 3], np.array(mask_inv))
    wc_img = Image.fromarray(wc_arr, 'RGBA')

    # Check word layout
    layout = list(wc.layout_)
    print(f'Words laid out: {len(layout)}')
    if layout:
        xs = [item[2][0] for item in layout]
        ys = [item[2][1] for item in layout]
        fs = [item[1] for item in layout]
        print(f'  X range: {min(xs):.0f} - {max(xs):.0f} (mask width: {MASK_W})')
        print(f'  Y range: {min(ys):.0f} - {max(ys):.0f} (mask height: {MASK_H})')
        print(f'  Font range: {min(fs):.0f} - {max(fs):.0f}')

    # === Composite at 2x ===
    print('Compositing (2x)...')
    final = bg.convert('RGBA')

    # Cloud body fill — single layer, no shadow, no glow
    # Use hard_mask directly (0=cloud, 255=outside)
    # Invert: 255=cloud (opaque fill), 0=outside (transparent)
    cloud_mask_inv = hard_mask.point(lambda p: 255 - p)  # 255 inside cloud, 0 outside
    # Place in full canvas at offset
    cloud_mask_full = Image.new('L', (RW, RH), 0)
    cloud_mask_full.paste(cloud_mask_inv, (MASK_XO, MASK_YO))
    cloud_mask_blurred = cloud_mask_full.filter(ImageFilter.GaussianBlur(radius=80))  # feathered edge
    cloud_fill = Image.new('RGBA', (RW, RH), (0, 0, 0, 0))
    cf_data = np.array(cloud_fill)
    fill_color = cloud_fill_color  # grayscale from palette
    cf_data[:, :, 0] = fill_color[0]
    cf_data[:, :, 1] = fill_color[1]
    cf_data[:, :, 2] = fill_color[2]
    cf_data[:, :, 3] = np.array(cloud_mask_blurred)  # 100% opacity inside cloud, feathered to 0 outside
    cloud_fill = Image.fromarray(cf_data, 'RGBA')
    final = Image.alpha_composite(final, cloud_fill)

    # Paste word cloud at offset
    wc_full = Image.new('RGBA', (RW, RH), (0, 0, 0, 0))
    wc_full.paste(wc_img, (MASK_XO, MASK_YO))
    final = Image.alpha_composite(final, wc_full)

    # === Footer (at 2x, will be downscaled with everything else) ===
    draw = ImageDraw.Draw(final)
    sub_font = ImageFont.truetype(FONT_PATH, 48)  # 2x of 24
    small_font = ImageFont.truetype(FONT_REGULAR, 32)  # 2x of 16
    tiny_font = ImageFont.truetype(FONT_REGULAR, 28)  # 2x of 14

    # Footer backing — compact
    footer_overlay = Image.new('RGBA', (RW, RH), (0, 0, 0, 0))
    footer_draw = ImageDraw.Draw(footer_overlay)
    footer_h = 160  # 2x of 80 — more compact
    for y in range(footer_h):
        alpha = int(90 * (y / footer_h))
        footer_draw.line([(0, RH - footer_h + y), (RW, RH - footer_h + y)],
            fill=(*colors[2], alpha))
    final = Image.alpha_composite(final, footer_overlay)
    draw = ImageDraw.Draw(final)

    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    footer_text = f'{weather}  ·  Sentiment {avg_sentiment:+.2f}  ·  {drop_count} drops  ·  {len(word_freq)} words  ·  {ts}'
    draw.text((50, RH - 140), footer_text, fill=accent, font=sub_font)

    # Wave list — 1 line only, truncated
    max_chars = 130
    wave_line = '  ·  '.join(wave_names)
    if len(wave_line) > max_chars:
        wave_line = wave_line[:max_chars-3] + '...'
    draw.text((50, RH - 80), wave_line, fill=text_color, font=small_font)

    # === Downscale 2x → 1x for crisp text ===
    print('Downscaling 2x → 1x...')
    final_rgb = final.convert('RGB')
    final_small = final_rgb.resize((W, H), Image.LANCZOS)
    out_png = OUTPUT_PATH if OUTPUT_PATH else '/tmp/6529_weather.png'
    final_small.save(out_png, 'PNG', quality=95)
    print(f'Saved PNG: {out_png}')

    # === Export cloud SVG path for HTML (at 1x coordinates) ===
    import cv2
    mask_arr = np.array(hard_mask)
    contours, _ = cv2.findContours(
        (mask_arr == 0).astype(np.uint8) * 255,
        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS
    )
    cloud_path_str = ''
    if contours:
        largest = max(contours, key=cv2.contourArea)
        epsilon = 3.0
        approx = cv2.approxPolyDP(largest, epsilon, True)
        for i, pt in enumerate(approx):
            # Scale from 2x mask coords to 1x canvas coords + offset
            px = int(pt[0][0] / SS + MASK_XO / SS)
            py = int(pt[0][1] / SS + MASK_YO / SS)
            if i == 0:
                cloud_path_str += f'M{px},{py}'
            else:
                cloud_path_str += f' L{px},{py}'
        cloud_path_str += ' Z'

    # === Export PNG as base64 for HTML embedding ===
    import io as _io
    png_buf = _io.BytesIO()
    final_small.save(png_buf, format='PNG')
    png_b64 = base64.b64encode(png_buf.getvalue()).decode()

    # Font as base64
    with open(FONT_PATH, 'rb') as f:
        font_b64 = base64.b64encode(f.read()).decode()

    # === Build HTML — static PNG + weather-only animations ===
    weather_lower = weather.lower().replace(' ', '_')
    is_positive = avg_sentiment > 0.2
    is_negative = avg_sentiment < -0.2
    is_rainy = 'rainy' in weather_lower or 'stormy' in weather_lower
    is_stormy = 'stormy' in weather_lower
    is_sunny = 'sunny' in weather_lower

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>6529 Cloud Report</title>
<style>
@font-face {{
  font-family: 'DejaVuSansBold';
  src: url(data:font/woff;base64,{font_b64}) format('woff');
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  background: #1a1a1a;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  font-family: 'DejaVuSansBold', sans-serif;
}}
.scene {{
  position: relative;
  width: {W}px;
  height: {H}px;
  overflow: hidden;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}}
.cloud-img {{
  position: absolute;
  top: 0; left: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
}}
/* Weather effect layers (above image, below nothing — purely decorative) */
.effects {{
  position: absolute;
  top: 0; left: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
  overflow: hidden;
  border-radius: 12px;
}}
/* Cloud breathing — subtle scale pulse on the entire image */
@keyframes cloudBreathe {{
  0%, 100% {{ transform: scale(1); }}
  50% {{ transform: scale(1.015); }}
}}
.cloud-img {{
  animation: cloudBreathe 8s ease-in-out infinite;
  transform-origin: center 40%;
}}
/* Vignette pulse */
@keyframes vignettePulse {{
  0%, 100% {{ opacity: 0.3; }}
  50% {{ opacity: 0.5; }}
}}
.vignette {{
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 3;
  pointer-events: none;
  border-radius: 12px;
  box-shadow: inset 0 0 100px rgba(0,0,0,0.4);
  animation: vignettePulse 6s ease-in-out infinite;
}}
'''

    # Weather-specific CSS animations
    if is_sunny:
        html += '''
/* Sun rays */
@keyframes sunRotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.sun-rays {
  position: absolute;
  top: -100px; right: -100px;
  width: 400px; height: 400px;
  z-index: 2;
  pointer-events: none;
  animation: sunRotate 120s linear infinite;
  opacity: 0.15;
}
.sun-rays::before {
  content: '';
  position: absolute;
  top: 50%; left: 50%;
  width: 600px; height: 600px;
  transform: translate(-50%, -50%);
  background: conic-gradient(
    from 0deg,
    rgba(255,200,100,0) 0deg,
    rgba(255,200,100,0.3) 10deg,
    rgba(255,200,100,0) 20deg,
    rgba(255,200,100,0) 40deg,
    rgba(255,200,100,0.3) 50deg,
    rgba(255,200,100,0) 60deg,
    rgba(255,200,100,0) 80deg,
    rgba(255,200,100,0.3) 90deg,
    rgba(255,200,100,0) 100deg,
    rgba(255,200,100,0) 360deg
  );
}
'''

    if is_rainy or is_stormy:
        html += f'''
/* Rain drops */
@keyframes rainFall {{
  0% {{ transform: translateY(-20px); opacity: 0; }}
  10% {{ opacity: 0.6; }}
  90% {{ opacity: 0.6; }}
  100% {{ transform: translateY({H+20}px); opacity: 0; }}
}}
.rain {{
  position: absolute;
  width: 2px;
  background: linear-gradient(to bottom, transparent, rgba(150,180,220,0.5));
  z-index: 2;
  pointer-events: none;
  border-radius: 2px;
}}
'''

    if is_stormy:
        html += '''
/* Lightning flash */
@keyframes lightningFlash {
  0%, 95%, 100% { opacity: 0; }
  96%, 97% { opacity: 0.7; }
  98% { opacity: 0; }
  99% { opacity: 0.5; }
}
.lightning {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 60%;
  z-index: 2;
  pointer-events: none;
  background: radial-gradient(ellipse at 50% 20%,
    rgba(255,240,200,0.8) 0%,
    rgba(255,240,200,0) 60%);
  animation: lightningFlash 12s ease-in-out infinite;
}
'''

    # Floating particles (all weather)
    html += '''
/* Floating ambient particles */
@keyframes particleFloat {
  0%, 100% { transform: translate(0, 0); opacity: 0.3; }
  25% { transform: translate(10px, -15px); opacity: 0.5; }
  50% { transform: translate(-5px, -25px); opacity: 0.3; }
  75% { transform: translate(-12px, -10px); opacity: 0.4; }
}
.particle {
  position: absolute;
  width: 3px; height: 3px;
  border-radius: 50%;
  z-index: 2;
  pointer-events: none;
  animation: particleFloat ease-in-out infinite;
}
'''

    html += f'''
</style>
</head>
<body>
<div class="scene">
  <img class="cloud-img" src="data:image/png;base64,{png_b64}" alt="6529 Cloud Report">
  <div class="effects" id="effects"></div>
  <div class="vignette"></div>
'''

    if is_sunny:
        html += '  <div class="sun-rays"></div>\n'

    if is_stormy:
        html += '  <div class="lightning"></div>\n'

    # Generate rain drops via JS
    if is_rainy or is_stormy:
        num_rain = 60 if is_stormy else 30
        html += f'''  <script>
  (function() {{
    var effects = document.getElementById('effects');
    // Rain drops
    for (var i = 0; i < {num_rain}; i++) {{
      var drop = document.createElement('div');
      drop.className = 'rain';
      drop.style.left = (Math.random() * 100) + '%';
      drop.style.height = (12 + Math.random() * 28) + 'px';
      drop.style.top = '-30px';
      var dur = 0.8 + Math.random() * 1.2;
      drop.style.animation = 'rainFall ' + dur + 's linear infinite';
      drop.style.animationDelay = (Math.random() * 2) + 's';
      effects.appendChild(drop);
    }}
'''

    # Particles (all weather)
    accent_rgb = f'rgba({accent[0]},{accent[1]},{accent[2]},0.4)'
    is_rainy_js = 'true' if (is_rainy or is_stormy) else 'false'
    html += f'''    // Floating particles
    for (var i = 0; i < 20; i++) {{
      var p = document.createElement('div');
      p.className = 'particle';
      p.style.left = (Math.random() * 100) + '%';
      p.style.top = (20 + Math.random() * 60) + '%';
      p.style.background = '{accent_rgb}';
      p.style.animationDuration = (6 + Math.random() * 8) + 's';
      p.style.animationDelay = (Math.random() * 4) + 's';
      effects.appendChild(p);
    }}
  }})();
  </script>
'''

    html += '''</div>
</body>
</html>'''

    with open(OUTPUT_HTML, 'w') as f:
        f.write(html)
    print(f'Saved HTML: {OUTPUT_HTML}')
    print(f'\nWeather: {weather} | Sentiment: {avg_sentiment:+.3f} | Words: {len(word_freq)}')
    print(f'Cloud path: {len(cloud_path_str)} chars')

if __name__ == '__main__':
    main()