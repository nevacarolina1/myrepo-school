# Ganti dengan versi Python yang sesuai
FROM python:3.12

# Membuat direktori kerja
RUN mkdir -p /movies

# Set direktori kerja
WORKDIR /movies

# Menyalin semua file dari direktori saat ini ke dalam image
COPY . .

# Instal dependensi dari requirements.txts
RUN pip install --no-cache-dir -r requirements.txt
RUN apt update -y
RUN apt install ffmpeg

# Menginformasikan Docker bahwa aplikasi mendengarkan pada port 80
EXPOSE 3000

RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
