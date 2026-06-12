"""
vapor app.py  - ベイパー予報 Webアプリ
ユニークURLで各ユーザーの設定を管理する
"""
import base64
import io
import json
import os
import uuid
import requests
import streamlit as st
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFilter

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
    tip_x, tip_y = cx, int(size * 0.18)

    lp = _bezier((tip_x - 10, tip_y + 14), (tip_x - 55, tip_y + 70), (tip_x - 68, tip_y + 145))
    rp = _bezier((tip_x + 10, tip_y + 14), (tip_x + 55, tip_y + 70), (tip_x + 68, tip_y + 145))

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for pts in (lp, rp):
        for i in range(len(pts) - 1):
            t = i / len(pts)
            gd.line([pts[i], pts[i + 1]], fill=(160, 210, 255, int(90 * (1 - t * 0.6))),
                    width=max(2, int(14 * (1 - t * 0.5))))
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)
    for pts in (lp, rp):
        for i in range(len(pts) - 1):
            t = i / len(pts)
            draw.line([pts[i], pts[i + 1]], fill=(210, 235, 255, int(240 * (1 - t * 0.35))),
                      width=max(1, int(6 * (1 - t * 0.65))))

    bx, by = tip_x, tip_y
    draw.polygon([(bx, by), (bx - 4, by + 20), (bx + 4, by + 20)], fill=(255, 255, 255, 255))
    draw.rounded_rectangle([bx - 4, by + 18, bx + 4, by + 38], radius=3, fill=(240, 240, 255, 255))
    draw.polygon([(bx - 4, by + 22), (bx + 4, by + 22), (bx + 22, by + 32),
                  (bx + 18, by + 36), (bx, by + 30), (bx - 18, by + 36), (bx - 22, by + 32)],
                 fill=(255, 255, 255, 240))
    draw.polygon([(bx - 4, by + 34), (bx + 4, by + 34), (bx + 10, by + 42), (bx - 10, by + 42)],
                 fill=(220, 230, 255, 220))
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
            "forecast_days": 1,
        },
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def _parse_sunset_conditions(data: dict) -> dict:
    sunset_str = data["daily"]["sunset"][0]
    sunset_dt = datetime.fromisoformat(sunset_str)
    times = data["hourly"]["time"]
    target = sunset_dt.strftime("%Y-%m-%dT%H:00")
    idx = times.index(target) if target in times else len(times) - 1
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
    page_title="ベイパー予報",
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
    f'ベイパー予報</h2>',
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

    show_card(selected_code, selected_name)

    if st.button("🔄 データを更新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 計算式
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

# 爆焼け予報セクション
st.divider()
st.markdown("### 🌅 爆焼け予報")
st.caption("日没時の気象データから爆焼けの可能性をスコア化します")

bk_code = selected_code if selected_code and selected_code in AIRPORT_COORDS else None

if bk_code is None:
    st.info("空港を選ぶと、その地点の爆焼けスコアが表示されます。")
else:
    try:
        lat, lon = AIRPORT_COORDS[bk_code]
        raw = fetch_bakuyake(lat, lon)
        cond = _parse_sunset_conditions(raw)
        score = calc_bakuyake_score(cond)
        verdict, color, cls = judge_bakuyake(score)
        bar_colors = {"hot": "#ff6b35", "warm": "#f39c12", "mild": "#8e9eab", "cool": "#445566"}
        bar_color = bar_colors[cls]
        sunset_str = cond["sunset_dt"].strftime("%H:%M")
        airport_name = get_airport_name(bk_code)
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
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
