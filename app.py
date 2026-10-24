from flask import Flask, render_template
import os
import json
from google.cloud import storage  # ← import for GCS
from json.decoder import JSONDecodeError

app = Flask(__name__)
DATA_FOLDER = 'downloaded_audios'
warning_triggered = False  # ← your boolean trigger
GCS_BUCKET_NAME = 'iott-32784.firebasestorage.app'  # ← replace with your bucket name
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")

def upload_to_gcs(source_file_path, destination_blob_name):
    """Uploads a file to the specified GCS bucket."""
    client = storage.Client(PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_path)
    print(f"Uploaded {source_file_path} to gs://{GCS_BUCKET_NAME}/{destination_blob_name}")


def load_all_sensor_data():
    sensor_files = sorted(
        [f for f in os.listdir(DATA_FOLDER) if f.startswith('sensor_') and f.endswith('.json')],
        reverse=True
    )
    sensor_data = []
    for file in sensor_files:
        path = os.path.join(DATA_FOLDER, file)
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                sensor_data.append({
                    'filename': file,
                    'data': data
                })
        except (JSONDecodeError, OSError) as e:
            print(f"Skipping file {file}: {e}")
    return sensor_data

def load_latest_prediction():
    prediction_files = sorted(
        [f for f in os.listdir(DATA_FOLDER) if f.startswith('audio') and f.endswith('.json')],
        reverse=True
    )
    if not prediction_files:
        return None

    prediction_path = os.path.join(DATA_FOLDER, prediction_files[0])
    with open(prediction_path, 'r') as pred_file:
        prediction_data = json.load(pred_file)

    # Write to warning.txt based on the prediction
    is_bird = prediction_data.get('predicted_class') == 'Crow' or prediction_data.get('predicted_class') == 'Animal'
    with open('warning.txt', 'w') as warn_file:
        warn_file.write('true' if is_bird else 'false')
    
    # Upload the file
    upload_to_gcs('warning.txt', 'warning.txt')

    return prediction_data, is_bird


@app.route('/')
def index():
    all_sensors = load_all_sensor_data()
    latest_prediction, warning_triggered = load_latest_prediction()
    return render_template('index.html', sensors=all_sensors, prediction=latest_prediction, warning=warning_triggered)

if __name__ == '__main__':
    app.run(debug=True)
