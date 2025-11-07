import datetime
import json
import base64
import time
import threading

import requests
import m3u8

from filelions import FileLions
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup

SYNC_BYTE = 0x47

class Response: 
    def __init__(self, data: dict | bytes): 
        self.data = data
        if isinstance(data, (dict, list)): 
            self.data = self.to_bytes(data)
    
    def to_bytes(self, data: dict): 
        return json.dumps(data).encode()

    def __str__(self): 
        json_data = self.json()
        if json_data: 
            return json.dumps(json_data, indent=2)
        text_data = self.text()
        if text_data: 
            return text_data 
        
        return self.content()

    def text(self): 
        try: 
            text_data = self.data.decode()
            return text_data
        except: 
            return None
    
    def json(self): 
        try: 
            decoded_data = self.data.decode()
            json_data = json.loads(decoded_data)
            return json_data
        except: 
            return None
    
    def content(self): 
        return self.data
        
class Request: 
    @staticmethod
    def get(url: str, *args, **kwargs) -> Response: 
        res = requests.get(url, *args, **kwargs)
        res.raise_for_status()

        return Response(res.content)
    
    @staticmethod
    def post(url: str, *args, **kwargs) -> Response: 
        res = requests.post(url, *args, **kwargs)
        res.raise_for_status()

        return Response(res.content)

class OppaDrama: 
    BASE_URL = base64.b64decode("aHR0cDovLzQ1LjExLjU3LjI0Mw==").decode()
    ADMIN_AJAX_URL = BASE_URL + "/wp-admin/admin-ajax.php"

    def __init__(self):
        pass

    def search(self, q: str): 
        url = self.ADMIN_AJAX_URL
        data = {
            "action": "ts_ac_do_search",
            "ts_ac_query": q
        }

        res = Request.post(url, data=data)
        return res

    def post_details(self, url: str): 
        res = Request.get(url)
        soup = BeautifulSoup(res.text(), "html.parser")

        data = {}

        # Judul
        title_tag = soup.find("h1", class_="entry-title")
        data["title"] = title_tag.get_text(strip=True) if title_tag else None

        # Gambar utama
        img_tag = soup.find("img", class_="ts-post-image")
        data["poster"] = img_tag["src"] if img_tag else None

        # Rating
        rating_tag = soup.select_one(".rating strong")
        data["rating"] = rating_tag.get_text(strip=True).replace("Rating", "").strip() if rating_tag else None

        # Deskripsi singkat (sinopsis)
        desc_tag = soup.select_one(".entry-content p")
        data["synopsis"] = desc_tag.get_text(strip=True) if desc_tag else None

        # Negara
        countries = [a.get_text(strip=True) for a in soup.select('.spe a[href*="/country/"]')]
        data["countries"] = countries

        # Sutradara
        director = [a.get_text(strip=True) for a in soup.select('.spe a[href*="/director/"]')]
        data["director"] = director

        # Artis
        casts = [a.get_text(strip=True) for a in soup.select('.spe a[href*="/cast/"]')]
        data["cast"] = casts

        # Genre
        genres = [a.get_text(strip=True) for a in soup.select('.genxed a')]
        data["genres"] = genres

        # Trailer (iframe YouTube)
        trailer_tag = soup.select_one(".trailer iframe")
        data["trailer_url"] = trailer_tag["src"] if trailer_tag else None

        # Link BluRay (link ke halaman player)
        movie_links = []
        link_tags = soup.select('.eplister li a')
        if link_tags: 
            for tag in link_tags: 
                movie_links.append(tag["href"])

        data["movie_links"] = movie_links

        # Deskripsi tambahan (mindesc)
        mindesc = soup.select_one('.mindesc')
        data["description"] = mindesc.get_text(strip=True) if mindesc else None
        
        return Response(data)

    def movie_details(self, url: str): 
        res = Request.get(url)
        soup = BeautifulSoup(res.text(), "html.parser")

        data = {}

        # Judul
        title = soup.find("h1", class_="entry-title")
        data["title"] = title.get_text(strip=True) if title else None

        # Gambar
        img = soup.find("img", class_="ts-post-image")
        data["image"] = img["src"] if img else None

        # Player utama
        iframe = soup.select_one(".player-embed iframe")
        data["main_player"] = iframe["src"] if iframe else None

        # Server mirror (decode base64)
        mirrors = []
        for opt in soup.select("select.mirror option"): 
            label = opt.get_text(strip=True)
            val = opt.get("value")

            try: 
                decoded = base64.b64decode(val).decode("utf-8")
                iframe_src = BeautifulSoup(decoded, "html.parser").find("iframe")["src"]
                mirrors.append({
                    "server": label,
                    "iframe_src": iframe_src
                })
            except Exception as e:
                pass

        data["streaming_servers"] = mirrors

        # Link download
        downloads = []
        for li in soup.select(".dlbox ul li")[1:]:  # skip header
            server = li.select_one(".q b")
            quality = li.select_one(".w")
            link = li.select_one(".e a")
            if server and quality and link:
                downloads.append({
                    "server": server.get_text(strip=True),
                    "quality": quality.get_text(strip=True),
                    "url": link["href"]
                })
        data["downloads"] = downloads

        # Deskripsi
        desc = soup.select_one(".desc, .mindes, .entry-content p")
        data["description"] = desc.get_text(strip=True) if desc else None

        # Rating
        rating = soup.select_one(".rating strong")
        data["rating"] = rating.get_text(strip=True).replace("Rating ", "") if rating else None

        return Response(data)

    def playlist_filelions(self, url: str) -> Response: 
        parsed_url = urlparse(url)
        stream_base_url = f"{parsed_url.scheme}://{parsed_url.hostname}"

        m3u8_result = FileLions.extract_m3u8(url, referer=self.BASE_URL)
        hls4_path = m3u8_result.get("hls4")
        
        url = f"{stream_base_url}{hls4_path}"
        res = Request.get(url)

        m3u8_raw = m3u8.loads(res.text())
        playlist = []
        for item in m3u8_raw.playlists: 
            item_url = url.replace("master.m3u8", item.uri)
            resolution = f"{item.stream_info.resolution[1]}p"
            playlist.append({
                "url": item_url,
                "resolution": resolution
            })

        return Response(playlist)

    def m3u8_filelions(self, url: str):
        res = Request.get(url)
        res_text = res.text()

        m3u8_data = m3u8.loads(res_text).segments
        return m3u8_data

    def download_filelions(self, url: str, max_workers: int = 16) -> bytes: 
        segments = self.m3u8_filelions(url)

        total_segments = len(segments)
        start_time = time.time()

        total_bytes, finished_segments, next_segment_to_yield = 0, 0, 0
        results = [None] * total_segments
        total_bytes = 0
        finished_segments = 0
        lock, segment_buffer = threading.Lock(), {}

        # Flag untuk memberitahu thread jika terjadi error fatal
        stop_event = threading.Event()

        def download_segment(segment, idx):
            """Worker thread (Producer)."""
            max_retries = 5
            for attempt in range(max_retries):
                # Jika thread utama meminta berhenti, hentikan thread ini
                if stop_event.is_set():
                    return
                
                try:
                    r = Request.get(segment.uri, timeout=30, stream=True)
                    content = r.content()
                    
                    sync_pos = content.find(SYNC_BYTE, 0)
                    data_to_write = content[sync_pos:]
                    
                    with lock:
                        segment_buffer[idx] = data_to_write
                        nonlocal total_bytes, finished_segments
                        total_bytes += len(data_to_write)
                        finished_segments += 1
                    return # Sukses, keluar dari loop retry
                except Exception as e:
                    print(f"\n[RETRY {attempt+1}/{max_retries}] Segmen {idx}: {type(e).__name__}")
                    if attempt < max_retries - 1:
                        time.sleep(1 + attempt) # Jeda lebih lama setiap kali gagal
                    else:
                        print(f"\n[FAIL] Gagal total segmen {idx}.")
                        with lock: segment_buffer[idx] = b'' # Tandai gagal
                        stop_event.set() # Beritahu thread lain untuk berhenti jika satu gagal total
                        return

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try: 
            for i, segment in enumerate(segments):
                executor.submit(download_segment, segment, i)
            
            # Loop utama (Consumer) yang berjalan BERSAMAAN dengan unduhan
            while next_segment_to_yield < total_segments:
                if stop_event.is_set():
                    raise RuntimeError("Download dihentikan karena salah satu segmen gagal diunduh berulang kali.")

                # Apakah segmen berikutnya sudah ada di buffer?
                if next_segment_to_yield in segment_buffer:
                    chunk = segment_buffer.pop(next_segment_to_yield)
                    if chunk:
                        yield chunk
                    next_segment_to_yield += 1

                    with lock:
                        elapsed = time.time() - start_time  
                        speed = (total_bytes / (1024*1024)) / elapsed if elapsed > 0 else 0
                
                        eta_str = "..." # Default string saat ETA belum bisa dihitung
                        if speed > 0 and finished_segments > 0:
                            # 1. Hitung rata-rata ukuran per segmen
                            avg_segment_size = total_bytes / finished_segments
                            # 2. Estimasi total ukuran file
                            estimated_total_size = avg_segment_size * total_segments
                            # 3. Hitung sisa data yang perlu diunduh
                            remaining_bytes = estimated_total_size - total_bytes
                            # 4. Hitung estimasi waktu sisa dalam detik
                            eta_seconds = remaining_bytes / (speed * 1024 * 1024)
                    
                            if eta_seconds > 0:
                                # 5. Format menjadi jam:menit:detik
                                eta_str = str(datetime.timedelta(seconds=int(eta_seconds)))
                
                        print(
                            f"Progress: {finished_segments}/{total_segments} | "
                            f"Downloaded: {total_bytes / (1024*1024):.2f} MB | "
                            f"Speed: {speed:.2f} MB/s | "
                            f"ETA: {eta_str}",
                            end='\r'
                        )

        finally:
            print("\nProses selesai, membersihkan resources...".ljust(120))
            executor.shutdown(wait=False, cancel_futures=True)

if __name__ == "__main__": 
    oppa = OppaDrama()
