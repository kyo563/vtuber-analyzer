import streamlit as st
from googleapiclient.discovery import build
import openpyxl
from datetime import datetime
import io

API_KEY = "AIzaSyCJilGGK0Xj4tRojTkSZdmhHBbFNjHZbD4"
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

def get_channel_id_from_url(url):
    if "channel/" in url:
        return url.split("channel/")[1].split("/")[0]
    st.error("channel/形式のURLのみ対応（例：https://www.youtube.com/channel/xxxxxxxxxx）")
    return None

def get_channel_stats(channel_id):
    request = YOUTUBE.channels().list(part="snippet,statistics", id=channel_id)
    response = request.execute()
    item = response["items"][0]
    stats = item["statistics"]
    snippet = item["snippet"]
    return {
        "title": snippet["title"],
        "subscriberCount": int(stats.get("subscriberCount", 0)),
        "videoCount": int(stats.get("videoCount", 0)),
        "viewCount": int(stats.get("viewCount", 0))
    }

def get_oldest_video_date(channel_id):
    videos = []
    next_page_token = None
    while True:
        request = YOUTUBE.search().list(
            channelId=channel_id,
            part="snippet",
            type="video",
            order="date",
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        videos += response["items"]
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    oldest_video = videos[-1]
    return oldest_video["snippet"]["publishedAt"]

def get_playlist_count(channel_id):
    playlists = []
    next_page_token = None
    while True:
        request = YOUTUBE.playlists().list(
            part="id",
            channelId=channel_id,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        playlists += response.get("items", [])
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return len(playlists)

def main():
    st.title("VT自動集計アプリ")
    url = st.text_input("YTチャンネルURLを入力してください（https://www.youtube.com/channel/）")
    if st.button("集計"):
        if not url:
            st.warning("URLを入力してください")
            return
        channel_id = get_channel_id_from_url(url)
        if not channel_id:
            return
        stats = get_channel_stats(channel_id)
        oldest_date_str = get_oldest_video_date(channel_id)
        oldest_date = datetime.strptime(oldest_date_str, "%Y-%m-%dT%H:%M:%SZ")
        months_active = (datetime.utcnow() - oldest_date).days / 30
        subs_per_month = stats["subscriberCount"] / months_active if months_active > 0 else 0
        subs_per_video = stats["subscriberCount"] / stats["videoCount"] if stats["videoCount"] else 0

        # 新規追加項目
        view_count = stats["viewCount"]
        playlist_count = get_playlist_count(channel_id)
        view_per_sub = view_count / stats["subscriberCount"] if stats["subscriberCount"] > 0 else 0

        st.write("### 集計結果")
        st.write(f"**チャンネル名**: {stats['title']}")
        st.write(f"**登録者数**: {stats['subscriberCount']}")
        st.write(f"**動画本数**: {stats['videoCount']}")
        st.write(f"**最古動画公開日**: {oldest_date.strftime('%Y-%m-%d')}")
        st.write(f"**活動月数**: {round(months_active,2)}")
        st.write(f"**登録者数/活動月**: {round(subs_per_month,2)}")
        st.write(f"**登録者数/動画**: {round(subs_per_video,2)}")
        st.write(f"**総再生回数**: {view_count}")
        st.write(f"**総再生回数/登録者数**: {round(view_per_sub,2)}")
        st.write(f"**総再生リスト数**: {playlist_count}")

        # Excel作成
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([
            "チャンネル名", "URL", "登録者数", "動画数", "活動開始日", "活動月数", "Subs/月",
            "Subs/動画", "総再生回数", "再生/登録者", "再生リスト数"
        ])
        ws.append([
            stats["title"], url, stats["subscriberCount"], stats["videoCount"],
            oldest_date.strftime("%Y-%m-%d"), round(months_active, 2),
            round(subs_per_month, 2), round(subs_per_video, 2),
            view_count, round(view_per_sub,2), playlist_count
        ])
        excel_bytes = io.BytesIO()
        wb.save(excel_bytes)
        st.download_button("Excelダウンロード", data=excel_bytes.getvalue(), file_name="vtuber_stats.xlsx")

if __name__ == "__main__":
    main()
