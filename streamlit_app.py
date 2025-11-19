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

download_placeholder.download_button(
    "TXTダウンロード",
    data=txt_value.encode("utf-8"),
    file_name="vt_stats.txt",
)

st.success("集計が完了しました。上部のダウンロードボタンから取得してください。")
