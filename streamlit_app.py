# streamlit_app.py — 修正版：直近指標のインデント修正済み（全文）
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

with col_buttons:
    run_btn = st.button("集計")
    last_txt = st.session_state.get("last_txt") if "last_txt" in st.session_state else None
    if last_txt:
        st.download_button("TXTダウンロード", data=last_txt.encode("utf-8"), file_name="vt_stats.txt")
    else:
        st.write("")

with col_info:
    st.write("動作メモ")
    st.write("- APIキーは Streamlit secrets に設定してください。")
    st.write("- キャッシュを活用してクォータを節約しています。")

if run_btn:
    if not API_KEY:
        st.error("APIキー未設定です。サイドバーまたは secrets に設定してください。")
        st.stop()

    channel_id = resolve_channel_id_simple(url_or_id)
    if not channel_id:
        st.error("チャンネルIDを解決できませんでした。")
        st.stop()

    basic = get_channel_basic(channel_id)
    if not basic:
        st.error("チャンネル情報の取得に失敗しました。")
        st.stop()

    # データ取得日
    data_date = datetime.utcnow().strftime("%Y/%m/%d")

    # publishedAt -> datetime
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

    # 直近10日・30日の動画ID を取得して stats をまとめる
    ids_10 = search_video_ids_published_after(channel_id, 10)
    stats_10 = get_videos_stats(tuple(ids_10)) if ids_10 else {}
    total_views_last10 = sum(v.get("viewCount", 0) for v in stats_10.values())
    num_videos_last10 = len(stats_10)

    ids_30 = search_video_ids_published_after(channel_id, 30)
    stats_30 = get_videos_stats(tuple(ids_30)) if ids_30 else {}
    total_views_last30 = sum(v.get("viewCount", 0) for v in stats_30.values())
    num_videos_last30 = len(stats_30)

    # 直近10日のトップ動画（views と share のみ）
    if num_videos_last10 > 0:
        top_vid_10 = max(stats_10.items(), key=lambda kv: kv[1]["viewCount"])
        top_video_id = top_vid_10[0]
        top_info = top_vid_10[1]
        top_views_last10 = top_info["viewCount"]
        top_share_last10 = round((top_views_last10 / total_views_last10) if total_views_last10 > 0 else 0.0, 4)
    else:
        top_video_id = None
        top_views_last10 = 0
        top_share_last10 = 0.0

    # 直近30日のトップ動画（views と share のみ）
    if num_videos_last30 > 0:
        top_vid_30 = max(stats_30.items(), key=lambda kv: kv[1]["viewCount"])
        top_video_id_30 = top_vid_30[0]
        top_info_30 = top_vid_30[1]
        top_views_last30 = top_info_30["viewCount"]
        top_share_last30 = round((top_views_last30 / total_views_last30) if total_views_last30 > 0 else 0.0, 4)
    else:
        top_video_id_30 = None
        top_views_last30 = 0
        top_share_last30 = 0.0

    # 指標計算（簡潔表示用）
    views_per_sub = round((views_total / subs), 2) if subs > 0 else 0.0
    subs_per_total_view = round((subs / views_total), 5) if views_total and views_total > 0 else 0.0
    views_per_video = round((views_total / vids_total), 2) if vids_total and vids_total > 0 else 0.0

    views_per_sub_last10 = round((total_views_last10 / subs), 5) if subs > 0 else 0.0
    views_per_sub_last30 = round((total_views_last30 / subs), 5) if subs > 0 else 0.0

    avg_views_per_video_last10 = round((total_views_last10 / num_videos_last10), 2) if num_videos_last10 > 0 else 0.0
    avg_views_per_video_last30 = round((total_views_last30 / num_videos_last30), 2) if num_videos_last30 > 0 else 0.0

    playlists_meta = get_playlists_meta(channel_id)
    playlist_count = len(playlists_meta)
    playlists_sorted = sorted(playlists_meta, key=lambda x: x["itemCount"], reverse=True)
    top5_playlists = playlists_sorted[:5]
    while len(top5_playlists) < 5:
        top5_playlists.append({"title": "-", "itemCount": "-"})

    playlists_per_video = round((playlist_count / vids_total), 5) if vids_total and vids_total > 0 else 0.0
    videos_per_month = round((vids_total / months_active), 2) if months_active and months_active > 0 else 0.0
    videos_per_subscriber = round((vids_total / subs), 5) if subs and subs > 0 else 0.0
    subs_per_month = round((subs / months_active), 2) if months_active and months_active > 0 else 0.0
    subs_per_video = round((subs / vids_total), 2) if vids_total and vids_total > 0 else 0.0
    subs_per_month_per_video = round((subs_per_month / vids_total), 5) if vids_total and vids_total > 0 else 0.0
    views_per_month = round((views_total / months_active), 2) if months_active and months_active > 0 else 0.0

    # --- 表示（簡潔ラベル） ---
    st.header("集計結果")
    col1, col2 = st.columns([2, 2])

    with col1:
        st.subheader("基本情報")
        st.write(f"データ取得日: {data_date}")
        st.write(f"チャンネルID: {channel_id}")
        st.write(f"チャンネル名: {basic.get('title')}")
        st.write(f"登録者数: {subs}")
        st.write(f"動画本数: {vids_total}")
        st.write(f"総再生回数: {views_total}")
        st.write(f"活動開始日: {published_dt.strftime('%Y-%m-%d') if published_dt else '不明'}")
        st.write(f"活動月数: {months_active if months_active is not None else '-'}")

        # 統合された集計（ここを上位プレイリストより上に表示）
        st.subheader("集計")
        st.write(f"累計登録者数/活動月: {subs_per_month}")
        st.write(f"累計登録者数/動画: {subs_per_video}")
        st.write(f"累計動画あたり総再生回数: {views_per_video}")
        st.write(f"累計総再生回数/登録者数: {views_per_sub}")
        st.write(f"1再生あたり登録者増: {subs_per_total_view}")
        st.write(f"動画あたりプレイリスト数: {playlists_per_video}")
        st.write(f"活動月あたり動画本数: {videos_per_month}")
        st.write(f"登録者あたり動画本数: {videos_per_subscriber}")

        # 上位プレイリスト（件数順）
        st.subheader("上位プレイリスト（件数順）")
        for i, pl in enumerate(top5_playlists, start=1):
            st.write(f"{i}位: {pl['title']} → {pl['itemCount']}本")

    with col2:
        # 右カラムには直近指標と補助情報を表示（指定の順序で）
        st.subheader("直近指標")
        st.write(f"直近10日 合計再生数: {total_views_last10}")
        st.write(f"直近10日 投稿数: {num_videos_last10}")
        st.write("直近10日 トップ動画:")
        if top_video_id:
            st.write(f"- views: {top_views_last10} | share: {top_share_last10:.4f}")
        else:
            st.write("- 該当する直近10日間の公開動画がありません。")
        st.write(f"直近10日 平均再生: {avg_views_per_video_last10}")
        st.write(f"直近10日 視聴/登録比: {views_per_sub_last10}")
        st.markdown("---")
        st.write(f"直近30日 合計再生数: {total_views_last30}")
        st.write(f"直近30日 投稿数: {num_videos_last30}")
        st.write("直近30日 トップ動画:")
        if top_video_id_30:
            st.write(f"- views: {top_views_last30} | share: {top_share_last30:.4f}")
        else:
            st.write("- 該当する直近30日間の公開動画がありません。")
        st.write(f"直近30日 平均再生: {avg_views_per_video_last30}")
        st.write(f"直近30日 視聴/登録比: {views_per_sub_last30}")

    # TXT ダウンロード用（結果のみを順番に出力） — セッションに保存して上部からダウンロード可能にする
    txt_output = io.StringIO()
    # 基本情報（結果のみ、順序通り）
    txt_output.write(f"{data_date}\n")
    txt_output.write(f"{channel_id}\n")
    txt_output.write(f"{basic.get('title') or ''}\n")
    txt_output.write(f"{subs}\n")
    txt_output.write(f"{vids_total}\n")
    txt_output.write(f"{views_total}\n")
    txt_output.write(f"{published_dt.strftime('%Y-%m-%d') if published_dt else ''}\n")
    txt_output.write(f"{months_active if months_active is not None else ''}\n")

    # 集計
    txt_output.write(f"{subs_per_month}\n")
    txt_output.write(f"{subs_per_video}\n")
    txt_output.write(f"{views_per_video}\n")
    txt_output.write(f"{views_per_sub}\n")
    txt_output.write(f"{subs_per_total_view}\n")
    txt_output.write(f"{playlists_per_video}\n")
    txt_output.write(f"{videos_per_month}\n")
    txt_output.write(f"{videos_per_subscriber}\n")

    # 上位プレイリスト（タイトルと件数）
    for pl in top5_playlists:
        txt_output.write(f"{pl.get('title','')}\t{pl.get('itemCount','')}\n")

    # 直近指標（10日）
    txt_output.write(f"{total_views_last10}\n")
    txt_output.write(f"{num_videos_last10}\n")
    txt_output.write(f"{top_views_last10}\n")
    txt_output.write(f"{top_share_last10}\n")
    txt_output.write(f"{avg_views_per_video_last10}\n")
    txt_output.write(f"{views_per_sub_last10}\n")

    # 直近指標（30日）
    txt_output.write(f"{total_views_last30}\n")
    txt_output.write(f"{num_videos_last30}\n")
    txt_output.write(f"{top_views_last30}\n")
    txt_output.write(f"{top_share_last30}\n")
    txt_output.write(f"{avg_views_per_video_last30}\n")
    txt_output.write(f"{views_per_sub_last30}\n")

    # セッション保存（上部ダウンロードボタンで参照される）
    st.session_state["last_txt"] = txt_output.getvalue()

    st.success("集計が完了しました。ページ上部の「TXTダウンロード」からダウンロードできます。")
