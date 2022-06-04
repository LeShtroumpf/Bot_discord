FROM python:3

RUN mkdir -p ./bot_run/run
WORKDIR ./bot_run/run
COPY . .

ENV TOKEN=<INSERT YOUR TOKEN HERE >

RUN pip install --no-cache-dir -U -r requirements.txt
RUN echo "hello world"
CMD ["python3", "main.py"]