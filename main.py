import asyncio
import base64
import time
import subprocess
import os
import math
import datetime
import config

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified
from oppa import OppaDrama


# --- Konfigurasi untuk BOT ---
API_ID = config.API_ID  # Ganti dengan api_id Anda
API_HASH = config.API_HASH  # Ganti dengan api_hash Anda
BOT_TOKEN = "8019398076:AAEyP2EC7veWvREcP_vRlOKDmV_lPVbzYuE" # Ganti dengan Token Bot Anda

# Inisialisasi sebagai Bot Account
app = Client("my_public_bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
oppa = OppaDrama()

user_session_data = {}

# --- Fungsi Helper (dengan pengecekan 50MB) ---
async def upload_progress(current, total, p_args):
    # ... (fungsi ini tidak berubah)
    client, message, last_update = p_args["client"], p_args["message"], p_args["last_update"]
    now = time.time()
    if now - last_update > 2.0:
        p_args["last_update"] = now
        percentage = current * 100 / total
        speed = current / (now - p_args["start_time"])
        speed_str = f"{speed / 1024:.2f} KB/s" if speed < 1024*1024 else f"{speed / (1024*1024):.2f} MB/s"
        try:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=message.id,
                text=f"⏳ Mengunggah...\n`[{'=' * int(percentage / 5):20}]` {percentage:.1f}% | {speed_str}")
        except: pass

    await asyncio.sleep(5)

# === GANTI FUNGSI INI ===
async def download_progress_callback(client, message, finished, total, downloaded_bytes, start_time):
    """Fungsi yang akan dipanggil oleh download_filelions untuk update status."""
    now = time.time()
    last_edit_time = getattr(download_progress_callback, 'last_edit_time', 0)

    if now - last_edit_time > 2.0:
        setattr(download_progress_callback, 'last_edit_time', now)
        
        if total == 0: return # Hindari pembagian dengan nol jika total segmen belum diketahui

        percentage = finished * 100 / total
        elapsed = now - start_time
        speed = (downloaded_bytes / (1024*1024)) / elapsed if elapsed > 0 else 0
        
        # --- BLOK BARU: Perhitungan ETA ---
        eta_str = "..." # Default string saat ETA belum bisa dihitung
        if speed > 0 and finished > 0:
            # 1. Hitung rata-rata ukuran per segmen
            avg_segment_size = downloaded_bytes / finished
            # 2. Estimasi total ukuran file
            estimated_total_size = avg_segment_size * total
            # 3. Hitung sisa data yang perlu diunduh
            remaining_bytes = max(0, estimated_total_size - downloaded_bytes)
            # 4. Hitung estimasi waktu sisa dalam detik
            speed_in_bytes_per_sec = speed * 1024 * 1024
            if speed_in_bytes_per_sec > 0:
                eta_seconds = remaining_bytes / speed_in_bytes_per_sec
                # 5. Format menjadi jam:menit:detik
                eta_str = str(datetime.timedelta(seconds=int(eta_seconds)))
        # --- AKHIR BLOK BARU ---
        
        try:
            # Tambahkan ETA ke dalam string output
            await client.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.id,
                text=(
                    f"⏳ (1/3) Mengunduh...\n"
                    f"`[{'=' * int(percentage / 5):20}]`\n"
                    f"{percentage:.1f}% | {speed:.2f} MB/s | ETA: {eta_str}"
                )
            )
        except (MessageNotModified, FloodWait):
            pass
        except Exception as e:
            print(f"Error di download_progress_callback: {e}")
            
        await asyncio.sleep(5)

async def process_and_send_video(client, chat_id, message_id, m3u8_url):
    # ... (fungsi ini tidak berubah)
    temp_output_path = f"out_{int(time.time())}.mp4"
    try:
        loading_message = await client.get_messages(chat_id, message_id)
        dl_progress = lambda f, t, b, st: asyncio.create_task(
            download_progress_callback(client, loading_message, f, t, b, st)
        )
        ffmpeg_cmd = ['ffmpeg', '-y', '-i', 'pipe:0', '-c', 'copy', '-movflags', '+faststart', temp_output_path]
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        download_generator = await asyncio.to_thread(
            oppa.download_filelions, m3u8_url, max_workers=4, progress_callback=dl_progress)
        for video_chunk in download_generator:
            try:
                process.stdin.write(video_chunk)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError): break
        if not process.stdin.is_closing(): process.stdin.close()
        stdout, stderr = await process.communicate()
        if process.returncode != 0: raise subprocess.CalledProcessError(process.returncode, ffmpeg_cmd, stderr=stderr.decode())
        await client.edit_message_text(text="⏳ (2/3) Mempersiapkan unggahan...", chat_id=chat_id, message_id=message_id)

        status_message = await client.get_messages(chat_id, message_id)
        p_args = {"client": client, "message": status_message, "last_update": 0, "start_time": time.time()}
        await client.send_video(
            chat_id, video=temp_output_path, caption="✅ Selesai!",
            supports_streaming=True, progress=upload_progress, progress_args=(p_args,))
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        error_text = f"❌ Terjadi kesalahan:\n`{str(e)[:300]}`"
        try: await client.edit_message_text(text=error_text, chat_id=chat_id, message_id=message_id)
        except: await client.send_message(chat_id, error_text)
    finally:
        if os.path.exists(temp_output_path): os.remove(temp_output_path)


def get_link_type(url):
    try: return f"{url.strip().rstrip('/').split('-')[-1].capitalize()}"
    except: return "Download"

# --- Handlers Pyrogram untuk Bot Publik ---

@app.on_message(filters.command("search"))
async def search_handler(client, message):
    if len(message.command) < 2: return await message.reply("Gunakan: `/search <judul>`")
    query = message.text.split(maxsplit=1)[1]
    
    status_msg = await message.reply(f"🔎 Mencari '{query}'...")
    
    search_obj = await asyncio.to_thread(oppa.search, query)
    json_data = search_obj.json()
    all_items = json_data.get("series",[])[0].get("all", [])

    if not all_items: return await status_msg.edit("Maaf, hasil tidak ditemukan.")
    
    # Gunakan ID pengguna sebagai kunci sesi
    user_id = message.from_user.id
    user_session_data[user_id] = {'search_results': all_items}
    
    buttons = [[InlineKeyboardButton(item.get('post_title'), callback_data=f"detail_{item.get('ID')}")] for item in all_items]
    markup = InlineKeyboardMarkup(buttons)
    await status_msg.edit(f"Hasil pencarian untuk '{query}':", reply_markup=markup)

@app.on_callback_query()
async def callback_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Ambil sesi berdasarkan ID pengguna yang menekan tombol
    session = user_session_data.get(user_id)
    if not session:
        return await callback_query.answer("Sesi Anda sudah berakhir. Silakan lakukan pencarian baru dengan /search.", show_alert=True)

    # --- Logika Navigasi Tombol ---
    if data == "back_to_search":
        buttons = [[InlineKeyboardButton(item.get('post_title'), callback_data=f"detail_{item.get('ID')}")] for item in session.get('search_results', [])]
        markup = InlineKeyboardMarkup(buttons)
        await callback_query.message.edit("Hasil pencarian:", reply_markup=markup)

    elif data.startswith("detail_"):
        item_id = int(data.split('_')[1])
        selected_item = next((i for i in session['search_results'] if i.get('ID') == item_id), None)
        if not selected_item: return await callback_query.answer("Item tidak ditemukan.", show_alert=True)

        details_obj = await asyncio.to_thread(oppa.post_details, selected_item.get('post_link'))
        json_data = details_obj.json()

        session.update({'current_movie_id': item_id, 'current_movie_links': json_data.get('movie_links', [])})
        
        detail_text = f"🎬 <b>{json_data.get('title')}</b>\n\n<i>{json_data.get('synopsis')}</i>"
        buttons = [[InlineKeyboardButton(f"⬇️ {get_link_type(link)}", callback_data=f"getlinks_{i}")] for i, link in enumerate(session['current_movie_links'])]
        buttons.append([InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_search")])
        markup = InlineKeyboardMarkup(buttons)
        await callback_query.message.edit(detail_text, reply_markup=markup)

    elif data.startswith("getlinks_"):
        link_index = int(data.split('_')[1]); session['current_link_index'] = link_index
        target_url = session['current_movie_links'][link_index]
        mv_details_obj = await asyncio.to_thread(oppa.movie_details, target_url)
        json_data = mv_details_obj.json()

        buttons = []
        for server in json_data.get('streaming_servers', []):
            if server.get('server','').lower() == 'filelions':
                encoded_url = base64.b64encode(server.get('iframe_src','').encode()).decode()
                buttons.append(InlineKeyboardButton(f"▶️ {server.get('server')}", callback_data=f"playlist_fl_{encoded_url}"))
            else: buttons.append(InlineKeyboardButton(f"📺 {server.get('server')}", url=server.get('iframe_src')))
        markup = InlineKeyboardMarkup([buttons, [InlineKeyboardButton("⬅️ Kembali", callback_data=f"detail_{session['current_movie_id']}")]])
        await callback_query.message.edit(f"<b>Pilih server untuk '{json_data.get('title')}':</b>", reply_markup=markup)

    elif data.startswith("playlist_fl_"):
        encoded_url = data.split('_', 2)[-1]
        target_url = base64.b64decode(encoded_url).decode()
        m3u8_data = await asyncio.to_thread(oppa.playlist_filelions, target_url)
        json_data = m3u8_data.json()

        session['m3u8_list'] = json_data
        buttons = [InlineKeyboardButton(f"▶️ {item.get('resolution')}", callback_data=f"dl_m3u8_{i}") for i, item in enumerate(json_data)]
        markup = InlineKeyboardMarkup([buttons, [InlineKeyboardButton("⬅️ Kembali", callback_data=f"getlinks_{session['current_link_index']}")]])
        await callback_query.message.edit("<b>Pilih resolusi untuk diunduh:</b>", reply_markup=markup)

    elif data.startswith("dl_m3u8_"): 
        chat_id = callback_query.message.chat.id
        await callback_query.message.delete()
        loading_msg = await client.send_message(chat_id, "⏳ Mempersiapkan unduhan...")
        try:
            m3u8_index = int(data.split('_')[-1])
            m3u8_url = session['m3u8_list'][m3u8_index]['url']
        except (KeyError, IndexError, ValueError):
            return await loading_msg.edit("❌ Sesi tidak valid. Coba lagi.")
        asyncio.create_task(process_and_send_video(client, chat_id, loading_msg.id, m3u8_url))

    await callback_query.answer()

def monitor(environ, start_response): 
    """Simplest possible application object"""
    data = b'Hello, World!\n'
    status = '200 OK'
    response_headers = [
        ('Content-type', 'text/plain'),
        ('Content-Length', str(len(data)))
    ]
    start_response(status, response_headers)
    return iter([data])

if __name__ == "__main__":
    print("Bot publik sedang berjalan...")
    app.run()
