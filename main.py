import os, json, hashlib
from datetime import datetime, timedelta, timezone
import requests

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV = timezone(timedelta(hours=2))

# ---------- НАЛАШТУВАННЯ ----------
TOKEN = os.environ.get("TG_TOKEN") or ""
CHAT  = os.environ.get("TG_CHAT")  or ""   # add secret
API   = "https://api-poweron.toe.com.ua/api/a_gpv_g"
GROUP = "5.2"
ADDR_KEY  = "2203940014130"
DEBUG_KEY = "MjIwMzkvNDAwMTQvMTMw"
DAYS_AHEAD = 1
ADDRESS_LABEL = "selo, vylesha, number"
# -----------------------------------

BASE  = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state.json")
RAW   = os.path.join(BASE, "response.json")

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "uk,en-US;q=0.9,en;q=0.8",
    "cache-control": "no-cache", "pragma": "no-cache",
    "origin": "https://poweron.toe.com.ua", "referer": "https://poweron.toe.com.ua/",
    "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/158.0.0.0 Mobile Safari/537.36",
    "x-debug-key": DEBUG_KEY,
}

ICON = {"0": "💚", "1": "🔴", "10": "🟠"}
TEXT = {"0": "є світло", "1": "немає світла", "10": "можливе відключення"}


def tg_send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT, "text": text[:4000]}
    r = requests.post(url, data=data, timeout=30)
    
    # Якщо статус не 200 OK, друкуємо детальну відповідь від Telegram
    if r.status_code != 200:
        print(f"❌ ПОМИЛКА TELEGRAM API: {r.status_code}")
        print(f"Відповідь сервера: {r.text}")
        
    r.raise_for_status()


def fetch():
    today = datetime.now(KYIV).date()
    day0  = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    after = day0 - timedelta(hours=12)
    before = day0 + timedelta(days=1 + DAYS_AHEAD)
    fmt = "%Y-%m-%dT%H:%M:%S"
    url = (f"{API}?before={before.strftime(fmt)}%2B00:00&after={after.strftime(fmt)}%2B00:00"
           f"&group[]={GROUP}&time={ADDR_KEY}&_={int(datetime.now().timestamp()*1000)}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def members(data):
    if isinstance(data, dict):
        return data.get("hydra:member", data.get("member", []))
    return data if isinstance(data, list) else []


def end_of(slot):
    t = datetime.strptime(slot, "%H:%M") + timedelta(minutes=30)
    s = t.strftime("%H:%M")
    return "24:00" if s == "00:00" else s


def spans(times):
    out = []
    for slot in sorted(times):
        st, end = str(times[slot]), end_of(slot)
        if out and out[-1][2] == st and out[-1][1] == slot:
            out[-1][1] = end
        else:
            out.append([slot, end, st])
    return out


def minutes(a, b):
    f = lambda x: int(x[:2]) * 60 + int(x[3:5])
    return f(b) - f(a)


def format_day(date, created, times):
    now = datetime.now(KYIV)
    day = datetime.strptime(date, "%Y-%m-%d").date()
    if day < now.date():   now_min = 24 * 60 + 1
    elif day > now.date(): now_min = -1
    else:                  now_min = now.hour * 60 + now.minute

    d   = day.strftime("%d.%m.%Y")
    upd = created[11:16] if len(created) >= 16 else ""
    head = f"📅 {d} · Черга {GROUP}" + (f" (станом на {upd})" if upd else "")

    sp = spans(times)
    if all(s == "0" for _, _, s in sp):
        return head + "\n✅ Відключень не заплановано"

    lines = []
    for a, b, s in sp:
        mark = "| " if minutes("00:00", b) <= now_min else ""
        lines.append(f"{mark}{ICON.get(s, '❔')} {a}–{b}  {TEXT.get(s, 'стан ' + s)}")

    off = sum(minutes(a, b) for a, b, s in sp if s == "1")
    total = f"\nБез світла: {off // 60} год {off % 60:02d} хв" if off else ""
    return head + "\n" + "\n".join(lines) + total


def check_and_notify():
    data = fetch()
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    by_date = {}
    for rec in members(data):
        g = (rec.get("dataJson") or {}).get(GROUP)
        if not g or "times" not in g:
            continue
        date = rec["dateGraph"][:10]
        if date not in by_date or rec["dateCreate"] > by_date[date]["dateCreate"]:
            by_date[date] = {"dateCreate": rec["dateCreate"], "times": g["times"]}

    if not by_date:
        print("У відповіді немає графіка для групи", GROUP); return

    snapshot = {d: v["times"] for d, v in sorted(by_date.items())}
    h = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()

    old = None
    if os.path.exists(STATE):
        try: old = json.load(open(STATE, encoding="utf-8")).get("hash")
        except Exception: pass

    if h == old:
        print("Без змін"); return

    head = "⚡ Графік оновився" if old else "✅ Моніторинг запущено"
    body = "\n\n".join(format_day(d, v["dateCreate"], v["times"]) for d, v in sorted(by_date.items()))
    tg_send(f"{head}\n{ADDRESS_LABEL}\n\n{body}")
    json.dump({"hash": h}, open(STATE, "w", encoding="utf-8"))
    print("Надіслано")


if __name__ == "__main__":
    if not TOKEN or not CHAT:
        raise SystemExit("Задайте secrets TG_TOKEN і TG_CHAT у налаштуваннях репо.")
    check_and_notify()   #cron workflow
