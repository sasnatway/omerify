import flet as ft
import json
import os
import urllib.request
import urllib.parse
import threading
import time

DATA_FILE = "user_data.json"
DOWNLOADS_DIR = "downloads"
LOGO_FILE = "logo.png"

if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

DEFAULT_COVER = "https://picsum.photos/300/300"


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data.get("playlists"), dict):
                    data["playlists"] = list(data["playlists"].keys())
                return data
        except Exception:
            pass
    return {
        "profile": None,
        "liked_songs": [],
        "liked_tracks_data": [],
        "playlists": [],
        "playlist_tracks": {},
        "downloaded_tracks": [],
        "following": [],
        "messages": {},
        "last_played_artist": None,
        "saved_volume": 100
    }


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def search_online_tracks(query):
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.deezer.com/search?q={encoded_query}&limit=35"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

        tracks = []
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            for item in data.get("data", []):
                cover = item.get("album", {}).get("cover_medium")
                if not cover or cover == "":
                    cover = DEFAULT_COVER

                tracks.append({
                    "id": str(item["id"]),
                    "title": item["title"],
                    "artist": item['artist']['name'],
                    "album": item["album"]["title"],
                    "cover": cover,
                    "preview": item.get("preview", "")
                })
        return tracks
    except Exception as e:
        print("Arama hatası:", e)
        return []


def download_track_mp3(track, callback):
    file_path = os.path.join(DOWNLOADS_DIR, f"{track['id']}.mp3")
    if os.path.exists(file_path):
        callback(True, file_path)
        return

    try:
        import yt_dlp
        search_query = f"{track['artist']} - {track['title']} Audio"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOADS_DIR, f"{track['id']}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'noplaylist': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch:{search_query}"])

        if os.path.exists(file_path):
            callback(True, file_path)
            return
    except Exception as e:
        print("yt-dlp tam indirme hatası:", e)

    # Yedek plan: Eğer yt-dlp hata verirse Deezer önizlemesini indirip çalmayı garantiler
    try:
        if track.get("preview"):
            urllib.request.urlretrieve(track["preview"], file_path)
            if os.path.exists(file_path):
                callback(True, file_path)
                return
    except Exception:
        pass

    callback(False, None)


def main(page: ft.Page):
    page.title = "Ömerify"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    user_db = load_data()
    if "playlist_tracks" not in user_db:
        user_db["playlist_tracks"] = {}
    if "downloaded_tracks" not in user_db:
        user_db["downloaded_tracks"] = []
    if "following" not in user_db:
        user_db["following"] = []
    if "messages" not in user_db:
        user_db["messages"] = {}
    if "saved_volume" not in user_db:
        user_db["saved_volume"] = 100

    now_playing = {"track": None, "is_playing": False, "seconds": 0, "load_id": 0}

    initial_vol_val = user_db["saved_volume"]
    initial_volume = (initial_vol_val / 100.0) ** 2

    audio_player = ft.Audio(
        src="",
        autoplay=False,
        volume=initial_volume
    )
    page.overlay.append(audio_player)

    player_cover = ft.Image(src=DEFAULT_COVER, width=50, height=50, border_radius=5)
    player_title = ft.Text("Şarkı Seçilmedi", weight=ft.FontWeight.BOLD, overflow=ft.TextOverflow.ELLIPSIS, width=140)
    player_artist = ft.Text("-", size=12, color=ft.Colors.GREY_400, overflow=ft.TextOverflow.ELLIPSIS, width=140)
    play_btn = ft.IconButton(icon=ft.Icons.PLAY_CIRCLE_FILL, icon_size=35, on_click=lambda e: toggle_play(e))

    bar_like_btn = ft.IconButton(icon=ft.Icons.FAVORITE_BORDER, icon_size=20, on_click=lambda e: toggle_current_like())
    bar_add_btn = ft.IconButton(icon=ft.Icons.PLAYLIST_ADD, icon_size=20, tooltip="Çalma Listesine Ekle",
                                on_click=lambda e: open_add_to_playlist_dialog(now_playing["track"]) if now_playing[
                                    "track"] else None)

    time_current = ft.Text("0:00", size=11, color=ft.Colors.GREY_400)
    time_total = ft.Text("Tam Sürüm", size=11, color=ft.Colors.PURPLE_ACCENT)

    progress_slider = ft.Slider(
        min=0, max=300, value=0, expand=True,
        active_color=ft.Colors.PURPLE_ACCENT,
        on_change=lambda e: seek_audio(e.control.value)
    )

    volume_slider = ft.Slider(
        min=0, max=100, value=user_db["saved_volume"], width=100,
        active_color=ft.Colors.PURPLE_ACCENT,
        on_change=lambda e: change_volume(e.control.value)
    )

    def on_file_picked(e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            file_path = e.files[0].path
            if "profile" not in user_db or not user_db["profile"]:
                user_db["profile"] = {}
            user_db["profile"]["photo"] = file_path
            save_data(user_db)
            page.open(ft.SnackBar(ft.Text("Profil fotoğrafı güncellendi!")))
            page.update()
            tabs_content.content = build_profile_view()
            page.update()

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.append(file_picker)

    def timer_loop():
        while True:
            time.sleep(1)
            if now_playing["is_playing"]:
                now_playing["seconds"] += 1
                sec = now_playing["seconds"]
                m = sec // 60
                s = sec % 60
                time_current.value = f"{m}:{s:02d}"
                progress_slider.value = min(sec, 300)
                page.update()

    threading.Thread(target=timer_loop, daemon=True).start()

    def seek_audio(val):
        now_playing["seconds"] = int(val)
        audio_player.seek(int(val * 1000))

    def change_volume(val):
        linear_val = val / 100.0
        audio_player.volume = linear_val * linear_val
        user_db["saved_volume"] = int(val)
        save_data(user_db)
        page.update()

    def toggle_theme(e):
        page.theme_mode = ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        page.update()

    def update_bar_like_icon():
        if now_playing["track"]:
            is_liked = now_playing["track"]["id"] in user_db["liked_songs"]
            bar_like_btn.icon = ft.Icons.FAVORITE if is_liked else ft.Icons.FAVORITE_BORDER
            bar_like_btn.icon_color = ft.Colors.RED if is_liked else None

    def toggle_current_like():
        if now_playing["track"]:
            toggle_like(now_playing["track"])
            update_bar_like_icon()
            page.update()

    def play_song(track):
        try:
            audio_player.pause()
        except Exception:
            pass

        now_playing["load_id"] += 1
        current_load_id = now_playing["load_id"]

        now_playing["track"] = track
        now_playing["is_playing"] = True
        now_playing["seconds"] = 0

        player_title.value = track["title"]
        player_artist.value = track["artist"]
        player_cover.src = track["cover"] if track.get("cover") else DEFAULT_COVER
        play_btn.icon = ft.Icons.PAUSE_CIRCLE_FILLED
        player_bar.visible = True

        update_bar_like_icon()
        user_db["last_played_artist"] = track["artist"]
        save_data(user_db)

        page.open(ft.SnackBar(ft.Text(f"'{track['title']}' hazırlanıyor...")))
        page.update()

        def prepare_and_play():
            def on_ready(success, file_path):
                if current_load_id != now_playing["load_id"]:
                    return
                if success and file_path and os.path.exists(file_path):
                    audio_player.src = file_path
                    audio_player.play()
                    page.open(ft.SnackBar(ft.Text(f"Çalınıyor: {track['title']}")))
                    page.update()
                else:
                    page.open(ft.SnackBar(ft.Text("Şarkı çalınamadı!")))
                    page.update()

            download_track_mp3(track, on_ready)

        threading.Thread(target=prepare_and_play, daemon=True).start()

    def toggle_play(e):
        if now_playing["track"]:
            now_playing["is_playing"] = not now_playing["is_playing"]
            if now_playing["is_playing"]:
                play_btn.icon = ft.Icons.PAUSE_CIRCLE_FILLED
                audio_player.resume()
            else:
                play_btn.icon = ft.Icons.PLAY_CIRCLE_FILL
                audio_player.pause()
            page.update()

    def toggle_like(track):
        track_id = track["id"]
        if track_id in user_db["liked_songs"]:
            user_db["liked_songs"].remove(track_id)
            user_db["liked_tracks_data"] = [t for t in user_db.get("liked_tracks_data", []) if t["id"] != track_id]
        else:
            user_db["liked_songs"].append(track_id)
            if "liked_tracks_data" not in user_db:
                user_db["liked_tracks_data"] = []
            if not any(t["id"] == track_id for t in user_db["liked_tracks_data"]):
                user_db["liked_tracks_data"].append(track)

        save_data(user_db)
        update_bar_like_icon()
        build_library_view()
        page.update()

    def handle_download(track):
        page.open(ft.SnackBar(ft.Text(f"'{track['title']}' tam sürüm indiriliyor...")))
        page.update()

        def on_done(success, file_path):
            if success:
                if not any(t["id"] == track["id"] for t in user_db["downloaded_tracks"]):
                    user_db["downloaded_tracks"].append(track)
                    save_data(user_db)
                page.open(ft.SnackBar(ft.Text(f"'{track['title']}' başarıyla indirildi!")))
            else:
                page.open(ft.SnackBar(ft.Text("İndirme başarısız.")))
            build_library_view()
            page.update()

        threading.Thread(target=download_track_mp3, args=(track, on_done), daemon=True).start()

    def open_add_to_playlist_dialog(track):
        playlists = user_db.get("playlists", [])
        if not playlists:
            page.open(ft.SnackBar(ft.Text("Önce Kitaplık sekmesinden bir çalma listesi oluşturun!")))
            page.update()
            return

        def add_to_pl(pl_name, dlg):
            if pl_name not in user_db["playlist_tracks"]:
                user_db["playlist_tracks"][pl_name] = []

            if not any(t["id"] == track["id"] for t in user_db["playlist_tracks"][pl_name]):
                user_db["playlist_tracks"][pl_name].append(track)
                save_data(user_db)
                page.open(ft.SnackBar(ft.Text(f"'{track['title']}' , '{pl_name}' listesine eklendi!")))
            else:
                page.open(ft.SnackBar(ft.Text("Şarkı zaten bu listede var.")))

            page.close(dlg)
            build_library_view()

        options = []
        dlg = ft.AlertDialog()
        for pl in playlists:
            options.append(
                ft.ListTile(
                    title=ft.Text(pl),
                    leading=ft.Icon(ft.Icons.QUEUE_MUSIC),
                    on_click=lambda e, name=pl, d=dlg: add_to_pl(name, d)
                )
            )

        dlg.title = ft.Text("Çalma Listesine Ekle")
        dlg.content = ft.Column(options, tight=True, width=300)
        page.open(dlg)

    def save_profile_click(e):
        if name_input.value and name_input.value.strip() != "":
            user_db["profile"] = {
                "name": name_input.value.strip(),
                "fav_genre": genre_dropdown.value or "Pop",
                "photo": LOGO_FILE if os.path.exists(LOGO_FILE) else None
            }
            save_data(user_db)
            show_main_app()

    name_input = ft.TextField(label="Adınız Soyadınız", width=300)
    genre_dropdown = ft.Dropdown(
        label="Favori Müzik Türü",
        width=300,
        options=[
            ft.dropdown.Option("Pop"),
            ft.dropdown.Option("Rock"),
            ft.dropdown.Option("Hip-Hop / Rap"),
            ft.dropdown.Option("Elektronik"),
            ft.dropdown.Option("Klasik")
        ]
    )

    logo_display = ft.Image(src=LOGO_FILE, width=90, height=90, border_radius=45,
                            fit=ft.ImageFit.COVER) if os.path.exists(LOGO_FILE) else ft.Icon(name=ft.Icons.HEADSET,
                                                                                             size=80,
                                                                                             color=ft.Colors.PURPLE_ACCENT)

    profile_setup_view = ft.Container(
        content=ft.Column([
            logo_display,
            ft.Text("Ömerify'a Hoş Geldiniz", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Lütfen profilinizi oluşturun (Tek seferlik)", color=ft.Colors.GREY_400),
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            name_input,
            genre_dropdown,
            ft.ElevatedButton("Profili Kaydet ve Başla", on_click=save_profile_click,
                              style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.PURPLE_800))
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.alignment.center,
        expand=True
    )

    player_bar = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Row([player_cover, ft.Column([player_title, player_artist], spacing=0)]),
                ft.Row([play_btn], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([
                    bar_like_btn,
                    bar_add_btn,
                    ft.Icon(ft.Icons.VOLUME_UP, size=18, color=ft.Colors.GREY_400),
                    volume_slider
                ], alignment=ft.MainAxisAlignment.END, spacing=2)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([
                time_current,
                progress_slider,
                time_total
            ], alignment=ft.MainAxisAlignment.CENTER)
        ], spacing=2),
        padding=10,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        visible=False
    )

    home_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def build_home_view():
        home_container.controls.clear()
        last_artist = user_db.get("last_played_artist")
        search_query = last_artist if last_artist else "Pop Hits"
        title_text = f"'{last_artist}' İle Alakalı Öneriler" if last_artist else "Ömerify İçin Önerilenler"

        home_container.controls.append(ft.Text(title_text, size=20, weight=ft.FontWeight.BOLD))
        loading_tile = ft.ListTile(title=ft.Text("Öneriler yükleniyor...", color=ft.Colors.PURPLE_ACCENT))
        home_container.controls.append(loading_tile)
        page.update()

        def fetch_recs():
            recs = search_online_tracks(search_query)
            if loading_tile in home_container.controls:
                home_container.controls.remove(loading_tile)

            for track in recs:
                is_liked = track["id"] in user_db["liked_songs"]
                c_src = track["cover"] if track.get("cover") else DEFAULT_COVER
                home_container.controls.append(
                    ft.ListTile(
                        leading=ft.Image(src=c_src, width=40, height=40, border_radius=5),
                        title=ft.Text(track["title"]),
                        subtitle=ft.Text(f"{track['artist']} • {track['album']}"),
                        trailing=ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.DOWNLOAD,
                                tooltip="İndir",
                                on_click=lambda e, t=track: handle_download(t)
                            ),
                            ft.IconButton(
                                icon=ft.Icons.PLAYLIST_ADD,
                                tooltip="Çalma Listesine Ekle",
                                on_click=lambda e, t=track: open_add_to_playlist_dialog(t)
                            ),
                            ft.IconButton(
                                icon=ft.Icons.FAVORITE if is_liked else ft.Icons.FAVORITE_BORDER,
                                icon_color=ft.Colors.RED if is_liked else None,
                                on_click=lambda e, t=track: toggle_like(t)
                            )
                        ], tight=True),
                        on_click=lambda e, t=track: play_song(t)
                    )
                )
            page.update()

        threading.Thread(target=fetch_recs, daemon=True).start()
        return ft.Container(content=home_container, padding=15, expand=True)

    search_results = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def on_search_submit(e):
        query = e.control.value.lower()
        search_results.controls.clear()
        if query:
            search_results.controls.append(
                ft.ListTile(title=ft.Text("Şarkılar aranıyor...", color=ft.Colors.PURPLE_ACCENT)))
            page.update()

            def fetch_results():
                tracks = search_online_tracks(query)
                search_results.controls.clear()
                for track in tracks:
                    is_liked = track["id"] in user_db["liked_songs"]
                    c_src = track["cover"] if track.get("cover") else DEFAULT_COVER
                    search_results.controls.append(
                        ft.ListTile(
                            leading=ft.Image(src=c_src, width=40, height=40, border_radius=5),
                            title=ft.Text(track["title"]),
                            subtitle=ft.Text(f"{track['artist']} • {track['album']}"),
                            trailing=ft.Row([
                                ft.IconButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    tooltip="İndir",
                                    on_click=lambda e, t=track: handle_download(t)
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.PLAYLIST_ADD,
                                    tooltip="Çalma Listesine Ekle",
                                    on_click=lambda e, t=track: open_add_to_playlist_dialog(t)
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.FAVORITE if is_liked else ft.Icons.FAVORITE_BORDER,
                                    icon_color=ft.Colors.RED if is_liked else None,
                                    on_click=lambda e, t=track: toggle_like(t)
                                )
                            ], tight=True),
                            on_click=lambda e, t=track: play_song(t)
                        )
                    )
                page.update()

            threading.Thread(target=fetch_results, daemon=True).start()

    search_view = ft.Column([
        ft.Container(
            padding=15,
            content=ft.TextField(
                hint_text="Ömerify'da milyonlarca şarkı arasında ara (Enter'a basın)...",
                on_submit=on_search_submit,
                prefix_icon=ft.Icons.SEARCH
            )
        ),
        search_results
    ], expand=True)

    library_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    playlist_input = ft.TextField(hint_text="Çalma Listesi Adı", width=200)

    def add_playlist(e):
        pl_name = playlist_input.value.strip()
        if pl_name and pl_name not in user_db["playlists"]:
            user_db["playlists"].append(pl_name)
            user_db["playlist_tracks"][pl_name] = []
            save_data(user_db)
            playlist_input.value = ""
            build_library_view()
            page.update()

    def show_playlist_details(pl_name):
        tracks = user_db.get("playlist_tracks", {}).get(pl_name, [])
        dlg = ft.AlertDialog()

        def close_detail(e):
            page.close(dlg)

        track_controls = []
        if not tracks:
            track_controls.append(ft.Text("Bu çalma listesinde henüz şarkı yok.", color=ft.Colors.GREY_400))
        else:
            for track in tracks:
                c_src = track["cover"] if track.get("cover") else DEFAULT_COVER
                track_controls.append(
                    ft.ListTile(
                        leading=ft.Image(src=c_src, width=40, height=40, border_radius=5),
                        title=ft.Text(track["title"]),
                        subtitle=ft.Text(track["artist"]),
                        on_click=lambda e, t=track: play_song(t)
                    )
                )

        dlg.title = ft.Text(f"🎵 {pl_name}")
        dlg.content = ft.Column(track_controls, tight=True, width=350, height=300, scroll=ft.ScrollMode.AUTO)
        dlg.actions = [ft.TextButton("Kapat", on_click=close_detail)]
        page.open(dlg)

    def build_library_view():
        library_container.controls.clear()

        liked_tracks = user_db.get("liked_tracks_data", [])
        library_container.controls.append(
            ft.ListTile(
                leading=ft.Icon(ft.Icons.FAVORITE, color=ft.Colors.RED, size=32),
                title=ft.Text("Beğenilen Şarkılar", weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(f"{len(liked_tracks)} şarkı"),
            )
        )
        for track in liked_tracks:
            c_src = track["cover"] if track.get("cover") else DEFAULT_COVER
            library_container.controls.append(
                ft.ListTile(
                    leading=ft.Image(src=c_src, width=40, height=40, border_radius=5),
                    title=ft.Text(track["title"]),
                    subtitle=ft.Text(track["artist"]),
                    trailing=ft.IconButton(
                        icon=ft.Icons.FAVORITE,
                        icon_color=ft.Colors.RED,
                        on_click=lambda e, t=track: toggle_like(t)
                    ),
                    on_click=lambda e, t=track: play_song(t)
                )
            )

        library_container.controls.append(ft.Divider())

        downloaded = user_db.get("downloaded_tracks", [])
        library_container.controls.append(
            ft.ListTile(
                leading=ft.Icon(ft.Icons.DOWNLOAD_DONE, color=ft.Colors.PURPLE_ACCENT, size=32),
                title=ft.Text("İndirilen Şarkılar (Çevrimdışı)", weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(f"{len(downloaded)} şarkı yerel depolamada"),
            )
        )
        for track in downloaded:
            c_src = track["cover"] if track.get("cover") else DEFAULT_COVER
            library_container.controls.append(
                ft.ListTile(
                    leading=ft.Image(src=c_src, width=40, height=40, border_radius=5),
                    title=ft.Text(track["title"]),
                    subtitle=ft.Text(f"{track['artist']} • Çevrimdışı Hazır"),
                    on_click=lambda e, t=track: play_song(t)
                )
            )

        library_container.controls.append(ft.Divider())
        library_container.controls.append(ft.Text("Çalma Listeleriniz", size=18, weight=ft.FontWeight.BOLD))

        library_container.controls.append(
            ft.Row([playlist_input, ft.ElevatedButton("Oluştur", on_click=add_playlist)])
        )

        for pl_name in user_db.get("playlists", []):
            count = len(user_db.get("playlist_tracks", {}).get(pl_name, []))
            library_container.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.QUEUE_MUSIC, color=ft.Colors.PURPLE_ACCENT),
                    title=ft.Text(pl_name, weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(f"{count} şarkı"),
                    on_click=lambda e, name=pl_name: show_playlist_details(name)
                )
            )

    social_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def open_chat_dialog(friend_name):
        if friend_name not in user_db["messages"]:
            user_db["messages"][friend_name] = []

        chat_messages_column = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def refresh_chat_ui():
            chat_messages_column.controls.clear()
            for msg in user_db["messages"][friend_name]:
                is_me = msg["sender"] == "Ben"
                chat_messages_column.controls.append(
                    ft.Row([
                        ft.Container(
                            content=ft.Text(msg["text"], color=ft.Colors.WHITE),
                            bgcolor=ft.Colors.PURPLE_800 if is_me else ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            padding=10, border_radius=8
                        )
                    ], alignment=ft.MainAxisAlignment.END if is_me else ft.MainAxisAlignment.START)
                )
            page.update()

        msg_input = ft.TextField(hint_text="Mesaj yaz...", expand=True)

        def send_msg(e):
            if msg_input.value.strip():
                user_db["messages"][friend_name].append({"sender": "Ben", "text": msg_input.value.strip()})
                save_data(user_db)
                msg_input.value = ""
                refresh_chat_ui()

        refresh_chat_ui()

        dlg = ft.AlertDialog()
        dlg.title = ft.Text(f"💬 Sohbet: {friend_name}")
        dlg.content = ft.Container(
            content=ft.Column([
                chat_messages_column,
                ft.Row([msg_input, ft.IconButton(icon=ft.Icons.SEND, on_click=send_msg)])
            ], height=300, width=350),
        )
        dlg.actions = [ft.TextButton("Kapat", on_click=lambda _: page.close(dlg))]
        page.open(dlg)

    MOCK_USERS = [
        {"name": "Ahmet Yılmaz", "genre": "Rock"},
        {"name": "Zeynep Demir", "genre": "Pop"},
        {"name": "Can Çelik", "genre": "Hip-Hop / Rap"},
        {"name": "Elif Kaya", "genre": "Elektronik"}
    ]

    def build_social_view():
        social_container.controls.clear()
        social_container.controls.append(ft.Text("Ömerify Sosyal Ağ", size=20, weight=ft.FontWeight.BOLD))

        following_list = user_db.get("following", [])

        social_container.controls.append(ft.Text("Takip Ettiklerin:", size=16, weight=ft.FontWeight.W_500))
        if not following_list:
            social_container.controls.append(ft.Text("Henüz kimseyi takip etmiyorsun.", color=ft.Colors.GREY_400))
        else:
            for friend in following_list:
                social_container.controls.append(
                    ft.ListTile(
                        leading=ft.CircleAvatar(content=ft.Text(friend[0].upper())),
                        title=ft.Text(friend),
                        subtitle=ft.Text("Çevrimiçi • Ömerify Dinliyor"),
                        trailing=ft.Row([
                            ft.IconButton(icon=ft.Icons.MESSAGE, tooltip="Mesaj Gönder",
                                          on_click=lambda e, f=friend: open_chat_dialog(f)),
                            ft.IconButton(icon=ft.Icons.PERSON_REMOVE, tooltip="Takipten Çık",
                                          on_click=lambda e, f=friend: unfollow_friend(f))
                        ], tight=True)
                    )
                )

        social_container.controls.append(ft.Divider())
        social_container.controls.append(ft.Text("Yeni Kullanıcılar Keşfet", size=16, weight=ft.FontWeight.W_500))

        def follow_friend(name):
            if name not in user_db["following"]:
                user_db["following"].append(name)
                save_data(user_db)
                build_social_view()
                page.update()

        def unfollow_friend(name):
            if name in user_db["following"]:
                user_db["following"].remove(name)
                save_data(user_db)
                build_social_view()
                page.update()

        for u in MOCK_USERS:
            if u["name"] != user_db.get("profile", {}).get("name"):
                is_following = u["name"] in following_list
                social_container.controls.append(
                    ft.ListTile(
                        leading=ft.CircleAvatar(content=ft.Text(u["name"][0])),
                        title=ft.Text(u["name"]),
                        subtitle=ft.Text(f"Favori Tür: {u['genre']}"),
                        trailing=ft.ElevatedButton(
                            "Takiptesin" if is_following else "Takip Et",
                            bgcolor=ft.Colors.GREY_800 if is_following else ft.Colors.PURPLE_ACCENT,
                            color=ft.Colors.WHITE,
                            on_click=lambda e, name=u["name"]: unfollow_friend(name) if name in user_db[
                                "following"] else follow_friend(name)
                        )
                    )
                )

        return ft.Container(content=social_container, padding=15, expand=True)

    def build_profile_view():
        prof = user_db.get("profile", {})
        photo_path = prof.get("photo")

        if photo_path and os.path.exists(photo_path):
            avatar_widget = ft.Image(src=photo_path, width=90, height=90, border_radius=45, fit=ft.ImageFit.COVER)
        elif os.path.exists(LOGO_FILE):
            avatar_widget = ft.Image(src=LOGO_FILE, width=90, height=90, border_radius=45, fit=ft.ImageFit.COVER)
        else:
            first_letter = prof.get("name", "U")[0].upper() if prof else "U"
            avatar_widget = ft.CircleAvatar(content=ft.Text(first_letter, size=28), radius=45)

        edit_name_input = ft.TextField(value=prof.get("name", ""), label="İsim Soyisim", width=260)
        edit_genre_dropdown = ft.Dropdown(
            label="Favori Tür",
            width=260,
            value=prof.get("fav_genre", "Pop"),
            options=[
                ft.dropdown.Option("Pop"),
                ft.dropdown.Option("Rock"),
                ft.dropdown.Option("Hip-Hop / Rap"),
                ft.dropdown.Option("Elektronik"),
                ft.dropdown.Option("Klasik")
            ]
        )

        def update_profile_info(e):
            if edit_name_input.value and edit_name_input.value.strip() != "":
                user_db["profile"]["name"] = edit_name_input.value.strip()
                user_db["profile"]["fav_genre"] = edit_genre_dropdown.value
                save_data(user_db)
                page.open(ft.SnackBar(ft.Text("Ömerify profilin güncellendi!")))
                tabs_content.content = build_profile_view()
                page.update()

        return ft.Container(
            content=ft.Column([
                ft.Row([avatar_widget], alignment=ft.MainAxisAlignment.CENTER),
                ft.ElevatedButton(
                    "Fotoğraf Değiştir",
                    icon=ft.Icons.IMAGE,
                    on_click=lambda _: file_picker.pick_files(allow_multiple=False,
                                                              file_type=ft.FilePickerFileType.IMAGE)
                ),
                ft.Divider(height=15),
                edit_name_input,
                edit_genre_dropdown,
                ft.ElevatedButton("Kaydet", icon=ft.Icons.SAVE, on_click=update_profile_info,
                                  style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.PURPLE_800)),
                ft.Divider(height=15),
                ft.ListTile(leading=ft.Icon(ft.Icons.MUSIC_NOTE), title=ft.Text("Kitaplıktaki Şarkılar"),
                            subtitle=ft.Text(f"{len(user_db.get('liked_songs', []))} Şarkı")),
                ft.ListTile(leading=ft.Icon(ft.Icons.PEOPLE), title=ft.Text("Takip Edilen Arkadaşlar"),
                            subtitle=ft.Text(f"{len(user_db.get('following', []))} Kişi"))
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO),
            padding=20,
            expand=True
        )

    settings_view = ft.Container(
        content=ft.Column([
            ft.Text("Ömerify Ayarları", size=22, weight=ft.FontWeight.BOLD),
            ft.Switch(label="Koyu Tema", value=True, on_change=toggle_theme),
            ft.Divider(),
            ft.Dropdown(
                label="Akış Kalitesi",
                value="Yüksek (320 kbps)",
                options=[ft.dropdown.Option("Normal (160 kbps)"), ft.dropdown.Option("Yüksek (320 kbps)")]
            )
        ]),
        padding=20,
        expand=True
    )

    tabs_content = ft.Container(expand=True)

    def on_nav_change(e):
        idx = e.control.selected_index
        if idx == 0:
            tabs_content.content = build_home_view()
        elif idx == 1:
            tabs_content.content = search_view
        elif idx == 2:
            build_library_view()
            tabs_content.content = library_container
        elif idx == 3:
            tabs_content.content = build_social_view()
        elif idx == 4:
            tabs_content.content = build_profile_view()
        elif idx == 5:
            tabs_content.content = settings_view
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.EXPLORE, label="Önerilenler"),
            ft.NavigationBarDestination(icon=ft.Icons.SEARCH, label="Ara"),
            ft.NavigationBarDestination(icon=ft.Icons.LIBRARY_MUSIC, label="Kitaplık"),
            ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Sosyal"),
            ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Profil"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Ayarlar"),
        ]
    )

    def show_main_app():
        page.controls.clear()
        tabs_content.content = build_home_view()
        page.add(
            ft.Column([
                tabs_content,
                player_bar,
                nav_bar
            ], expand=True)
        )
        page.update()

    if user_db.get("profile"):
        show_main_app()
    else:
        page.add(profile_setup_view)


if __name__ == "__main__":
    ft.app(target=main)