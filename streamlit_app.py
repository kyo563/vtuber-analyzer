# streamlit_app.py — experimental_rerun を使わないプレースホルダ方式（全文）
import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
import io

st.set_page_config(page_title="解析ツール", layout="wide")

# APIキー（推奨：Streamlit secrets に YOUTUBE_API_KEY を設定）
API_KEY = st.secrets.get("YOUTUBE_API_KEY") if "YOUTUBE_API_KEY" in st.secrets else None
if not API_KEY:
    API_KEY = st.sidebar.text_input("YouTube API Key (一時入力可)", type="password")

# YouTube client を一度だけ作成する（キャッシュ）
@st.cache_resource
def get_youtube_client():
    if not API_KEY:
        raise RuntimeError("YouTube API key is not configured.")
    return build("youtube", "v3", developerKey=API_KEY)

# ヘルパー関数（キャッシュ付き）
@st.cache_data(ttl=3600)
def resolve_channel_id_simple(url_or_id: str) -> Optional[str]:
    youtube = get_youtube_client()
    s = (url_or_id or "").strip()
    if not s:
        return None
    if s.startswith("UC") and len(s) == 24:
        return s
    if "channel/" in s:
        return s.split("channel/")[1].split("/")[0]
    try:
        resp = youtube.search().list(q=s, type="channel", part="snippet", maxResults=3).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
    except Exception:
        return None
    return None

@st.cache_data(ttl=3600)
def get_channel_basic(channel_id: str) -> Optional[Dict]:
    youtube = get_youtube_client()
    try:
        resp = youtube.channels().list(part="snippet,statistics,contentDetails", id=channel_id, maxResults=1).execute()
        items = resp.get("items", [])
        if not items:
            return None
        it = items[0]
        return {
            "channelId": channel_id,
            "title": it.get("snippet", {}).get("title"),
            "publishedAt": it.get("snippet", {}).get("publishedAt"),
            "subscriberCount": int(it.get("statistics", {}).get("subscriberCount", 0) or 0),
            "videoCount": int(it.get("statistics", {}).get("videoCount", 0) or 0),
            "viewCount": int(it.get("statistics", {}).get("viewCount", 0) or 0),
            "uploadsPlaylistId": it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        }
    except Exception:
        return None

@st.cache_data(ttl=1800)
def get_playlists_meta(channel_id: str) -> List[Dict]:
    youtube = get_youtube_client()
    pls: List[Dict] = []
    next_page = None
    try:
        while True:
            resp = youtube.playlists().list(part="snippet,contentDetails", channelId=channel_id, maxResults=50, pageToken=next_page).execute()
            for pl in resp.get("items", []):
                pls.append({
                    "playlistId": pl.get("id"),
                    "title": pl.get("snippet", {}).get("title"),
                    "itemCount": int(pl.get("contentDetails", {}).get("itemCount", 0) or 0)
                })
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except Exception:
        pass
    return pls

@st.cache_data(ttl=900)
def search_video_ids_published_after(channel_id: str, days: int) -> List[str]:
    youtube = get_youtube_client()
    video_ids: List[str] = []
    published_after = (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    next_page = None
    try:
        while True:
            resp = youtube.search().list(part="id", channelId=channel_id, publishedAfter=published_after, type="video", maxResults=50, pageToken=next_page).execute()
            for item in resp.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except Exception:
        pass
    return video_ids

@st.cache_data(ttl=1800)
def get_videos_stats(video_ids: Tuple[str, ...]) -> Dict[str, Dict]:
    youtube = get_youtube_client()
    out: Dict[str, Dict] = {}
    if not video_ids:
        return out
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        try:
            resp = youtube.videos().list(part="snippet,statistics", id=",".join(chunk), maxResults=50).execute()
            for it in resp.get("items", []):
                vid = it.get("id")
                out[vid] = {
                    "title": it.get("snippet", {}).get("title", ""),
                    "viewCount": int(it.get("statistics", {}).get("viewCount", 0) or 0),
                    "likeCount": int(it.get("statistics", {}).get("likeCount", 0) or 0)
                }
        except Exception:
            continue
    return out

@st.cache_data(ttl=300)
def fetch_playlist_items_sample(playlist_id: str, max_items: int = 100) -> List[Dict]:
    youtube = get_youtube_client()
    items: List[Dict] = []
    next_page = None
    try:
        while True and len(items) < max_items:
            resp = youtube.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=next_page).execute()
            for it in resp.get("items", []):
                videoId = it.get("contentDetails", {}).get("videoId") or it.get("snippet", {}).get("resourceId", {}).get("videoId")
                if videoId:
                    items.append({
                        "videoId": videoId,
                        "title": it.get("snippet", {}).get("title"),
                        "publishedAt": it.get("snippet", {}).get("publishedAt")
                    })
                    if len(items) >= max_items:
                        break
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except Exception:
        pass
    return items

# UI / Main
st.title("解析ツール")

# top row: input | buttons (集計 + ダウンロード) | info
col_input, col_buttons, col_info = st.columns([3, 1, 1])
with col_input:
    url_or_id = st.text_input("URL / ID / 表示名 を入力")

# プレースホルダをここで作る（上部ダウンロードを後で上書き）
with col_buttons:
    run_btn = st.button("集計")
    download_placeholder = st.empty()  # ← ここを後で上書きする

with col_info:
    st.write("動作メモ")
    st.write("- APIキーは Streamlit secrets に設定してください。")
    st.write("- キャッシュを活用してクォータを節約しています。")

if run_btn:
    if not API_KE_
