FROM python:3.12.2

WORKDIR /app/schtroumpfette

# ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# pip >= 26.2.2 : CVE-2026-1703, CVE-2026-3219, CVE-2026-8643, CVE-2026-13346 + certifi vendored à jour
RUN pip install --no-cache-dir -U "pip>=26.2.2" && \
    pip install --no-cache-dir -U -r requirements.txt

COPY . .

# Commit de l'image, annoncé au démarrage dans le salon de logs (vide en local = « version locale »)
ARG GIT_SHA=""
ENV GIT_SHA=$GIT_SHA

CMD ["python3", "-u", "main.py"]
