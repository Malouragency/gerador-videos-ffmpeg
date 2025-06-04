FROM python:3.9-slim
RUN apt-get update && apt-get install -y ffmpeg
COPY . /app
WORKDIR /app
RUN pip install flask
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]
