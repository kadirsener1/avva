def save_to_m3u(channels, filename="data/playlist.m3u"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for name, url in channels:
            f.write(f"#EXTINF:-1,{name}\n")
            f.write(f"{url}\n")
