import requests
from bs4 import BeautifulSoup

def fetch_free_proxies():
    url = "https://free-proxy-list.net/"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="table-striped")
    rows = table.find_all("tr")[1:]  # skip header

    proxies = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 8:
            ip = cols[0].text.strip()
            port = cols[1].text.strip()
            https = cols[6].text.strip()  # 'yes' or 'no'
            if https == "yes":
                proxy_str = f"https://{ip}:{port}"
            else:
                proxy_str = f"http://{ip}:{port}"
            proxies.append(proxy_str)
    return proxies

# Get fresh proxies
fresh_list = fetch_free_proxies()
print(f"Got {len(fresh_list)} proxies from free-proxy-list.net")
print(fresh_list[:5])  # print first 5 proxies