import json
import urllib.request
from datetime import datetime, timezone

AIRPORTS = [
    "RJCO", "RJEC", "RJCK", "RJCB",
    "RJSS", "RJSK",
    "RJTT", "RJAA",
    "RJGG", "RJNA",
    "RJOO", "RJBB", "RJBE",
    "RJOA", "RJOB",
    "RJOT", "RJOM",
    "RJFF",
    "ROAH",
]

def fetch_metar(codes):
    ids = ",".join(codes)
    url = f"https://aviationweather.gov/api/data/metar?ids={ids}&format=json&hours=2&mostRecent=true&taf=false"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "AirportForcast/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def main():
    result = {}
    try:
        data = fetch_metar(AIRPORTS)
        for m in data:
            code = m.get("icaoId") or m.get("stationId", "")
            if not code:
                continue
            result[code] = {
                "temp":       m.get("temp"),
                "dewp":       m.get("dewp"),
                "wdir":       m.get("wdir"),
                "wspd":       m.get("wspd"),
                "wgst":       m.get("wgst"),
                "reportTime": m.get("reportTime"),
            }
        print(f"OK: {len(result)} airports fetched")
    except Exception as e:
        print(f"ERROR: {e}")

    result["_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open("metar.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
