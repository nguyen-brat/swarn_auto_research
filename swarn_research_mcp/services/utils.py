import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import random
from pathlib import Path

import requests

from .external.get_active_proxy import get_working_proxies
from .external.get_proxy_free import fetch_free_proxies

DEFAULT_DIRECT_RETRIES = 2
DEFAULT_PROXY_RETRIES = 2
PROXY_FILE = Path(__file__).resolve().parent / "external" / "proxy.txt"


def _load_proxy_pool():
    if not PROXY_FILE.exists():
        proxy_list = fetch_free_proxies()
        working_proxies = get_working_proxies(proxy_list)
        PROXY_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROXY_FILE.write_text(
            "".join(f"{proxy}\n" for proxy in working_proxies),
            encoding="utf-8",
        )
        return working_proxies

    return [
        line.strip()
        for line in PROXY_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


PROXY_POOL = _load_proxy_pool()


async def run_blocking(func, *args, **kwargs):
    """Run a blocking service call without using asyncio's default executor."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
    finally:
        executor.shutdown(wait=True)


def _request(
    method,
    url,
    *,
    method_name,
    timeout,
    return_json,
    direct_retries,
    proxy_retries,
    **kwargs,
):
    last_error = None

    for attempt in range(1, direct_retries + 1):
        try:
            response = method(url, timeout=timeout, **kwargs)
            print(f"  {response.request.method if getattr(response, 'request', None) else method_name} {response.url}")
            print(f"  Status: {response.status_code}")
            if response.status_code == 429:
                response.raise_for_status()
            response.raise_for_status()
            return response.json() if return_json else response.text
        except requests.RequestException as exc:
            if getattr(getattr(exc, "response", None), "status_code", None) == 429:
                raise
            last_error = exc
            print(f"  Direct request attempt {attempt}/{direct_retries} failed: {exc}")

    if not PROXY_POOL:
        raise last_error

    for attempt in range(1, proxy_retries + 1):
        proxy_url = random.choice(PROXY_POOL)
        proxies = {"http": proxy_url, "https": proxy_url}
        try:
            response = method(url, timeout=timeout, proxies=proxies, **kwargs)
            print(f"  Falling back to proxy {proxy_url}")
            print(f"  {response.request.method if getattr(response, 'request', None) else method_name} {response.url}")
            print(f"  Status: {response.status_code}")
            response.raise_for_status()
            return response.json() if return_json else response.text
        except requests.RequestException as exc:
            last_error = exc
            print(f"  Proxy request attempt {attempt}/{proxy_retries} failed via {proxy_url}: {exc}")

    raise last_error


def http_get(
    url,
    params=None,
    headers=None,
    timeout=30,
    return_json=True,
    direct_retries=DEFAULT_DIRECT_RETRIES,
    proxy_retries=DEFAULT_PROXY_RETRIES,
):
    """Thin wrapper for GET requests shared by service modules."""
    return _request(
        requests.get,
        url,
        method_name="GET",
        params=params,
        headers=headers,
        timeout=timeout,
        return_json=return_json,
        direct_retries=direct_retries,
        proxy_retries=proxy_retries,
    )


def http_post(
    url,
    payload,
    params=None,
    headers=None,
    timeout=30,
    return_json=True,
    direct_retries=DEFAULT_DIRECT_RETRIES,
    proxy_retries=DEFAULT_PROXY_RETRIES,
):
    """Thin wrapper for POST requests shared by service modules."""
    return _request(
        requests.post,
        url,
        method_name="POST",
        json=payload,
        params=params,
        headers=headers,
        timeout=timeout,
        return_json=return_json,
        direct_retries=direct_retries,
        proxy_retries=proxy_retries,
    )


def safe_get(obj, path, default=None):
    # Split "a.b.c" into ['a', 'b', 'c']
    keys = path.split('.') if isinstance(path, str) else path
    
    for key in keys:
        try:
            if isinstance(obj, dict):
                # Exact match first; if missing, try case-insensitive
                if key in obj:
                    obj = obj[key]
                else:
                    obj = next(v for k, v in obj.items() if str(k).lower() == str(key).lower())
            elif isinstance(obj, (list, tuple)):
                obj = obj[int(key)]
            else:
                return default
        except (KeyError, ValueError, IndexError, StopIteration, TypeError):
            # StopIteration handles case-insensitive lookup failure
            # TypeError/KeyError handles if obj becomes None or lacks the key
            return default
            
        if obj is None:
            return default
            
    return obj

# Testing with your sample
if __name__ == "__main__":
    sample = {
        'externalIds': {'ArXiv': '2604.24929'},
        'title': 'GAIA-v2-LILT',
    }
    
    print(safe_get(sample, "externalIds.Arxiv"))  # Outputs: 2604.24929
    print(safe_get(sample, "non.existent.path")) # Outputs: None
