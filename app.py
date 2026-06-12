"""
vapor app.py  - ベイパー予報 Webアプリ
ユニークURLで各ユーザーの設定を管理する
"""
import base64
import io
import json
import math
import os
import uuid
import requests
import streamlit as st
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFilter

try:
    from astral import LocationInfo as _AstralLocation
    from astral.moon import phase as _astral_moon_phase, moonrise as _astral_moonrise
    _ASTRAL_OK = True
except ImportError:
    _ASTRAL_OK = False

try:
    import ephem as _ephem
    _EPHEM_OK = True
except ImportError:
    _EPHEM_OK = False

JST = timezone(timedelta(hours=9))


def _bezier(p0, p1, p2, n=80):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def _make_icon():
    size = 180
    img = Image.new("RGBA", (size, size), (18, 18, 40, 255))
    cx = size // 2

    # cab glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle([cx - 52, 22, cx + 52, 80], radius=14, fill=(80, 160, 255, 65))
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)
    body = (200, 225, 252, 255)
    cab  = (120, 195, 255, 255)
    hi   = (215, 238, 255, 130)

    # base platform
    draw.rounded_rectangle([cx - 56, 144, cx + 56, 162], radius=6, fill=body)
    # lower widening
    draw.rounded_rectangle([cx - 38, 118, cx + 38, 148], radius=5, fill=body)
    # shaft
    draw.rectangle([cx - 13, 72, cx + 13, 122], fill=body)
    # collar (overhang below cab)
    draw.rounded_rectangle([cx - 34, 66, cx + 34, 78], radius=4, fill=body)
    # cab
    draw.rounded_rectangle([cx - 46, 24, cx + 46, 72], radius=9, fill=cab)
    # cab glass highlight
    draw.rounded_rectangle([cx - 39, 29, cx + 39, 52], radius=7, fill=hi)
    # antenna mast
    draw.line([cx, 7, cx, 24], fill=(255, 255, 255, 220), width=3)
    # beacon
    draw.ellipse([cx - 5, 3, cx + 5, 13], fill=(255, 220, 70, 255))

    return img


# モジュールロード時に生成（PIL Image → page_icon に直接渡す / base64 → apple-touch-icon JS注入用）
_ICON_IMG = _make_icon()
_buf = io.BytesIO()
_ICON_IMG.convert("RGB").save(_buf, format="PNG")
_ICON_B64 = base64.b64encode(_buf.getvalue()).decode()
USERS_DIR = os.path.join(os.path.dirname(__file__), "users")
os.makedirs(USERS_DIR, exist_ok=True)

AIRPORT_COORDS = {
    "RJCO": (43.116, 141.381), "RJEC": (43.671, 142.448),
    "RJCK": (43.041, 144.193), "RJCB": (43.880, 144.164),
    "RJSS": (38.140, 140.917), "RJSK": (39.616, 140.219),
    "RJTT": (35.552, 139.780), "RJAA": (35.765, 140.386),
    "RJGG": (34.858, 136.805), "RJNA": (35.255, 136.924),
    "RJOO": (34.785, 135.438), "RJBB": (34.435, 135.244),
    "RJBE": (34.633, 135.224), "RJOA": (34.436, 132.919),
    "RJOB": (34.758, 133.855), "RJOT": (34.214, 134.016),
    "RJOM": (33.827, 132.700), "RJFF": (33.586, 130.451),
    "ROAH": (26.196, 127.646),
}

AIRPORTS_BY_REGION = {
    "北海道": {
        "RJCO": "札幌丘珠空港",
        "RJEC": "旭川空港",
        "RJCK": "釧路空港",
        "RJCB": "女満別空港",
    },
    "東北": {
        "RJSS": "仙台空港",
        "RJSK": "秋田空港",
    },
    "関東": {
        "RJTT": "東京国際空港",
        "RJAA": "成田国際空港",
    },
    "中部": {
        "RJGG": "中部国際空港",
        "RJNA": "県営名古屋空港",
    },
    "近畿": {
        "RJOO": "大阪国際空港",
        "RJBB": "関西国際空港",
        "RJBE": "神戸空港",
    },
    "中国": {
        "RJOA": "広島空港",
        "RJOB": "岡山桃太郎空港",
    },
    "四国": {
        "RJOT": "高松空港",
        "RJOM": "松山空港",
    },
    "九州": {
        "RJFF": "福岡空港",
    },
    "沖縄": {
        "ROAH": "那覇空港",
    },
}


def get_user_file(user_id):
    return os.path.join(USERS_DIR, f"{user_id}.json")


def load_user_settings(user_id):
    f = get_user_file(user_id)
    if os.path.exists(f):
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            data["is_new"] = False
            return data
    return {"bookmarks": [], "default_code": "", "is_new": True}


def save_user_settings(user_id, settings):
    data = {k: v for k, v in settings.items() if k != "is_new"}
    with open(get_user_file(user_id), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)


def get_airport_name(code):
    for airports in AIRPORTS_BY_REGION.values():
        if code in airports:
            return airports[code]
    return code


def resolve_code_to_indices(code):
    for ri, (_, airports) in enumerate(AIRPORTS_BY_REGION.items()):
        if code in airports:
            return ri, list(airports.keys()).index(code)
    return 0, 0


@st.cache_data(ttl=1800)
def fetch_metar(code):
    url = f"https://aviationweather.gov/api/data/metar?ids={code}&format=json"
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    data = res.json()
    return data[0] if data else None


@st.cache_data(ttl=1800)
def fetch_bakuyake(lat: float, lon: float):
    res = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,relative_humidity_2m,visibility,precipitation",
            "daily": "sunset",
            "timezone": "Asia/Tokyo",
            "forecast_days": 7,
        },
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def _parse_sunset_conditions(data: dict, day_idx: int = 0) -> dict:
    sunset_str = data["daily"]["sunset"][day_idx]
    sunset_dt = datetime.fromisoformat(sunset_str)
    times = data["hourly"]["time"]
    target = sunset_dt.strftime("%Y-%m-%dT%H:00")
    idx = times.index(target) if target in times else min(day_idx * 24 + 19, len(times) - 1)
    h = data["hourly"]
    precip_3h = sum(v or 0 for v in h["precipitation"][max(0, idx - 2): idx + 1])
    return {
        "sunset_dt": sunset_dt,
        "cloud":      h["cloud_cover"][idx] or 0,
        "cloud_high": h["cloud_cover_high"][idx] or 0,
        "cloud_mid":  h["cloud_cover_mid"][idx] or 0,
        "cloud_low":  h["cloud_cover_low"][idx] or 0,
        "humidity":   h["relative_humidity_2m"][idx] or 50,
        "vis_m":      h["visibility"][idx] or 10000,
        "precip_3h":  precip_3h,
    }


def calc_bakuyake_score(c) -> int:
    cloud = c["cloud"]
    # 全体雲量: 20-50% 満点、0% と 100% は 0 点
    if cloud < 20:
        c_s = cloud / 20.0
    elif cloud <= 50:
        c_s = 1.0
    elif cloud <= 80:
        c_s = (80 - cloud) / 30.0
    else:
        c_s = 0.0
    # 高層雲: 多いほど良い
    h_s = c["cloud_high"] / 100.0
    # 湿度: 低いほど良い (40% 以下満点、80% 以上 0 点)
    hum = c["humidity"]
    hum_s = max(0.0, (80 - hum) / 40.0) if hum > 40 else 1.0
    # 視程: 20km 以上満点
    vis_s = min(1.0, c["vis_m"] / 20000.0)
    # 雨上がりボーナス
    rain_b = 1.0 if 0.5 <= c["precip_3h"] <= 15.0 else 0.0

    return min(100, round((c_s * 0.40 + h_s * 0.10 + hum_s * 0.25 + vis_s * 0.15 + rain_b * 0.10) * 100))


def judge_bakuyake(score: int):
    if score >= 70:
        return "🔥 爆焼けチャンス！", "#ff6b35", "hot"
    elif score >= 50:
        return "🌅 期待できる", "#f39c12", "warm"
    elif score >= 30:
        return "🌤 少し期待", "#8e9eab", "mild"
    else:
        return "😐 今日は厳しいかも", "#556677", "cool"


def judge_vapor(spread):
    if spread <= 1.0:
        return "✅ ほぼ確実に出る", "#2ecc71", "green"
    elif spread <= 3.0:
        return "⚡ 出る可能性あり", "#f39c12", "yellow"
    else:
        return "❌ まず出ない", "#e74c3c", "red"


def wind_compass(deg):
    dirs = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
            "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return dirs[round(float(deg) / 22.5) % 16]


def calc_rwy14_probability(wdir, wspd):
    """RWY14運用確率(0-100)とRWY32追い風成分(kt)を返す。算出不可は(None, None)"""
    if wdir is None or wspd is None:
        return None, None
    try:
        wdir_f = float(wdir)
        wspd_f = float(wspd)
    except (ValueError, TypeError):
        return None, None
    # RWY32(heading 320°)の追い風成分 = wspd × cos(wdir - 140°)
    # 10kt以上がブルーゾーン（RWY14運用の可能性）
    tailwind = wspd_f * math.cos(math.radians(wdir_f - 140))
    tailwind = round(tailwind, 1)
    prob = min(100, max(0, round(tailwind * 8)))
    return prob, tailwind


def show_rwy14_card(code, item):
    if code != "RJOO" or item is None:
        return
    wdir = item.get("wdir")
    wspd = item.get("wspd")
    wgst = item.get("wgst")
    prob, tailwind = calc_rwy14_probability(wdir, wspd)

    try:
        wdir_f = float(wdir)
        wspd_f = float(wspd)
        wind_info = f"{wdir_f:.0f}° {wind_compass(wdir_f)} / {wspd_f:.0f}kt"
        if wgst:
            wind_info += f"（最大 {float(wgst):.0f}kt）"
    except (ValueError, TypeError):
        wind_info = f"VRB / {wspd}kt" if wspd else "---"

    if prob is None:
        st.markdown(f"""
<div style="border-radius:18px;padding:18px 20px;margin:14px 0;border-left:7px solid #555;background:#1a1a2e;">
  <div style="font-size:0.78em;color:#999;margin-bottom:6px;">RWY14 運用確率 — 大阪国際空港</div>
  <div style="color:#aaa;">{wind_info}　（追い風成分算出不可）</div>
</div>
""", unsafe_allow_html=True)
        return

    rancen_label = "　ランチェンゾーン" if tailwind >= 10.0 else ""

    if tailwind >= 12.0:
        card_color, bg_color = "#e74c3c", "#270b0b"
        verdict = "🔴 ランチェンゾーン — 状態が続けば RWY14 の可能性"
    elif tailwind >= 9.0:
        card_color, bg_color = "#f39c12", "#271c08"
        verdict = "🟡 ランチェンゾーン接近中"
    else:
        card_color, bg_color = "#2ecc71", "#0b2118"
        verdict = "🟢 RWY32 通常運用"

    st.markdown(f"""
<div style="border-radius:18px;padding:18px 20px;margin:14px 0;border-left:7px solid {card_color};background:{bg_color};">
  <div style="font-size:0.78em;color:#999;margin-bottom:8px;">✈ RWY14 運用可能性 — 大阪国際空港</div>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <div style="font-size:1.3em;font-weight:bold;color:#fff;">{wind_info}</div>
      <div style="font-size:1.2em;font-weight:bold;color:#ccc;margin-top:6px;">追い風成分: {tailwind}{rancen_label}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:0.72em;color:#999;">ワンフォースコア</div>
      <div style="font-size:2.6em;font-weight:bold;color:#fff;line-height:1.1;">{prob}<span style="font-size:0.5em;color:#888;">%</span></div>
    </div>
  </div>
  <div style="height:8px;background:#333;border-radius:4px;margin:10px 0 8px;">
    <div style="height:8px;border-radius:4px;background:{card_color};width:{prob}%;"></div>
  </div>
  <div style="font-size:1.1em;font-weight:bold;color:{card_color};">{verdict}</div>
  <div style="font-size:0.75em;color:#666;margin-top:8px;">追い風成分が 9.0〜11.9 でランチェン可能性あり、12.0 以上が断続的に続く場合に RWY14 運用になる可能性が大きくなります。</div>
</div>
""", unsafe_allow_html=True)
    with st.expander("📐 ワンフォースコアの計算式"):
        st.markdown(f"""
**追い風成分**
```
追い風成分 = 風速 × cos(風向 − 140°)
```
- `風向` = METAR の風向（度）
- `風速` = METAR の風速（kt）
- `140°` = RWY32（逆方向 RWY14）の滑走路方位

現在の値: {wdir_f:.0f}° / {wspd_f:.0f}kt → 追い風成分 **{tailwind}**

---

**判定基準**

| 追い風成分 | 判定 |
|---|---|
| 12.0 以上 | 🔴 断続継続で RWY14 運用の可能性大 |
| 9.0〜11.9 | 🟡 ランチェン可能性あり |
| 9.0 未満 | 🟢 RWY32 通常運用 |

---

**データソース**

| 項目 | 取得元 |
|---|---|
| 風向・風速 | aviationweather.gov（METAR） |
| 滑走路方位 | RWY14/32 磁方位 140°/320° |
""")
        st.caption("30分キャッシュ | 伊丹空港（RJOO）専用")


def make_moon_image(phase_ratio: float, size: int = 80) -> Image.Image:
    """月の形をPILで描画。phase_ratio: 0=新月, 0.5=満月"""
    try:
        import numpy as np
        p = float(phase_ratio)
        yc, xc = np.mgrid[0:size, 0:size]
        cx = cy = (size - 1) / 2.0
        r = (size / 2) * 0.90
        nx = (xc - cx) / r
        ny = (yc - cy) / r
        inside = nx ** 2 + ny ** 2 <= 1.0
        sqrt_t = np.sqrt(np.maximum(0.0, 1.0 - ny ** 2))
        if p <= 0.5:
            lit = nx > (1.0 - 4.0 * p) * sqrt_t
        else:
            lit = -nx > (4.0 * (p - 0.5) - 1.0) * sqrt_t
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[inside & lit] = [255, 240, 180, 255]
        rgba[inside & ~lit] = [25, 25, 45, 200]
        return Image.fromarray(rgba, "RGBA")
    except Exception:
        return Image.new("RGBA", (size, size), (80, 80, 80, 180))


def _moon_b64(phase_ratio: float, size: int = 80) -> str:
    buf = io.BytesIO()
    make_moon_image(phase_ratio, size).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def moon_phase_name(age: float) -> str:
    a = age % 29.53
    if a < 1.5:    return "新月"
    elif a < 5.5:  return "三日月"
    elif a < 9.5:  return "上弦前"
    elif a < 11.5: return "上弦の月"
    elif a < 13.5: return "十三夜"
    elif a < 15.5: return "満月"
    elif a < 17.5: return "十六夜"
    elif a < 19.5: return "立待月"
    elif a < 21.5: return "居待月"
    elif a < 23.5: return "下弦の月"
    elif a < 26.5: return "下弦後"
    else:          return "晦日月"


@st.cache_data(ttl=3600)
def get_moon_data(lat: float, lon: float, date_offset: int = 0) -> dict:
    target_date = (datetime.now(JST) + timedelta(days=date_offset)).date()
    result = {
        "age": 0.0, "phase_ratio": 0.0, "illumination": 0,
        "phase_name": "---", "rise_time": "---", "rise_az": "---",
        "date": target_date,
    }
    if _ASTRAL_OK:
        try:
            age = _astral_moon_phase(target_date)
            pr = age / 29.53
            result.update({
                "age": round(age, 1),
                "phase_ratio": pr,
                "illumination": round((1 - math.cos(2 * math.pi * pr)) / 2 * 100),
                "phase_name": moon_phase_name(age),
            })
        except Exception:
            pass
        try:
            loc = _AstralLocation(latitude=lat, longitude=lon, timezone="Asia/Tokyo")
            rise_dt = _astral_moonrise(loc.observer, target_date, loc.timezone)
            if rise_dt:
                result["rise_time"] = rise_dt.strftime("%H:%M")
                if _EPHEM_OK:
                    obs = _ephem.Observer()
                    obs.lat = str(lat)
                    obs.lon = str(lon)
                    obs.date = _ephem.Date(rise_dt.astimezone(timezone.utc))
                    m = _ephem.Moon()
                    m.compute(obs)
                    result["rise_az"] = f"{math.degrees(float(m.az)):.0f}°"
        except Exception:
            pass
    return result


def show_moon_section(selected_code: str):
    if selected_code not in AIRPORT_COORDS:
        return
    lat, lon = AIRPORT_COORDS[selected_code]
    airport_name = get_airport_name(selected_code)
    st.markdown("### 🌕 月情報")
    st.caption("月齢・月相・輝面比・月の出時刻と方角")
    try:
        today = get_moon_data(lat, lon, 0)
        t_b64 = _moon_b64(today["phase_ratio"], 100)
        st.markdown(f"""
<div style="border-radius:18px;padding:22px 20px 16px;margin:14px 0;
     border-left:7px solid #b8860b;background:#1a1a0e;">
  <div style="font-size:0.78em;color:#999;margin-bottom:10px;">{airport_name}</div>
  <div style="display:flex;align-items:center;gap:20px;">
    <img src="data:image/png;base64,{t_b64}" width="100" height="100"
         style="border-radius:50%;flex-shrink:0;">
    <div>
      <div style="font-size:1.6em;font-weight:bold;color:#fff;">{today['phase_name']}</div>
      <div style="font-size:1.0em;color:#ccc;margin-top:6px;">月齢 {today['age']} 日　輝面比 {today['illumination']}%</div>
      <div style="font-size:0.9em;color:#aaa;margin-top:6px;">🌙 月の出 {today['rise_time']}　方角 {today['rise_az']}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
        WDAYS = ["月", "火", "水", "木", "金", "土", "日"]
        mini_items = []
        for i in range(1, 7):
            d = get_moon_data(lat, lon, i)
            dd = d["date"]
            wd = WDAYS[dd.weekday()]
            ds = "明日" if i == 1 else f"{dd.month}/{dd.day}"
            lbl = f'{ds}<br><span style="color:#666;font-size:0.9em;">({wd})</span>'
            mb64 = _moon_b64(d["phase_ratio"], 40)
            mini_items.append(
                f'<div style="flex:1;min-width:0;text-align:center;padding:10px 4px 8px;'
                f'border-radius:12px;background:#1a1a0e;border:1px solid #b8860b;">'
                f'<div style="font-size:0.7em;color:#999;margin-bottom:4px;line-height:1.4;">{lbl}</div>'
                f'<div style="display:flex;justify-content:center;margin-bottom:4px;">'
                f'<img src="data:image/png;base64,{mb64}" width="36" height="36" style="border-radius:50%;"></div>'
                f'<div style="font-size:0.8em;font-weight:bold;color:#fff;white-space:nowrap;">{d["phase_name"]}</div>'
                f'<div style="font-size:0.68em;color:#888;">{d["illumination"]}%</div>'
                f'<div style="font-size:0.65em;color:#777;margin-top:2px;">{d["rise_time"]}</div>'
                f'</div>'
            )
        st.markdown(
            '<div style="display:flex;gap:6px;width:100%;box-sizing:border-box;padding:6px 0 2px;">'
            + "".join(mini_items) + "</div>",
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.error(f"月情報の取得エラー: {e}")


def show_card(code, name):
    try:
        item = fetch_metar(code)
        if not item:
            st.warning(f"{name}（{code}）のデータが取得できませんでした")
            return
        temp = item.get("temp")
        dewp = item.get("dewp")
        if temp is None or dewp is None:
            st.warning("気温・露点データがありません")
            return
        spread = round(float(temp) - float(dewp), 1)
        judgment, color, cls = judge_vapor(spread)
        st.markdown(f"""
        <div class="airport-card {cls}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <div class="ap-name">{name}</div>
                    <div class="ap-code">{code}</div>
                </div>
                <div style="text-align:right;">
                    <div class="sp-label">スプレッド</div>
                    <div class="sp-val">{spread}°</div>
                </div>
            </div>
            <div class="judgment" style="color:{color};">{judgment}</div>
            <div class="detail">気温 {temp}°C　／　露点 {dewp}°C</div>
        </div>
        """, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"データ取得エラー: {e}")


# ページ設定
st.set_page_config(
    page_title="Airport Forcast",
    page_icon=_ICON_IMG,
    layout="centered",
    initial_sidebar_state="collapsed",
)

# apple-touch-icon（iOSホーム画面追加時のアイコン）をJSで<head>に注入
st.markdown(f"""<script>
(function(){{
  var l=document.createElement('link');
  l.rel='apple-touch-icon';
  l.href='data:image/png;base64,{_ICON_B64}';
  document.head.appendChild(l);
}})();
</script>""", unsafe_allow_html=True)

st.markdown("""
<style>
    .main > div { padding: 1rem 0.6rem; }
    h1 a, h2 a, h3 a, h4 a { display: none !important; }
    .airport-card {
        border-radius: 18px;
        padding: 22px 20px 16px;
        margin: 14px 0;
        border-left: 7px solid #555;
        background: #1a1a2e;
    }
    .airport-card.green  { border-left-color: #2ecc71; background: #0b2118; }
    .airport-card.yellow { border-left-color: #f39c12; background: #271c08; }
    .airport-card.red    { border-left-color: #e74c3c; background: #270b0b; }
    .ap-name  { font-size: 1.6em; font-weight: bold; color: #fff; }
    .ap-code  { font-size: 0.82em; color: #777; margin-top: 2px; }
    .sp-label { font-size: 0.72em; color: #999; }
    .sp-val   { font-size: 2.6em; font-weight: bold; color: #fff; line-height:1.1; }
    .judgment { font-size: 1.15em; font-weight: bold; margin-top: 14px; }
    .detail   { font-size: 0.83em; color: #888; margin-top: 8px; }
    .bakuyake-card { border-radius: 18px; padding: 22px 20px 16px; margin: 14px 0; border-left: 7px solid #555; background: #1a1a2e; }
    .bakuyake-card.hot  { border-left-color: #ff6b35; background: #2a1200; }
    .bakuyake-card.warm { border-left-color: #f39c12; background: #271c08; }
    .bakuyake-card.mild { border-left-color: #8e9eab; background: #151c22; }
    .bakuyake-card.cool { border-left-color: #445566; background: #111; }
    .bk-header  { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; }
    .bk-city    { font-size:1.4em; font-weight:bold; color:#fff; }
    .bk-subtitle{ font-size:0.82em; color:#aaa; margin-top:2px; }
    .bk-score   { font-size:2.6em; font-weight:bold; color:#fff; line-height:1.1; }
    .bk-score-unit { font-size:0.5em; color:#888; }
    .bk-bar-wrap{ margin:8px 0 14px; background:#333; border-radius:4px; height:8px; }
    .bk-bar-fill{ height:8px; border-radius:4px; }
    .bk-verdict { font-size:1.15em; font-weight:bold; margin-bottom:8px; }
    .bk-cond    { font-size:0.83em; color:#888; }
</style>
""", unsafe_allow_html=True)

# ユーザーID管理
user_id = st.query_params.get("u", None)
if not user_id:
    new_id = uuid.uuid4().hex[:8]
    st.query_params["u"] = new_id
    st.rerun()

user_settings = load_user_settings(user_id)
bookmarks    = user_settings.get("bookmarks", [])
default_code = user_settings.get("default_code", "")
is_new       = user_settings.get("is_new", False)

# ヘッダー
st.markdown(
    f'<h2 style="display:flex;align-items:center;gap:10px;">'
    f'<img src="data:image/png;base64,{_ICON_B64}" width="36" style="border-radius:6px;">'
    f'Airport Forcast</h2>',
    unsafe_allow_html=True,
)
st.caption(f"更新: {datetime.now(JST).strftime('%m/%d %H:%M')} JST　|　METAR（30分キャッシュ）")

# 初回ユーザー向けメッセージ
if is_new:
    st.info("📌 初回アクセスです。このページのURLをブックマークしておいてください。次回から設定が引き継がれます。")

# Bookmarkセクション
if bookmarks:
    st.markdown("#### 🔖 Bookmark")
    n = len(bookmarks)
    cols = st.columns(min(n, 3))
    for i, fav_code in enumerate(bookmarks):
        with cols[i % min(n, 3)]:
            if st.button(get_airport_name(fav_code), key=f"bm_{fav_code}", use_container_width=True):
                st.session_state["jump_code"] = fav_code
                st.rerun()
    st.divider()

# ジャンプ先 or デフォルトからインデックスを解決
resolve_code = st.session_state.get("jump_code") or default_code
jump_region_idx, jump_airport_idx = (
    resolve_code_to_indices(resolve_code) if resolve_code else (0, 0)
)

# 地域・空港選択
region_names = list(AIRPORTS_BY_REGION.keys())
st.markdown("#### 空港を選択")

# デフォルト・ジャンプがある場合だけ初期インデックスを設定
r_idx = resolve_code_to_indices(resolve_code)[0] if resolve_code else None

selected_region = st.selectbox(
    "地域", region_names,
    index=r_idx,
    placeholder="- 地域を選択 -",
)

if "jump_code" in st.session_state:
    del st.session_state["jump_code"]

if selected_region is None:
    st.selectbox("空港", [], index=None, placeholder="- 空港を選択 -", disabled=True)
    selected_code = None
else:
    airports_in_region = AIRPORTS_BY_REGION[selected_region]
    airport_labels = [f"{name}　{code}" for code, name in airports_in_region.items()]
    airport_codes  = list(airports_in_region.keys())

    # 選択された地域内にresolve_codeがあれば初期選択、なければ未選択
    ap_idx = (
        airport_codes.index(resolve_code)
        if resolve_code and resolve_code in airports_in_region
        else None
    )

    selected_ap_label = st.selectbox(
        "空港", airport_labels,
        index=ap_idx,
        placeholder="- 空港を選択 -",
    )

    selected_code = (
        airport_codes[airport_labels.index(selected_ap_label)]
        if selected_ap_label else None
    )

# 空港が選ばれている場合のみボタン・カードを表示
if selected_code:
    selected_name = AIRPORTS_BY_REGION[selected_region][selected_code]
    is_bm      = selected_code in bookmarks
    is_default = selected_code == default_code
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔖 解除" if is_bm else "🔖 Bookmark", use_container_width=True):
            if is_bm:
                bookmarks.remove(selected_code)
            else:
                if selected_code not in bookmarks:
                    bookmarks.append(selected_code)
            user_settings["bookmarks"] = bookmarks
            save_user_settings(user_id, user_settings)
            st.rerun()

    with col2:
        if st.button("🏠 解除" if is_default else "🏠 デフォルト", use_container_width=True):
            user_settings["default_code"] = "" if is_default else selected_code
            save_user_settings(user_id, user_settings)
            st.rerun()

    # 爆焼け予報
    st.markdown("### 🌅 爆焼け予報")
    st.caption("日没時の気象データから爆焼けの可能性をスコア化します")
    if selected_code in AIRPORT_COORDS:
        try:
            lat, lon = AIRPORT_COORDS[selected_code]
            raw = fetch_bakuyake(lat, lon)
            cond = _parse_sunset_conditions(raw)
            score = calc_bakuyake_score(cond)
            verdict, color, cls = judge_bakuyake(score)
            bar_colors = {"hot": "#ff6b35", "warm": "#f39c12", "mild": "#8e9eab", "cool": "#445566"}
            bar_color = bar_colors[cls]
            sunset_str = cond["sunset_dt"].strftime("%H:%M")
            airport_name = get_airport_name(selected_code)
            vis_km = cond["vis_m"] / 1000
            rain_txt = "　🌂 雨上がり" if cond["precip_3h"] >= 0.5 else ""
            st.markdown(f"""
<div class="bakuyake-card {cls}">
  <div class="bk-header">
    <div>
      <div class="bk-city">{airport_name}</div>
      <div class="bk-subtitle">日没 {sunset_str}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:0.72em;color:#999;">爆焼けスコア</div>
      <div class="bk-score">{score}<span class="bk-score-unit"> / 100</span></div>
    </div>
  </div>
  <div class="bk-bar-wrap"><div class="bk-bar-fill" style="width:{score}%;background:{bar_color};"></div></div>
  <div class="bk-verdict" style="color:{color};">{verdict}</div>
  <div class="bk-cond">雲量 {cond['cloud']}%　高層雲 {cond['cloud_high']}%　湿度 {cond['humidity']}%　視程 {vis_km:.0f}km{rain_txt}</div>
</div>
""", unsafe_allow_html=True)

            # 6日ミニスコア行（明日〜）
            WDAYS = ["月", "火", "水", "木", "金", "土", "日"]
            n_days = len(raw["daily"]["sunset"])
            mini_items = []
            for i in range(1, n_days):
                d = datetime.fromisoformat(raw["daily"]["sunset"][i])
                wd = WDAYS[d.weekday()]
                date_str = "明日" if i == 1 else f"{d.month}/{d.day}"
                lbl = f'{date_str}<br><span style="color:#666;font-size:0.9em;">({wd})</span>'
                c_i = _parse_sunset_conditions(raw, i)
                s_i = calc_bakuyake_score(c_i)
                _, _, cls_i = judge_bakuyake(s_i)
                bg  = {"hot": "#2a1200", "warm": "#271c08", "mild": "#151c22", "cool": "#111"}[cls_i]
                bdr = {"hot": "#ff6b35", "warm": "#f39c12", "mild": "#8e9eab", "cool": "#445566"}[cls_i]
                mini_items.append(
                    f'<div style="flex:1;text-align:center;padding:10px 4px 8px;border-radius:12px;'
                    f'background:{bg};border:1px solid {bdr};">'
                    f'<div style="font-size:0.7em;color:#999;margin-bottom:4px;line-height:1.4;">{lbl}</div>'
                    f'<div style="font-size:1.4em;font-weight:bold;color:#fff;line-height:1;">{s_i}</div>'
                    f'<div style="height:3px;border-radius:2px;background:{bdr};margin:5px 6px 0;"></div>'
                    f'</div>'
                )
            st.markdown(
                '<div style="display:flex;gap:6px;width:100%;box-sizing:border-box;padding:6px 0 2px;">'
                + "".join(mini_items) + "</div>",
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    with st.expander("📐 爆焼けスコアの計算式"):
        st.markdown("""
**スコア構成（合計100点）**

| 指標 | 配点 | 理想値 |
|---|---|---|
| 全体雲量 | 40点 | 20〜50%（キャンバスとなる適度な雲） |
| 湿度 | 25点 | 40%以下（低いほど透明度が高い） |
| 視程 | 15点 | 20km以上（大気が澄んでいる） |
| 高層雲（巻雲） | 10点 | 多いほど良い（光を広域に拡散） |
| 雨上がりボーナス | 10点 | 直近3時間に0.5〜15mm（空気が洗われた後） |

---

**全体雲量スコアの計算**

```
雲量 0%        → 0点  （キャンバスなし）
雲量 20〜50%   → 満点 （光を反射する適度な雲）
雲量 50〜80%   → 逓減 （厚くなりすぎると光が通らない）
雲量 80%以上   → 0点  （太陽光が届かない）
```

**湿度スコアの計算**

```
湿度 40%以下   → 満点
湿度 40〜80%   → 線形に逓減
湿度 80%以上   → 0点
```

---

**判定基準**

| スコア | 判定 |
|---|---|
| 70〜100 | 🔥 爆焼けチャンス！ |
| 50〜69  | 🌅 期待できる |
| 30〜49  | 🌤 少し期待 |
| 0〜29   | 😐 今日は厳しいかも |

---

**なぜ雲量が多すぎてもダメなのか**

夕焼けは太陽が地平線に沈む直前、大気を斜めに通過した赤い光が
雲に当たって反射することで起きる。
雲が少なすぎると反射面がなく、多すぎると光が雲で遮られる。
「適度な雲が西空にあり、頭上は晴れている」状態が最適。

**高層雲（巻雲）がなぜ重要か**

高度8〜12kmの薄い巻雲は、光を遮らずに広く拡散させる。
夕焼けが空全体を染める爆焼けには、この巻雲の存在が大きく効く。
""")
        st.markdown("""
---

**データソース**

| 項目 | 取得元 | 変数名 |
|---|---|---|
| 日没時刻 | [Open-Meteo](https://open-meteo.com/) daily | `sunset` |
| 全体雲量 | Open-Meteo hourly | `cloud_cover` |
| 高層雲量 | Open-Meteo hourly | `cloud_cover_high`（高度8km以上） |
| 湿度 | Open-Meteo hourly | `relative_humidity_2m` |
| 視程 | Open-Meteo hourly | `visibility`（単位: m） |
| 降水量 | Open-Meteo hourly | `precipitation`（日没前3時間の合計） |

日没時刻を含む1時間ブロック（例: 日没19:11 → 19:00台）の気象データを使用。キャッシュ: 30分。
""")
        st.caption("空港座標から Open-Meteo API（無料・APIキー不要）で取得")

    show_moon_section(selected_code)

    st.divider()

    # ベイパー
    st.markdown("### ✈ ベイパー予報")
    show_card(selected_code, selected_name)

    with st.expander("📐 ベイパー発生の計算式"):
        st.markdown("""
**スプレッド（温度差）**
```
スプレッド = 気温 − 露点温度
```

| スプレッド | 判定 |
|---|---|
| 0〜1°C | ✅ ほぼ確実に出る |
| 1〜3°C | ⚡ 出る可能性あり |
| 3°C 超 | ❌ まず出ない |

---

**露点温度の計算（Magnus式）**

湿度（%）と気温（°C）から露点温度を求める近似式：
```
Td = T − ((100 − RH) / 5)
```
- `T`  = 気温（°C）
- `RH` = 相対湿度（%）
- `Td` = 露点温度（°C）

精密版（Magnus式）：
```
α  = ln(RH/100) + 17.625 × T / (243.04 + T)
Td = 243.04 × α / (17.625 − α)
```

---

**なぜスプレッドが小さいと出るのか**

着陸時に翼端渦・フラップ後縁で局所的な気圧降下が発生する。
この圧力低下により温度がさらに下がり、露点に達して空気中の
水分が凝結してベイパーとして可視化される。

- 朝方・雨上がり直後・海沿い → 湿度が高くなりやすい
- 大型機・フル高揚力装置展開の着陸時 → 渦が強く出やすい
""")
        st.caption("データソース: aviationweather.gov（METAR）| 30分キャッシュ")

    # ワンフォー（伊丹専用）
    if selected_code == "RJOO":
        st.markdown("### ✈ ワンフォー予報")
        try:
            show_rwy14_card(selected_code, fetch_metar(selected_code))
        except Exception:
            pass

    if st.button("🔄 データを更新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
