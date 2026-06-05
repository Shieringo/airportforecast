"""
vapor app.py  - ベイパー予報 Webアプリ
ユニークURLで各ユーザーの設定を管理する
"""
import json
import os
import uuid
import requests
import streamlit as st
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
USERS_DIR = os.path.join(os.path.dirname(__file__), "users")
os.makedirs(USERS_DIR, exist_ok=True)

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
    page_icon="✈️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

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
st.markdown("## ✈️ ベイパー予報")
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
    placeholder="-地域を選択-",
)

if "jump_code" in st.session_state:
    del st.session_state["jump_code"]

if selected_region is None:
    st.selectbox("空港", [], index=None, placeholder="-空港を選択-", disabled=True)
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
        placeholder="-空港を選択-",
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
