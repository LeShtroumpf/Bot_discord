FROM python:3

RUN mkdir -p /schtroumpfette
WORKDIR /schtroumpfette

COPY . schtroumpfette


RUN pip install --no-cache-dir -U -r schtroumpfette/requirements.txt
RUN echo "hello to schtroumpfette"
CMD ["python3", "schtroumpfette/main.py"]
