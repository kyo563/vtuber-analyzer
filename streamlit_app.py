# app.py
import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import io
from typing import List, Dict, Optional

# --------------------
# 設定
# --------------------
st.set_page_config(page_title="分析ツール", layout="wide")

# APIキー取得（推薦：st.secrets に YOUTUBE_API_KEY を入れる）
API_KEY = st.secrets.get("YOUTUBE_API_KEY") if "YOUTUBE_API_KEY" in st.secrets else None
if not API_KEY:
    API_KEY = st.sidebar.text_input("YouTube API Key (一時入力可)", type="password")

if not API_KEY:
    st.sidebar.error("YouTube API Key を設定してください（Streamlit secrets を推奨）。")

# build client は実行時に作る（st.cache_data は service オブジェクトをキャッシュしない方が安全）
def build_youtube(api_key: str):
    return build("youtube", "v3", developerKey=api_key)

# --------------------
# ヘルパー関数（キャッシュ有り）
# --------------------
@st.cache_data(ttl=3600)
def resolve_channel_id_simple(youtube_service, url_or_id: str) -> Optional[str]:
    """
    簡易的な channelId 解決:
    - UC... の直接入力
    - /channel/ URL
    - それ以外は search.type=channel でフォールバック（最良候補を返す）
    """
    s = (url_or_id or "").strip()
    if not s:
        return None
    if s.startswith("UC") and len(s) == 24:
        return s
    if "channel/" in s:
        return s.split("channel/")[1].split("/")[0]
    # フォールバック検索
    try:
        resp = youtube_service.search().list(
            q=s, type="channel", part="snippet", maxResults=3
        ).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
    except Exception:
        return None
    return None

@st.cache_data(ttl=3600)
def get_channel_basic(youtube_service, channel_id: str) -> Optional[Dict]:
    """channels.list で基本情報を取得"""
    try:
        resp = youtube_service.channels().list(
            part="snippet,statistics,contentDetails",
            id=channel_id,
            maxResults=1
        ).execute()
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
    """チャンネルのプレイリスト一覧（title, itemCount, playlistId）を取得"""
    pls = []
    next_page = None
    try:
        while True:
            resp = youtube_service.playlists().list(
                part="snippet,contentDetails",
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page
            ).execute()
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
    """
    channelId の中で publishedAfter (UTC) 以降に公開された動画の videoId を収集する。
    search.list を利用（publishedAfter で絞る）。ページネーション対応。
    """
    video_ids = []
    published_after = (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    next_page = None
    try:
        while True:
            resp = youtube_service.search().list(
                part="id",
                channelId=channel_id,
                publishedAfter=published_after,
                type="video",
                maxResults=50,
                pageToken=next_page
            ).execute()
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
    """
    videos.list で videoId -> {title, viewCount, likeCount} をまとめて返す。
    50件チャンクでまとめて取得。
    """
    out = {}
    if not video_ids:
        return out
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        try:
            resp = youtube_service.videos().list(
                part="snippet,statistics",
                id=",".join(chunk),
                maxResults=50
            ).execute()
            for it in resp.get("items", []):
                vid = it.get("id")
                out[vid] = {
                    "title": it.get("snippet", {}).get("title", ""),
                    "viewCount": int(it.get("statistics", {}).get("viewCount", 0) or 0),
                    "likeCount": int(it.get("statistics", {}).get("likeCount", 0) or 0)
                }
        except Exception:
            # 部分失敗でも可能な限り返す
            continue
    return out

@st.cache_data(ttl=300)
def fetch_playlist_items_sample(youtube_service, playlist_id: str, max_items: int = 100) -> List[Dict]:
    """
    playlistItems を遅延取得（プレイリスト展開用）。最大取得数を制限して呼ぶ。
    返すのは videoId, title, publishedAt。
    """
    items = []
    next_page = None
    try:
        while True and len(items) < max_items:
            resp = youtube_service.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page
            ).execute()
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

# --------------------
# UI: 入力部分
# --------------------
st.title("YouTube チャンネル解析ツール（直近指標 + プレイリスト展開）")
st.markdown("ID")

col_input, col_info = st.columns([3, 1])
with col_input:
    url_or_id = st.text_input("ID / 表示名 を入力")
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

    # チャンネルID解決
    channel_id = resolve_channel_id_simple(youtube, url_or_id)
    if not channel_id:
        st.error("チャンネルIDを解決できませんでした。正しい URL / ID / 表示名 を確認してください。")
        st.stop()

    st.write(f"**解析対象チャンネルID**: {channel_id}")

    # 基本情報取得
    basic = get_channel_basic(youtube, channel_id)
    if not basic:
        st.error("チャンネル情報の取得に失敗しました。")
        st.stop()

    # 活動月数等の計算（publishedAt のフォーマットに対応）
    published_at_raw = basic.get("publishedAt")
    published_dt = None
    if published_at_raw:
        try:
            published_dt = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
        except Exception:
            published_dt = None

    months_active = round(((datetime.utcnow().replace(tzinfo=timezone.utc) - published_dt).days / 30), 2) if published_dt else None

    # 既存の主要指標（重複を避ける）
    subs = basic.get("subscriberCount", 0)
    vids_total = basic.get("videoCount", 0)
    views_total = basic.get("viewCount", 0)

    # 直近10日・30日の動画群を取得（publishedAfter を使う方法）
    video_ids_10 = search_video_ids_published_after(youtube, channel_id, 10)
    stats_10 = get_videos_stats(youtube, video_ids_10) if video_ids_10 else {}
    total_views_last10 = sum(v.get("viewCount", 0) for v in stats_10.values())
    num_videos_last10 = len(stats_10)

    video_ids_30 = search_video_ids_published_after(youtube, channel_id, 30)
    stats_30 = get_videos_stats(youtube, video_ids_30) if video_ids_30 else {}
    total_views_last30 = sum(v.get("viewCount", 0) for v in stats_30.values())
    num_videos_last30 = len(stats_30)

    # 直近10日のトップ動画（タイトル, views, URL, シェア）
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

    # 代替指標（重複を置き換え）
    # ・直近30日：views_last30 / subscriberCount（視聴/登録比）
    views_per_sub_last30 = round((total_views_last30 / subs), 5) if subs > 0 else 0.0
    # ・直近10日：動画当たり平均再生数
    avg_views_per_video_last10 = round((total_views_last10 / num_videos_last10), 2) if num_videos_last10 > 0 else 0.0

    # 再生リスト情報（メタのみ）
    playlists_meta = get_playlists_meta(youtube, channel_id)
    playlist_count = len(playlists_meta)
    playlists_sorted = sorted(playlists_meta, key=lambda x: x["itemCount"], reverse=True)
    top5_playlists = playlists_sorted[:5]
    while len(top5_playlists) < 5:
        top5_playlists.append({"title": "-", "itemCount": "-"})

    # 表示（左：数値、右：直近指標／プレイリスト）
    colA, colB = st.columns([2, 2])

    with colA:
        st.write("### 基本情報")
        st.write(f"**チャンネル名**: {basic.get('title')}")
        st.write(f"**登録者数**: {subs}")
        st.write(f"**動画本数**: {vids_total}")
        st.write(f"**総再生回数**: {views_total}")
        st.write(f"**活動開始日**: {published_dt.strftime('%Y-%m-%d') if published_dt else '不明'}")
        st.write(f"**活動月数**: {months_active if months_active is not None else '-'}")
        st.write(f"**再生リスト数**: {playlist_count}")

        st.write("### 置き換えた新指標（直近）")
        st.write(f"直近10日 合計再生数（直近公開動画のみ）: {total_views_last10}")
        st.write(f"直近10日 投稿数: {num_videos_last10}")
        st.write(f"直近10日 トップ動画: {top_title_last10} — {top_views_last10} views — シェア: {top_share_last10:.2%}")
        st.write(f"直近10日 平均再生（動画あたり）: {avg_views_per_video_last10}")
        st.write(f"直近30日 合計再生数（直近公開動画のみ）: {total_views_last30}")
        st.write(f"直近30日 投稿数: {num_videos_last30}")
        st.write(f"直近30日 視聴/登録比 (views_last30 / subscribers): {views_per_sub_last30}")

    with colB:
        st.write("### 上位プレイリスト（件数順）")
        for i, pl in enumerate(top5_playlists, start=1):
            st.write(f"{i}位: {pl['title']} → {pl['itemCount']} 本")

        st.write("### 直近10日トップ動画（詳細）")
        if top_video_id:
            st.markdown(f"- [{top_title_last10}]({top_url_last10})")
            st.write(f"  - 再生数: {top_views_last10}")
            st.write(f"  - シェア: {top_share_last10:.2%}")
        else:
            st.write("該当する直近10日間の公開動画がありません。")

    # TXT ダウンロード（既存出力フォーマットを踏襲しつつ更新）
    # 追加指標をまとめて計算（テキスト出力に含める）
    subs_per_month = round((subs / months_active), 2) if months_active and months_active > 0 else 0.0
    subs_per_video = round((subs / vids_total), 2) if vids_total and vids_total > 0 else 0.0
    views_per_sub = round((views_total / subs), 2) if subs > 0 else 0.0
    subs_per_month_per_video = round((subs_per_month / vids_total), 5) if vids_total and vids_total > 0 else 0.0
    views_per_video = round((views_total / vids_total), 2) if vids_total and vids_total > 0 else 0.0
    views_per_month = round((views_total / months_active), 2) if months_active and months_active > 0 else 0.0
    subs_per_view = round((subs_per_month / views_per_month), 5) if views_per_month and views_per_month > 0 else 0.0
    subs_per_view_alt = round((subs_per_video / views_per_video), 5) if views_per_video and views_per_video > 0 else 0.0
    subs_per_total_view = round((subs / views_total), 5) if views_total and views_total > 0 else 0.0
    playlists_per_video = round((playlist_count / vids_total), 5) if vids_total and vids_total > 0 else 0.0
    videos_per_month = round((vids_total / months_active), 2) if months_active and months_active > 0 else 0.0
    videos_per_subscriber = round((vids_total / subs), 5) if subs and subs > 0 else 0.0

    txt_output = io.StringIO()
    txt_output.write(f"{channel_id}
")
    txt_output.write(f"{basic.get('title')}
")
    txt_output.write(f"{subs}
")
    txt_output.write(f"{vids_total}
")
    txt_output.write(f"{published_dt.strftime('%Y-%m-%d') if published_dt else '-'}
")
    txt_output.write(f"{months_active if months_active is not None else '-'}
")
    txt_output.write(f"{subs_per_month}
")
    txt_output.write(f"{subs_per_video}
")
    txt_output.write(f"{views_total}
")
    txt_output.write(f"{views_per_sub}
")
    txt_output.write(f"{playlist_count}
")
    txt_output.write(f"{subs_per_month_per_video}
")
    txt_output.write(f"{views_per_video}
")
    txt_output.write(f"{views_per_month}
")
    txt_output.write(f"{subs_per_view}
")
    txt_output.write(f"{subs_per_view_alt}
")
    txt_output.write(f"{subs_per_total_view}
")
    txt_output.write(f"{playlists_per_video}
")
    txt_output.write(f"{videos_per_month}
")
    txt_output.write(f"{videos_per_subscriber}
")

    # 新指標も続けて追記（直近10日/30日系）
    txt_output.write(f"{total_views_last10}
")           # 直近10日 合計再生数 (直近公開動画)
    txt_output.write(f"{avg_views_per_video_last10}
")  # 直近10日 平均再生
    txt_output.write(f"{views_per_sub_last30}
")        # 直近30日 視聴/登録比
    txt_output.write(f"{playlist_count}
")

    txt_output.write("
動画本数が多い上位5再生リスト:
")
    for i, pl in enumerate(top5_playlists, 1):
        txt_output.write(f"{i}位: {pl['title']}　→ {pl['itemCount']}本
")

    # 画面下部：プレイリスト展開（遅延取得）
    st.write("### プレイリスト詳細（クリックで展開・遅延取得）")
    for pl in playlists_sorted[:20]:  # UI上は最大20件まで表示（expanderで展開可能）
        pid = pl.get("playlistId")
        title = pl.get("title")
        count = pl.get("itemCount")
        with st.expander(f"{title} — {count} 本"):
            # 展開時に中身を取得（最大100件）
            pl_items = fetch_playlist_items_sample(youtube, pid, max_items=100)
            if not pl_items:
                st.write("プレイリスト内の取得に失敗、または空です。")
            else:
                for idx, it in enumerate(pl_items, start=1):
                    url = f"https://www.youtube.com/watch?v={it['videoId']}"
                    pub = it.get("publishedAt") or "-"
                    st.markdown(f"{idx}. [{it.get('title')}]({url}) — 公開: {pub}")

    # ダウンロードボタン（右カラム）
    st.download_button(
        "TXTダウンロード",
        data=txt_output.getvalue().encode("utf-8"),
        file_name="vt_stats.txt"
    )

    # 運用ノートを表示
    st.markdown("---")
    st.write("運用メモ（重要）:")
    st.write("- 直近N日系指標は「その期間に公開された動画が現在までに獲得した再生数」を集計しています。")
    st.write("- 期間中に既に公開されていた動画が期間内に稼いだ増分は取得できません（チャンネル全体の期間内総再生数を得るには YouTube Analytics API が必要です）。")
    st.write("- プレイリスト展開はユーザーがクリックしたタイミングで取得するため、クォータ消費を抑えられます。")
