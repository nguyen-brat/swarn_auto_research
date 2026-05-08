import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from .get_proxy_free import fetch_free_proxies

TEST_URL = "https://httpbin.org/ip"   # reveals which IP is visible to the server
TIMEOUT = 10                          # seconds

# -----------------------------
# 2. Function to test a single proxy
# -----------------------------
def test_proxy(proxy_url):
    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }
    try:
        resp = requests.get(TEST_URL, proxies=proxies, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            ip_visible = data.get("origin", "unknown")
            print(f"✅ WORKING | Proxy: {proxy_url}  ->  Server sees IP: {ip_visible}")
            return proxy_url     # return the proxy if it worked
        else:
            print(f"❌ FAILED  | Proxy: {proxy_url}  (HTTP {resp.status_code})")
    except Exception as e:
        print(f"❌ FAILED  | Proxy: {proxy_url}  ({type(e).__name__}: {str(e)[:80]})")
    return None

# -----------------------------
# 3. Test all proxies (concurrently for speed)
# -----------------------------
def get_working_proxies(proxy_list):
    working_pool = []
    print("Testing proxies...\n")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(test_proxy, p): p for p in proxy_list}
        for future in as_completed(futures):
            result = future.result()
            if result:
                working_pool.append(result)
    print(f"\nWorking proxies: {len(working_pool)} / {len(proxy_list)}")
    if working_pool:
        print("Working pool:", working_pool)
    else:
        print("No working proxies found. Free proxies are often dead or blocked – try a fresh list or use a paid service.")
    return working_pool


if __name__ == "__main__":
    proxy_candidates = fetch_free_proxies()
    get_working_proxies(proxy_candidates)
