import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime
import io

API_KEY = "AIzaSyCJilGGK0Xj4tRojTkSZdmhHBbFNjHZbD4"
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

def get_channel_id_from_url(url_or_id):
    """
    URLの可能性がある文字列からチャンネルIDを抽出。
    もしくはIDのみが入力された場合はそのまま返す。
    """
    if url_or_id.startswith("UC"):  # ほぼ全てのYouTubeチャンネルIDはUCから始まる
        return url_or_id
    if "channel/" in url_or_id:
        return url_or_id.split("channel/")[1].split("/")[0]
    st.error("channel/形式のURLまたはチャンネルIDを入力してください。例）UCxxxxxxxxxxxx")
    return None

def get_channel_stats(channel_id):
    request = YOUTUBE.channels().list(part="snippet,statistics", id=channel_id)
    response = request.execute()
    stats = response["items"][0]["statistics"]
    snippet = response["items"][0]["snippet"]
    published = snippet.get("publishedAt")
    return {
        "title": snippet["title"],
        "subscriberCount": int(stats.get("subscriberCount", 0)),
        "videoCount": int(stats.get("videoCount", 0)),
        "viewCount": int(stats.get("viewCount", 0)),
        "publishedAt": published,
    }

def get_playlists_with_counts(channel_id):
    playlists = []
    next_page_token = None
    while True:
        request = YOUTUBE.playlists().list(
            channelId=channel_id,
            part="snippet,contentDetails",
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        for pl in response["items"]:
            playlists.append({
                "title": pl["snippet"]["title"],
                "count": int(pl["contentDetails"].get("itemCount", 0))
            })
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return playlists

def main():
    st.title("データ自動集計アプリ")
    url_or_id = st.text_input("YouTubeチャンネルURLまたはチャンネルIDを入力してください")
    if st.button("集計"):
        if not url_or_id:
            st.warning("URLまたはチャンネルIDを入力してください")
            return
        channel_id = get_channel_id_from_url(url_or_id)
        if not channel_id:
            return
        stats = get_channel_stats(channel_id)
        published_at = stats["publishedAt"]
        if not published_at:
            st.error("チャンネル作成日の取得に失敗しました（publishedAtが空です）。")
            return
        try:
            oldest_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            try:
                oldest_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
            except Exception as e:
                st.error(f"日付のフォーマットが不正です: {published_at}")
                return

        months_active = (datetime.utcnow() - oldest_date).days / 30
        subs_per_month = stats["subscriberCount"] / months_active if months_active > 0 else 0
        subs_per_video = stats["subscriberCount"] / stats["videoCount"] if stats["videoCount"] else 0
        subs_per_month_per_video = subs_per_month / stats["videoCount"] if stats["videoCount"] else 0
        view_per_sub = stats["viewCount"] / stats["subscriberCount"] if stats["subscriberCount"] else 0

        # ここから新規複合指標の計算
        views_per_video = stats["viewCount"] / stats["videoCount"] if stats["videoCount"] else 0
        views_per_month = stats["viewCount"] / months_active if months_active > 0 else 0
        subs_per_view = (subs_per_month) / (views_per_month) if views_per_month > 0 else 0
        subs_per_view_alt = (subs_per_video) / (views_per_video) if views_per_video > 0 else 0
        subs_per_total_view = stats["subscriberCount"] / stats["viewCount"] if stats["viewCount"] else 0
        playlists_per_video = len(get_playlists_with_counts(channel_id)) / stats["videoCount"] if stats["videoCount"] else 0
        videos_per_month = stats["videoCount"] / months_active if months_active > 0 else 0
        videos_per_subscriber = stats["videoCount"] / stats["subscriberCount"] if stats["subscriberCount"] else 0

        playlists = get_playlists_with_counts(channel_id)
        playlist_count = len(playlists)
        playlists_sorted = sorted(playlists, key=lambda x: x["count"], reverse=True)
        top5_playlists = playlists_sorted[:5]
        # 5件未満の場合は「-」を補填
        while len(top5_playlists) < 5:
            top5_playlists.append({"title": "-", "count": "-"})

        st.write("### 集計結果")
        st.write(f"**チャンネルID**: {channel_id}")
        st.write(f"**チャンネル名**: {stats['title']}")
        st.write(f"**登録者数**: {stats['subscriberCount']}")
        st.write(f"**動画本数**: {stats['videoCount']}")
        st.write(f"**活動月数**: {round(months_active,2)}")
        st.write(f"**登録者数/活動月**: {round(subs_per_month,2)}")
        st.write(f"**登録者数/動画**: {round(subs_per_video,2)}")
        st.write(f"**動画あたり月間登録者数増加数**: {round(subs_per_month_per_video,2)}")
        st.write(f"**総再生回数**: {stats['viewCount']}")
        st.write(f"**総再生回数/登録者数**: {round(view_per_sub,2)}")
        st.write(f"**再生リスト数**: {playlist_count}")
        st.write(f"**動画あたり総再生回数**: {round(views_per_video,2)}")
        st.write(f"**月間再生回数**: {round(views_per_month,2)}")
        st.write(f"**月間再生回数あたり登録者増加率**: {round(subs_per_view,6)}")
        st.write(f"**動画あたり再生回数あたり登録者数**: {round(subs_per_view_alt,6)}")
        st.write(f"**1再生あたり登録者数の伸び率（登録者あたり）**: {round(subs_per_total_view,6)}")
        st.write(f"**動画あたりプレイリスト数**: {round(playlists_per_video,6)}")
        st.write(f"**活動月あたり動画本数**: {round(videos_per_month,2)}")
        st.write(f"**登録者あたり動画本数**: {round(videos_per_subscriber,6)}")
        st.write(f"**URL**: https://www.youtube.com/channel/{channel_id}")

        st.write("### 動画本数が多い上位5再生リスト")
        for i, pl in enumerate(top5_playlists, 1):
            st.write(f"{i}位: {pl['title']}　→ {pl['count']}本")

        # テキスト出力
        txt_output = io.StringIO()
        txt_output.write(f"{channel_id}\n")
        txt_output.write(f"{stats['title']}\n")
        txt_output.write(f"{stats['subscriberCount']}\n")
        txt_output.write(f"{stats['videoCount']}\n")
        txt_output.write(f"{round(months_active,2)}\n")
        txt_output.write(f"{round(subs_per_month,2)}\n")
        txt_output.write(f"{round(subs_per_video,2)}\n")
        txt_output.write(f"{round(subs_per_month_per_video,2)}\n")
        txt_output.write(f"{stats['viewCount']}\n")
        txt_output.write(f"{round(view_per_sub,2)}\n")
        txt_output.write(f"{playlist_count}\n")
        txt_output.write(f"{round(views_per_video,2)}\n")
        txt_output.write(f"{round(views_per_month,2)}\n")
        txt_output.write(f"{round(subs_per_view,6)}\n")
        txt_output.write(f"{round(subs_per_view_alt,6)}\n")
        txt_output.write(f"{round(subs_per_total_view,6)}\n")
        txt_output.write(f"{round(playlists_per_video,6)}\n")
        txt_output.write(f"{round(videos_per_month,2)}\n")
        txt_output.write(f"{round(videos_per_subscriber,6)}\n")
        txt_output.write(f"https://www.youtube.com/channel/{channel_id}\n\n")
        txt_output.write("動画本数が多い上位5再生リスト:\n")
        for i, pl in enumerate(top5_playlists, 1):
            txt_output.write(f"{i}位: {pl['title']}　→ {pl['count']}本\n")

        st.download_button(
            "TXTダウンロード",
            data=txt_output.getvalue().encode("utf-8"),
            file_name="vtuber_stats.txt"
        )

if __name__ == "__main__":
    main()
