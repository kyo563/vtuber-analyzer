# app.py (修正版)
import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import io
from typing import List, Dict, Optional

st.set_page_config(page_title="YouTube チャンネル解析ツール (修正版)", layout="wide")

# APIキー取得（推薦：st.secrets に YOUTUBE_API_KEY を入れる）
API_KEY = st.secrets.get("YOUTUBE_API_KEY") if "YOUTUBE_API_KEY" in st.secrets else None
if not API_KEY:
    API_KEY = st.sidebar.text_input("YouTube API Key (一時入力可)", type="password")

def build_youtube(api_key: str):
    return build("youtube", "v3", developerKey=api_key)

@st.cache_data(ttl=3600)
def resolve_channel_id_simple(youtube_service, url_or_id: str) -> Optional[str]:
    s = (url_or_id or "").strip()
    if not s:
        return None
    if s.startswith("UC") and len(s) == 24:
        return s
    if "channel/" in s:
        return s.split("channel/")[1].split("/")[0]
    try:
        resp = youtube_service.search().list(q=s, type="channel", part="snippet", maxResults=3).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
    except Exception:
        return None
    return None

@st.cache_data(ttl=3600)
def get_channel_basic(youtube_service, channel_id: str) -> Optional[Dict]:
    try:
        resp = youtube_service.channels().list(part="snippet,statistics,contentDetails", id=channel_id, maxResults=1).execute()
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
def get_playlists_meta(youtube_service, channel_id: str) -> List[Dict]:
    pls = []
    next_page = None
    try:
        while True:
            resp = youtube_service.playlists().list(part="snippet,contentDetails", channelId=channel_id, maxResults=50, pageToken=next_page).execute()
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
def search_video_ids_published_after(youtube_service, channel_id: str, days: int) -> List[str]:
    video_ids = []
    published_after = (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    next_page = None
    try:
        while True:
            resp = youtube_service.search().list(part="id", channelId=channel_id, publishedAfter=published_after, type="video", maxResults=50, pageToken=next_page).execute()
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
def get_videos_stats(youtube_service, video_ids: List[str]) -> Dict[str, Dict]:
    out = {}
    if not video_ids:
        return out
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        try:
            resp = youtube_service.videos().list(part="snippet,statistics", id=",".join(chunk), maxResults=50).execute()
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
def fetch_playlist_items_sample(youtube_service, playlist_id: str, max_items: int = 100) -> List[Dict]:
    items = []
    next_page = None
    try:
        while True and len(items) < max_items:
            resp = youtube_service.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=next_page).execute()
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

# UI
st.title("YouTube チャンネル解析ツール（直近指標 + プレイリスト展開）")
st.markdown("チャンネルID（UC...）またはチャンネルURL、ハンドル、表示名を入力してください。直近10日/30日の指標と、プレイリスト展開を行います。")

col_input, col_info = st.columns([3, 1])
with col_input:
    url_or_id = st.text_input("YouTube チャンネル URL または チャンネル ID / 表示名 を入力")
    run_btn = st.button("集計")

with col_info:
    st.write("動作メモ")
    st.write("- APIキーは Streamlit secrets に設定してください。")
    st.write("- プレイリストの中身はクリック時に取得します（遅延取得）。")
    st.write("- クォータ節約のためキャッシュを使っています。")

if run_btn:
    if not API_KEY:
        st.error("APIキー未設定です。サイドバーまたは secrets に設定してください。")
        st.stop()

    youtube = build_youtube(API_KEY)

    channel_id = resolve_channel_id_simple(youtube, url_or_id)
    if not channel_id:
        st.error("チャンネルIDを解決できませんでした。正しい URL / ID / 表示名 を確認してください。")
        st.stop()

    st.write(f"**解析対象チャンネルID**: {channel_id}")

    basic = get_channel_basic(youtube, channel_id)
    if not basic:
        st.error("チャンネル情報の取得に失敗しました。")
        st.stop()

    published_at_raw = basic.get("publishedAt")
    published_dt = None
    if published_at_raw:
        try:
            published_dt = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
        except Exception:
            published_dt = None

    months_active = round(((datetime.utcnow().replace(tzinfo=timezone.utc) - published_dt).days / 30), 2) if published_dt else None

    subs = basic.get("subscriberCount", 0)
    vids_total = basic.get("videoCount", 0)
    views_total = basic.get("viewCount", 0)

    video_ids_10 = search_video_ids_published_after(youtube, channel_id, 10)
    stats_10 = get_videos_stats(youtube, video_ids_10) if video_ids_10 else {}
    total_views_last10 = sum(v.get("viewCount", 0) for v in stats_10.values())
    num_videos_last10 = len(stats_10)

    video_ids_30 = search_video_ids_published_after(youtube, channel_id, 30)
    stats_30 = get_videos_stats(youtube, video_ids_30) if video_ids_30 else {}
    total_views_last30 = sum(v.get("viewCount", 0) for v in stats_30.values())
    num_videos_last30 = len(stats_30)

    if num_videos_last10 > 0:
        top_vid_10 = max(stats_10.items(), key=lambda kv: kv[1]["viewCount"])
        top_video_id = top_vid_10[0]
        top_info = top_vid_10[1]
        top_views_last10 = top_info["viewCount"]
        top_title_last10 = top_info["title"] or "(title unavailable)"
        top_url_last10 = f"https://www.youtube.com/watch?v={top_video_id}"
        top_share_last10 = round((top_views_last10 / total_views_last10) if total_views_last10 > 0 else 0.0, 4)
    else:
        top_video_id = None
        top_title_last10 = "-"
        top_views_last10 = 0
        top_url_last10 = "-"
        top_share_last10 = 0.0

    views_per_sub_last30 = round((total_views_last30 / subs), 5) if subs > 0 else 0.0
    avg_views_per_video_last10 = round((total_views_last10 / num_videos_last10), 2) if num_videos_last10 > 0 else 0.0

    playlists_meta = get_playlists_meta(youtube, channel_id)
    playlist_count = len(playlists_meta)
    playlists_sorted = sorted(playlists_meta, key=lambda x: x["itemCount"], reverse=True)
    top5_playlists = playlists_sorted[:5]
    while len(top5_playlists) < 5:
        top5_playlists.append({"title": "-", "itemCount": "-"})

    colA, colB = st.columns([2, 2])

    with colA:
        st.write("### 基本情報")
        st.write(f"**チャンネル名**: {basic.get('title')}")
        st.write(f"**登録者数**: {subs}")
        st.write(f"**動画本数**: {vids_total}")
        st.write(f"**総再生回数**: {views_total}")
        st.write(f"**活動開始日**: {published_dt.strftime('%Y-%m-%d') if published_dt else '不明'}")
        st.write(f"**活動月数**: {months_active if months_active is not None else '-'}")
        st.write(f"**再生リスト数**: {playlist_count}"_
