import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime
import io

API_KEY = "AIzaSyCJilGGK0Xj4tRojTkSZdmhHBbFNjHZbD4"
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

def get_channel_id_from_url(url):
    if "channel/" in url:
        return url.split("channel/")[1].split("/")[0]
    st.error("channel/形式のURLのみ対応：https://www.youtube.com/channel/xxxxxxxxxx")
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
    st.title("VTuberデータ自動集計アプリ（クォータ節約版）")
    url = st.text_input("YouTubeチャンネルURLを入力してください（channel/形式）")
    if st.button("集計"):
        if not url:
            st.warning("URLを入力してください")
            return
        channel_id = get_channel_id_from_url(url)
        if not channel_id:
            return
        stats = get_channel_stats(channel_id)
        published_at = stats["publishedAt"]
        if not published_at:
            st.error("チャンネル作成日の取得に失敗しました（publishedAtが空です）。")
            return
        try:
            oldest_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            st.error(f"日付のフォーマットが不正です: {published_at}")
            return
        months_active = (datetime.utcnow() - oldest_date).days / 30
        subs_per_month = stats["subscriberCount"] / months_active if months_active > 0 else 0
        subs_per_video = stats["subscriberCount"] / stats["videoCount"] if stats["videoCount"] else 0
        view_per_sub = stats["viewCount"] / stats["subscriberCount"] if stats["subscriberCount"] else 0

        playlists = get_playlists_with_counts(channel_id)
        playlist_count = len(playlists)
        playlists_sorted = sorted(playlists, key=lambda x: x["count"], reverse=True)
        top5_playlists = playlists_sorted[:5]

        st.write("### 集計結果")
        st.write(f"**チャンネルID**: {channel_id}")
        st.write(f"**チャンネル名**: {stats['title']}")
        st.write(f"**登録者数**: {stats['subscriberCount']}")
        st.write(f"**動画本数**: {stats['videoCount']}")
        st.write(f"**活動開始日**: {oldest_date.strftime('%Y-%m-%d')}")
        st.write(f"**活動月数**: {round(months_active,2)}")
        st.write(f"**登録者数/活動月**: {round(subs_per_month,2)}")
        st.write(f"**登録者数/動画**: {round(subs_per_video,2)}")
        st.write(f"**総再生回数**: {stats['viewCount']}")
        st.write(f"**総再生回数/登録者数**: {round(view_per_sub,2)}")
        st.write(f"**再生リスト数**: {playlist_count}")
        st.write(f"**URL**: {url}")

        st.write("### 動画本数が多い上位5再生リスト")
        for i, pl in enumerate(top5_playlists, 1):
            st.write(f"{i}位: {pl['title']}　→ {pl['count']}本")

        # テキスト出力
        txt_output = io.StringIO()
        txt_output.write(f"チャンネルID: {channel_id}\n")
        txt_output.write(f"チャンネル名: {stats['title']}\n")
        txt_output.write(f"登録者数: {stats['subscriberCount']}\n")
        txt_output.write(f"動画本数: {stats['videoCount']}\n")
        txt_output.write(f"活動開始日: {oldest_date.strftime('%Y-%m-%d')}\n")
        txt_output.write(f"活動月数: {round(months_active,2)}\n")
        txt_output.write(f"登録者数/活動月: {round(subs_per_month,2)}\n")
        txt_output.write(f"登録者数/動画: {round(subs_per_video,2)}\n")
        txt_output.write(f"総再生回数: {stats['viewCount']}\n")
        txt_output.write(f"総再生回数/登録者数: {round(view_per_sub,2)}\n")
        txt_output.write(f"再生リスト数: {playlist_count}\n")
        txt_output.write(f"URL: {url}\n\n")
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
