"""
======================================================================
PHASE 2: UNIFIED BULK EXTRACTION (WITH BUILT-IN 403 TLS BYPASS)
======================================================================
Uses standard `requests` for speed, but automatically falls back to
`curl_cffi` if it hits a 403 Forbidden block (e.g., HT, IE).
"""
!pip install -q trafilatura requests curl_cffi

import logging
import os
import glob
import pandas as pd
import trafilatura
import requests
from curl_cffi import requests as cffi_requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.auto import tqdm

# Silence the console spam
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("trafilatura").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("curl_cffi").setLevel(logging.ERROR)

# 1. PATHS
INPUT_CSV = ''
CHECKPOINT_DIR = ''
FINAL_OUT = ''
OLD_CKPT = ''

os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Standard headers for the first attempt
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
    'Referer': 'https://www.google.com/',
    'Connection': 'keep-alive'
}

# 2. EXTRACTION FUNCTION (With Smart 403 Fallback)
def extract_and_log(row):
    url = row['url']
    try:
        # ATTEMPT 1: Standard requests (Fast, works for 90% of sites)
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=15)

        # ATTEMPT 2: If blocked by 403, pivot to curl_cffi to bypass TLS fingerprinting
        if response.status_code == 403:
            response = cffi_requests.get(url, impersonate="chrome", timeout=15)

        if response.status_code != 200:
            return {'text': None, 'status': f'fetch_failed_{response.status_code}'}

        html = response.text

        # Pass the HTML to trafilatura for boilerplate removal
        text = trafilatura.extract(html, favor_precision=True)

        if not text or len(text) < 200:
            return {'text': None, 'status': 'extract_failed_or_short'}

        return {'text': text, 'status': 'kept'}

    except requests.exceptions.Timeout:
        return {'text': None, 'status': 'fetch_failed_timeout'}
    except Exception:
        # Catches curl_cffi errors, connection resets, etc.
        return {'text': None, 'status': 'exception'}

# 3. RESUME LOGIC
print("Checking for previous progress...")
df_urls = pd.read_csv(INPUT_CSV)
done_urls = set()

if os.path.exists(OLD_CKPT):
    df_old = pd.read_csv(OLD_CKPT, usecols=['url'])
    done_urls.update(df_old['url'].tolist())
    print(f"✓ Loaded {len(df_old):,} URLs from old monolithic checkpoint.")

batch_files = sorted(glob.glob(os.path.join(CHECKPOINT_DIR, 'batch_*.csv')))
if batch_files:
    for f in batch_files:
        df_b = pd.read_csv(f, usecols=['url'])
        done_urls.update(df_b['url'].tolist())
    print(f"✓ Loaded {len(batch_files)} batch files ({len(done_urls):,} total URLs processed).")

df_todo = df_urls[~df_urls['url'].isin(done_urls)].copy()
print(f"✓ Resuming: {len(df_todo):,} URLs remaining to extract.\n")

next_batch_num = len(batch_files) + 1

# 4. EXTRACTION LOOP
def process_batch(batch_df):
    batch_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(extract_and_log, row): row for _, row in batch_df.iterrows()}

        for future in tqdm(as_completed(futures), total=len(futures), leave=False):
            row = futures[future]
            result = future.result()
            batch_results.append({
                'url': row['url'], 'date': row['date'],
                'newspaper': row['newspaper'], 'language': row['language'],
                'text': result['text'], 'status': result['status']
            })
    return batch_results

CHUNK_SIZE = 10000
total_batches = (len(df_todo) // CHUNK_SIZE) + (1 if len(df_todo) % CHUNK_SIZE != 0 else 0)
cumulative_kept = 0
cumulative_failed = 0

for i in range(0, len(df_todo), CHUNK_SIZE):
    batch_df = df_todo.iloc[i:i+CHUNK_SIZE]
    batch_num_display = (i // CHUNK_SIZE) + 1

    batch_results = process_batch(batch_df)
    batch_df_out = pd.DataFrame(batch_results)

    batch_file = os.path.join(CHECKPOINT_DIR, f'batch_{next_batch_num:04d}.csv')
    try:
        batch_df_out.to_csv(batch_file, index=False)
        if not os.path.exists(batch_file) or os.path.getsize(batch_file) < 100:
            raise IOError("Drive write failed or file is empty.")
    except Exception as e:
        print(f"🚨 DRIVE WRITE ERROR on batch {next_batch_num}: {e}")
        print("   Retrying once to local disk as fallback...")
        batch_df_out.to_csv(f'/content/batch_{next_batch_num:04d}_FALLBACK.csv', index=False)

    kept = len(batch_df_out[batch_df_out['status'] == 'kept'])
    failed = len(batch_df_out[batch_df_out['status'] != 'kept'])
    cumulative_kept += kept
    cumulative_failed += failed

    print(f"✓ Batch {batch_num_display}/{total_batches} (File: {next_batch_num:04d}) | "
          f"Kept: {kept} | Failed: {failed} | "
          f"Running Total: {cumulative_kept:,} kept, {cumulative_failed:,} failed")

    next_batch_num += 1

# 5. FINAL CONSOLIDATION
print("\n✓ Extraction loop complete. Consolidating final dataset...")
all_batch_files = sorted(glob.glob(os.path.join(CHECKPOINT_DIR, 'batch_*.csv')))

if not all_batch_files and os.path.exists(OLD_CKPT):
    all_batch_files = [OLD_CKPT]

if all_batch_files:
    df_list = [pd.read_csv(f) for f in all_batch_files]
    df_all = pd.concat(df_list, ignore_index=True)

    df_final = df_all[df_all['status'] == 'kept'].drop(columns=['status'])
    df_final.to_csv(FINAL_OUT, index=False)

    print("\n" + "="*60)
    print("EXTRACTION COMPLETE")
    print("="*60)
    print(f"Total Articles Extracted: {len(df_final):,}")
    print(f"Total Fetch/Extract Failures: {len(df_all[df_all['status'] != 'kept']):,}")

    failures = df_all[df_all['status'] != 'kept']
    if len(failures) > 0:
        print("\n--- Failure Breakdown ---")
        print(failures['status'].value_counts())

        print("\n--- Per-Newspaper Success Rates ---")
        for paper in df_all['newspaper'].unique():
            paper_all = len(df_all[df_all['newspaper'] == paper])
            paper_kept = len(df_final[df_final['newspaper'] == paper])
            rate = paper_kept / paper_all if paper_all > 0 else 0
            print(f"  {paper}: {paper_kept:,}/{paper_all:,} ({rate:.1%} success)")

    print(f"\n✅ Clean corpus saved to: {FINAL_OUT}")
    print("✅ Ready for BERTopic clustering.")
else:
    print("⚠️ No batch files found to consolidate.")
