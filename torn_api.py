# torn_api.py

import requests
import time

CACHE = {}
CACHE_DURATION = 60  # seconds

def fetch_user_cached(username, api_key):
    now = time.time()
    if username in CACHE and now - CACHE[username]['ts'] < CACHE_DURATION:
        return CACHE[username]['data']

    url = f"https://api.torn.com/user/{username}?selections=basic,stats,personalstats,networth&key={api_key}"
    res = requests.get(url)
    if res.status_code != 200:
        return None

    data = res.json()
    if 'error' in data:
        return None

    CACHE[username] = { 'ts': now, 'data': data }
    return data


def fetch_status(username, api_key):
    url = f"https://api.torn.com/user/{username}?selections=status&key={api_key}"
    try:
        res = requests.get(url)
        data = res.json()
        return data.get("status", {})
    except:
        return {}


def fetch_faction_members(faction_id, api_key):
    url = f"https://api.torn.com/faction/{faction_id}?selections=basic,stats&key={api_key}"
    try:
        res = requests.get(url)
        return res.json().get("members", {})
    except:
        return {}
