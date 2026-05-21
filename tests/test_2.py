import requests
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from test import fetch_free_proxies
# -----------------------------
# 1. Your proxy list (free)
# -----------------------------
proxy_candidates = fetch_free_proxies()
PROXY_POOL = [
    'http://62.113.119.14:8080', 
    'http://8.219.97.248:80', 
    'http://168.110.52.228:3128', 
    'http://200.24.130.150:999', 
    'http://190.94.218.59:999', 
    'http://14.143.222.113:57788', 
    'http://8.211.166.184:8081', 
    'http://177.93.48.139:999', 
    'http://139.5.16.66:8080', 
    'http://89.208.106.138:10808', 
    'http://187.111.144.102:8080', 
    'http://103.231.236.202:8182', 
    'http://103.68.214.164:8080', 
    'http://103.162.63.226:8082', 
    'http://72.11.150.178:6005', 
    'http://168.222.254.136:8888', 
    'http://150.107.140.238:3128', 
    'http://81.26.190.143:1080'
]

TEST_URL = "https://httpbin.org/ip"   # reveals which IP is visible to the server
TIMEOUT = 10                          # seconds

# # -----------------------------
# # 2. Function to test a single proxy
# # -----------------------------
# def test_proxy(proxy_url):
#     proxies = {
#         "http": proxy_url,
#         "https": proxy_url,
#     }
#     try:
#         resp = requests.get(TEST_URL, proxies=proxies, timeout=TIMEOUT)
#         if resp.status_code == 200:
#             data = resp.json()
#             ip_visible = data.get("origin", "unknown")
#             print(f"✅ WORKING | Proxy: {proxy_url}  ->  Server sees IP: {ip_visible}")
#             return proxy_url     # return the proxy if it worked
#         else:
#             print(f"❌ FAILED  | Proxy: {proxy_url}  (HTTP {resp.status_code})")
#     except Exception as e:
#         print(f"❌ FAILED  | Proxy: {proxy_url}  ({type(e).__name__}: {str(e)[:80]})")
#     return None

# # -----------------------------
# # 3. Test all proxies (concurrently for speed)
# # -----------------------------
# working_pool = []
# print("Testing proxies...\n")
# with ThreadPoolExecutor(max_workers=5) as executor:
#     futures = {executor.submit(test_proxy, p): p for p in proxy_candidates}
#     for future in as_completed(futures):
#         result = future.result()
#         if result:
#             working_pool.append(result)

# print(f"\nWorking proxies: {len(working_pool)} / {len(proxy_candidates)}")
# if working_pool:
#     print("Working pool:", working_pool)
# else:
#     print("No working proxies found. Free proxies are often dead or blocked – try a fresh list or use a paid service.")

# -----------------------------
# 4. Example: use the working pool for your actual API calls
# -----------------------------
working_pool = PROXY_POOL
if working_pool:
    def fetch_with_random_proxy(url, retries=2):
        for attempt in range(retries):
            proxy_url = random.choice(working_pool)
            proxies = {"http": proxy_url, "https": proxy_url}
            try:
                r = requests.get(url, proxies=proxies, timeout=15)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                print(f"Proxy {proxy_url} failed: {e}. Retrying...")
                # Optionally remove dead proxy from pool
                # working_pool.remove(proxy_url)
        return None

    # Test call to AlphaXiv (or any other API)
    paper_preview = fetch_with_random_proxy(
        "https://api.alphaxiv.org/papers/v3/2304.08485/preview"
    )
    if paper_preview:
        print("\nSuccessfully fetched paper preview (rotated IP).")
        print("Title:", paper_preview.get("title", "N/A"))
    else:
        print("\nFailed to fetch paper preview after retries.")