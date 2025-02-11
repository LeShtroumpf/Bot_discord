FROM python:3.12.6

# RUN mkdir -p /schtroumpfette
WORKDIR /app/schtroumpfette

COPY requirements.txt .

RUN pip install --no-cache-dir -U -r requirements.txt

COPY . /app

RUN echo "hello to schtroumpfette"
CMD ["python3", "-u", "main.py"]
