import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
import io
import json
import streamlit.components.v1 as components

st.set_page_config(page_title="解析ツール", layout="wide")

# ===== 注釈用 CSS =====
st.markdown(
    """
    <style>
    .metric-note {
        color: #888888;      /* 注釈用の少し暗めの色 */
        font-size: 0.9em;    /* 少しだけ小さく（好みで調整可） */
    }
    .copy-btn {
        background-color: #FF4B4B;
        color: white;
        border: none;
        padding: 0.25rem 0.75rem;
        border-radius: 0.25rem;
        cursor: pointer;
        font-size: 0.9rem;
    }
    .copy-btn:hover {
        opacity: 0.9;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===== APIキー（推奨：Streamlit secrets に YOUTUBE_API_KEY を設定） =====
API_KEY = st.secrets.get("YOUTUBE_API_KEY", None)
if not API_KEY:
    API_KEY = st.sidebar.text_input("YouTube API Key (一時入力可)", type="password")


# ===== YouTube client =====
@st.cache_resource
def get_youtube_client(api_key: str):
    """
    YouTube Data API クライアント（APIキーごとに1インスタンス）
    """
    if not api_key:
        raise RuntimeError("YouTube API key is not configured.")
    return build("youtube", "v3", developerKey=api_key)


# ===== 共通：URL/表示名 → チャンネルID解決 =====
@st.cache_data(ttl=3600)
def resolve_channel_id_simple(url_or_id: str, api_key: str) -> Optional[str]:
    """
    URL / ID / 表示名 からチャンネルID(UC〜)を推定して返す。
    - 既に UC〜24桁 → それを返す
    - URLに channel/UC〜 が含まれていれば抜き出す
    - それ以外は search().list(type=channel) で検索し、最初のチャンネルIDを返す
    """
    s = (url_or_id or "").strip()
    if not s:
        return None

    # 生のチャンネルID（UC〜で始まる24桁）
    if s.startswith("UC") and len(s) == 24:
        return s

    # https://www.youtube.com/channel/UC... 形式
    if "channel/" in s:
        return s.split("channel/")[1].split("/")[0]

    youtube = get_youtube_client(api_key)

    try:
        resp = youtube.search().list(
            q=s,
            type="channel",
            part="id,snippet",
            maxResults=3,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return None

        # 正しいパスは item["id"]["channelId"]
        return items[0].get("id", {}).get("channelId")
    except Exception:
        return None


# ===== チャンネル基本情報 =====
@st.cache_data(ttl=3600)
def get_channel_basic(channel_id: str, api_key: str) -> Optional[Dict]:
    youtube = get_youtube_client(api_key)
    try:
        resp = youtube.channels().list(
            part="snippet,statistics,contentDetails",
            id=channel_id,
            maxResults=1,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return None

        it = items[0]
        snippet = it.get("snippet", {}) or {}
        stats = it.get("statistics", {}) or {}
        uploads = it.get("contentDetails", {}).get("relatedPlaylists", {}) or {}

        return {
            "channelId": channel_id,
            "title": snippet.get("title"),
            "publishedAt": snippet.get("publishedAt"),
            "subscriberCount": int(stats.get("subscriberCount", 0) or 0),
            "videoCount": int(stats.get("videoCount", 0) or 0),
            "viewCount": int(stats.get("viewCount", 0) or 0),
            "uploadsPlaylistId": uploads.get("uploads"),
        }
    except Exception:
        return None


# ===== プレイリスト情報 =====
@st.cache_data(ttl=1800)
def get_playlists_meta(channel_id: str, api_key: str) -> List[Dict]:
    youtube = get_youtube_client(api_key)
    pls: List[Dict] = []
    next_page: Optional[str] = None

    try:
        while True:
            resp = youtube.playlists().list(
                part="snippet,contentDetails",
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page,
            ).execute()
            for pl in resp.get("items", []):
                pls.append(
                    {
                        "playlistId": pl.get("id"),
                        "title": pl.get("snippet", {}).get("title"),
                        "itemCount": int(pl.get("contentDetails", {}).get("itemCount", 0) or 0),
                    }
                )
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except Exception:
        # 取得失敗時は空リストを返す
        pass

    return pls


# ===== 期間指定で動画ID取得 =====
@st.cache_data(ttl=900)
def search_video_ids_published_after(
    channel_id: str,
    days: int,
    api_key: str,
) -> List[str]:
    youtube = get_youtube_client(api_key)
    video_ids: List[str] = []

    published_after = (
        datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")

    next_page: Optional[str] = None

    try:
        while True:
            resp = youtube.search().list(
                part="id",
                channelId=channel_id,
                publishedAfter=published_after,
                type="video",
                maxResults=50,
                pageToken=next_page,
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


# ===== 複数動画の統計 =====
@st.cache_data(ttl=1800)
def get_videos_stats(video_ids: Tuple[str, ...], api_key: str) -> Dict[str, Dict]:
    youtube = get_youtube_client(api_key)
    out: Dict[str, Dict] = {}

    if not video_ids:
        return out

    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        try:
            resp = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(chunk),
                maxResults=50,
            ).execute()
            for it in resp.get("items", []):
                vid = it.get("id")
                if not vid:
                    continue
                snippet = it.get("snippet", {}) or {}
                stats = it.get("statistics", {}) or {}
                out[vid] = {
                    "title": snippet.get("title", "") or "",
                    "viewCount": int(stats.get("viewCount", 0) or 0),
                    "likeCount": int(stats.get("likeCount", 0) or 0),
                }
        except Exception:
            continue

    return out


# ===== 注釈付きメトリクス 1行表示用ヘルパ =====
def metric_line(label: str, value, note: Optional[str] = None, buf: Optional[list] = None):
    """
    label: 左側の指標名
    value: 値
    note : 「（〜〜）」内に入れる説明。metric-note クラスで色を落として表示。
    buf  : コピー用テキストを蓄積するリスト（任意）
    """
    if note:
        text = f"{label}: {value}（{note}）"
        st.markdown(
            f"{label}: {value} "
            f"<span class='metric-note'>（{note}）</span>",
            unsafe_allow_html=True,
        )
    else:
        text = f"{label}: {value}"
        st.markdown(text, unsafe_allow_html=True)

    if buf is not None:
        buf.append(text)


# ==================== UI / Main ====================

st.title("解析ツール")

# top row: input | buttons (集計 + ダウンロード) | info
col_input, col_buttons, col_info = st.columns([3, 1, 1])

with col_input:
    url_or_id = st.text_input("URL / ID / 表示名 を入力")

with col_buttons:
    run_btn = st.button("集計")
    download_placeholder = st.empty()
    copy_placeholder = st.empty()

with col_info:
    st.write("動作メモ")
    st.write("- APIキーは Streamlit secrets に設定してください。")
    st.write("- キャッシュを活用してクォータを節約しています。")

if run_btn:
    if not API_KEY:
        st.error("APIキー未設定です。サイドバーまたは secrets に設定してください。")
        st.stop()

    # ここから先の全API呼び出しは同じ API_KEY を明示的に渡す
    channel_id = resolve_channel_id_simple(url_or_id, API_KEY)
    if not channel_id:
        st.error("チャンネルIDを解決できませんでした。URL / ID / 表示名を確認してください。")
        st.stop()

    basic = get_channel_basic(channel_id, API_KEY)
    if not basic:
        st.error("チャンネル情報の取得に失敗しました。")
        st.stop()

    # データ取得日
    data_date = datetime.utcnow().strftime("%Y/%m/%d")

    # publishedAt -> datetime
    published_at_raw = basic.get("publishedAt")
    published_dt: Optional[datetime] = None
    if published_at_raw:
        try:
            published_dt = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
        except Exception:
            published_dt = None

    if published_dt:
        days_active = (datetime.utcnow().replace(tzinfo=timezone.utc) - published_dt).days
        months_active = round(days_active / 30, 2)
    else:
        months_active = None

    subs = basic.get("subscriberCount", 0)
    vids_total = basic.get("videoCount", 0)
    views_total = basic.get("viewCount", 0)

    # 直近10日・30日の動画ID & stats
    ids_10 = search_video_ids_published_after(channel_id, 10, API_KEY)
    stats_10 = get_videos_stats(tuple(ids_10), API_KEY) if ids_10 else {}
    total_views_last10 = sum(v.get("viewCount", 0) for v in stats_10.values())
    num_videos_last10 = len(stats_10)

    ids_30 = search_video_ids_published_after(channel_id, 30, API_KEY)
    stats_30 = get_videos_stats(tuple(ids_30), API_KEY) if ids_30 else {}
    total_views_last30 = sum(v.get("viewCount", 0) for v in stats_30.values())
    num_videos_last30 = len(stats_30)

    # 直近10日のトップ動画
    if num_videos_last10 > 0:
        top_vid_10 = max(stats_10.items(), key=lambda kv: kv[1]["viewCount"])
        top_video_id = top_vid_10[0]
        top_info = top_vid_10[1]
        top_views_last10 = top_info["viewCount"]
        top_share_last10 = round(
            (top_views_last10 / total_views_last10) if total_views_last10 > 0 else 0.0,
            4,
        )
        top_title_last10 = (top_info.get("title") or "").replace("\n", " ").strip()
    else:
        top_video_id = None
        top_views_last10 = 0
        top_share_last10 = 0.0
        top_title_last10 = ""

    # 直近30日のトップ動画
    if num_videos_last30 > 0:
        top_vid_30 = max(stats_30.items(), key=lambda kv: kv[1]["viewCount"])
        top_video_id_30 = top_vid_30[0]
        top_info_30 = top_vid_30[1]
        top_views_last30 = top_info_30["viewCount"]
        top_share_last30 = round(
            (top_views_last30 / total_views_last30) if total_views_last30 > 0 else 0.0,
            4,
        )
        top_title_last30 = (top_info_30.get("title") or "").replace("\n", " ").strip()
    else:
        top_video_id_30 = None
        top_views_last30 = 0
        top_share_last30 = 0.0
        top_title_last30 = ""

    # 各種指標計算
    views_per_sub = round((views_total / subs), 2) if subs > 0 else 0.0
    subs_per_total_view = round((subs / views_total), 5) if views_total > 0 else 0.0
    views_per_video = round((views_total / vids_total), 2) if vids_total > 0 else 0.0

    views_per_sub_last10 = round((total_views_last10 / subs), 5) if subs > 0 else 0.0
    views_per_sub_last30 = round((total_views_last30 / subs), 5) if subs > 0 else 0.0

    avg_views_per_video_last10 = (
        round((total_views_last10 / num_videos_last10), 2) if num_videos_last10 > 0 else 0.0
    )
    avg_views_per_video_last30 = (
        round((total_views_last30 / num_videos_last30), 2) if num_videos_last30 > 0 else 0.0
    )

    playlists_meta = get_playlists_meta(channel_id, API_KEY)
    playlist_count = len(playlists_meta)
    playlists_sorted = sorted(playlists_meta, key=lambda x: x["itemCount"], reverse=True)
    top5_playlists = playlists_sorted[:5]
    while len(top5_playlists) < 5:
        top5_playlists.append({"title": "-", "itemCount": "-"})

    playlists_per_video = round((playlist_count / vids_total), 5) if vids_total > 0 else 0.0
    videos_per_month = (
        round((vids_total / months_active), 2)
        if months_active is not None and months_active > 0
        else 0.0
    )
    videos_per_subscriber = round((vids_total / subs), 5) if subs > 0 else 0.0
    subs_per_month = (
        round((subs / months_active), 2)
        if months_active is not None and months_active > 0
        else 0.0
    )
    subs_per_video = round((subs / vids_total), 2) if vids_total > 0 else 0.0
    subs_per_month_per_video = round((subs_per_month / vids_total), 5) if vids_total > 0 else 0.0
    views_per_month = (
        round((views_total / months_active), 2)
        if months_active is not None and months_active > 0
        else 0.0
    )

    # コピー用テキストバッファ（UI表示内容＋注釈付き）
    summary_lines: list = []
    summary_lines.append("=== 集計結果 ===")
    summary_lines.append("")
    summary_lines.append("■ 基本情報")
    summary_lines.append(f"データ取得日: {data_date}（このツールで集計を行った日）")
    summary_lines.append(f"チャンネルID: {channel_id}（UCから始まる固有ID）")
    summary_lines.append(f"チャンネル名: {basic.get('title')}")
    summary_lines.append(f"登録者数: {subs}（現在の登録者総数）")
    summary_lines.append(f"動画本数: {vids_total}（公開済み動画の本数）")
    summary_lines.append(f"総再生回数: {views_total}（公開済み動画の累計再生数）")
    summary_lines.append(
        f"活動開始日: {published_dt.strftime('%Y-%m-%d') if published_dt else '不明'}"
        "（チャンネル作成日）"
    )
    summary_lines.append(
        f"活動月数: {months_active if months_active is not None else '-'}"
        "（チャンネル開設からの日数 ÷ 30 を概算）"
    )
    summary_lines.append("")

    # ===== 表示 =====
    st.header("集計結果")
    col1, col2 = st.columns([2, 2])

    # --- 左カラム：基本情報＋集計 ---
    with col1:
        st.subheader("基本情報")
        st.write(f"データ取得日: {data_date}（このツールで集計を行った日）")
        st.write(f"チャンネルID: {channel_id}（UCから始まる固有ID）")
        st.write(f"チャンネル名: {basic.get('title')}")
        st.write(f"登録者数: {subs}（現在の登録者総数）")
        st.write(f"動画本数: {vids_total}（公開済み動画の本数）")
        st.write(f"総再生回数: {views_total}（公開済み動画の累計再生数）")
        st.write(
            f"活動開始日: {published_dt.strftime('%Y-%m-%d') if published_dt else '不明'}"
            "（チャンネル作成日）"
        )
        st.write(
            f"活動月数: {months_active if months_active is not None else '-'}"
            "（チャンネル開設からの日数 ÷ 30 を概算）"
        )

        st.subheader("集計")
        metric_line("累計登録者数/活動月", subs_per_month, "現在の登録者数 ÷ 活動月数", summary_lines)
        metric_line("累計登録者数/動画", subs_per_video, "現在の登録者数 ÷ 動画本数", summary_lines)
        metric_line("累計動画あたり総再生回数", views_per_video, "総再生回数 ÷ 動画本数", summary_lines)
        metric_line("累計総再生回数/登録者数", views_per_sub, "総再生回数 ÷ 登録者数", summary_lines)
        metric_line("1再生あたり登録者増", subs_per_total_view, "登録者数 ÷ 総再生回数", summary_lines)
        metric_line("動画あたりプレイリスト数", playlists_per_video, "プレイリスト総数 ÷ 動画本数", summary_lines)
        metric_line("活動月あたり動画本数", videos_per_month, "動画本数 ÷ 活動月数", summary_lines)
        metric_line("登録者あたり動画本数", videos_per_subscriber, "動画本数 ÷ 登録者数", summary_lines)

        st.subheader("上位プレイリスト（件数順）")
        summary_lines.append("")
        summary_lines.append("■ 上位プレイリスト（件数順）")
        for i, pl in enumerate(top5_playlists, start=1):
            line = f"{i}位: {pl['title']} → {pl['itemCount']}本"
            st.write(line)
            summary_lines.append(line)

    # --- 右カラム：直近指標 ---
    with col2:
        st.subheader("直近指標")
        summary_lines.append("")
        summary_lines.append("■ 直近指標")
        metric_line(
            "直近10日 合計再生数",
            total_views_last10,
            "直近10日間に公開された動画の再生数合計",
            summary_lines,
        )
        metric_line(
            "直近10日 投稿数",
            num_videos_last10,
            "直近10日間に公開された公開動画本数",
            summary_lines,
        )

        st.write("直近10日 トップ動画:")
        summary_lines.append("直近10日 トップ動画:")
        if top_video_id:
            url_10 = f"https://www.youtube.com/watch?v={top_video_id}"
            st.markdown(
                f"- [{top_title_last10}]({url_10}) — "
                f"views: {top_views_last10}"
                f"<span class='metric-note'>（この動画単体の再生数）</span> "
                f"| share: {top_share_last10*100:.2f}%"
                f"<span class='metric-note'>（直近10日の合計再生数に占める割合）</span>",
                unsafe_allow_html=True,
            )
            summary_lines.append(
                f"- {top_title_last10} — "
                f"views: {top_views_last10}（この動画単体の再生数） | "
                f"share: {top_share_last10*100:.2f}%（直近10日の合計再生数に占める割合）"
            )
        else:
            st.write("- 該当する直近10日間の公開動画がありません。")
            summary_lines.append("- 該当する直近10日間の公開動画がありません。")

        metric_line(
            "直近10日 平均再生",
            avg_views_per_video_last10,
            "直近10日間の合計再生数 ÷ 投稿数",
            summary_lines,
        )
        metric_line(
            "直近10日 視聴/登録比",
            views_per_sub_last10,
            "直近10日の合計再生数 ÷ 現在の登録者数",
            summary_lines,
        )

        st.markdown("---")

        metric_line(
            "直近30日 合計再生数",
            total_views_last30,
            "直近30日間に公開された動画の再生数合計",
            summary_lines,
        )
        metric_line(
            "直近30日 投稿数",
            num_videos_last30,
            "直近30日間に公開された公開動画本数",
            summary_lines,
        )

        st.write("直近30日 トップ動画:")
        summary_lines.append("直近30日 トップ動画:")
        if top_video_id_30:
            url_30 = f"https://www.youtube.com/watch?v={top_video_id_30}"
            st.markdown(
                f"- [{top_title_last30}]({url_30}) — "
                f"views: {top_views_last30}"
                f"<span class='metric-note'>（この動画単体の再生数）</span> "
                f"| share: {top_share_last30*100:.2f}%"
                f"<span class='metric-note'>（直近30日の合計再生数に占める割合）</span>",
                unsafe_allow_html=True,
            )
            summary_lines.append(
                f"- {top_title_last30} — "
                f"views: {top_views_last30}（この動画単体の再生数） | "
                f"share: {top_share_last30*100:.2f}%（直近30日の合計再生数に占める割合）"
            )
        else:
            st.write("- 該当する直近30日間の公開動画がありません。")
            summary_lines.append("- 該当する直近30日間の公開動画がありません。")

        metric_line(
            "直近30日 平均再生",
            avg_views_per_video_last30,
            "直近30日間の合計再生数 ÷ 投稿数",
            summary_lines,
        )
        metric_line(
            "直近30日 視聴/登録比",
            views_per_sub_last30,
            "直近30日の合計再生数 ÷ 現在の登録者数",
            summary_lines,
        )

    summary_text = "\n".join(summary_lines)

    # ===== TXT ダウンロード用（注釈なしのCSVテキスト） =====
    txt_output = io.StringIO()

    # 基本情報
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

    # 上位プレイリスト
    for pl in top5_playlists:
        title = (pl.get("title", "") or "").replace("\n", " ").strip()
        txt_output.write(f"{title}→{pl.get('itemCount', '')}\n")

    # 直近10日
    txt_output.write(f"{total_views_last10}\n")
    txt_output.write(f"{num_videos_last10}\n")
    txt_output.write(f"{top_title_last10}\n")
    txt_output.write(f"{top_views_last10}\n")
    txt_output.write(f"{top_share_last10}\n")
    txt_output.write(f"{avg_views_per_video_last10}\n")
    txt_output.write(f"{views_per_sub_last10}\n")

    # 直近30日
    txt_output.write(f"{total_views_last30}\n")
    txt_output.write(f"{num_videos_last30}\n")
    txt_output.write(f"{top_title_last30}\n")
    txt_output.write(f"{top_views_last30}\n")
    txt_output.write(f"{top_share_last30}\n")
    txt_output.write(f"{avg_views_per_video_last30}\n")
    txt_output.write(f"{views_per_sub_last30}\n")

    txt_value = txt_output.getvalue()
    st.session_state["last_txt"] = txt_value
    st.session_state["summary_text"] = summary_text

    # ===== ダウンロード & コピー ボタン（同じ列に配置） =====
    with col_buttons:
        download_placeholder.download_button(
            "TXTダウンロード",
            data=txt_value.encode("utf-8"),
            file_name="vt_stats.txt",
        )

        components.html(
            f"""
            <button class="copy-btn" onclick="copyToClipboard()">集計結果をコピー</button>
            <script>
            function copyToClipboard() {{
                const text = {json.dumps(summary_text)};
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    navigator.clipboard.writeText(text);
                }} else {{
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                }}
            }}
            </script>
            """,
            height=80,
        )

    st.success("集計が完了しました。上部のボタンからTXTダウンロード / コピーができます。")
