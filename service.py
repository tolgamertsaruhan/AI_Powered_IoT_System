import os
import time
from google.cloud import storage
import os
import json
import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
from scipy.signal import resample
from google.cloud import storage # Import for GCS interaction
import csv

# Configuration
BUCKET_NAME = 'iott-32784.firebasestorage.app'
DOWNLOAD_DIR = './downloaded_audios'
CHECK_INTERVAL = 10  # seconds
AUDIO_EXTENSIONS = ('.raw', '.json')

# --- YAMNet Model Loading (unchanged) ---
yamnet_model = hub.load('https://tfhub.dev/google/yamnet/1')
class_map_path = yamnet_model.class_map_path().numpy().decode()

with tf.io.gfile.GFile(class_map_path) as f:
    reader = csv.reader(f)
    next(reader)  # Skip header
    class_names = [row[2] for row in reader]  # Use display_name column

# Make sure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Initialize GCS client
client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

def predict(path):
    raw_data = np.fromfile(path, dtype=np.int16)
    waveform = raw_data / 32768.0  # Normalize
    sample_rate = 8000 #recorded waw sample rate

    desired_sample_rate = 16000 #yamnet default input
    resample_factor = desired_sample_rate / sample_rate
    num_samples = int(len(waveform) * resample_factor)
    waveform_16k = resample(waveform, num_samples)

    print("predicting...")
    # Predict
    scores, embeddings, spectrogram = yamnet_model(waveform_16k)
    mean_scores = tf.reduce_mean(scores, axis=0)
    top_class = tf.argmax(mean_scores).numpy()
    predicted_class = class_names[top_class]
    confidence = float(mean_scores[top_class].numpy())
    print("predicted!!!")

    # Save prediction to JSON
    prediction_result = {
        "file": path,
        "predicted_class": predicted_class,
        "confidence": round(confidence, 4)
    }

    json_filename = path.replace(".raw", "_prediction.json")
    json_blob = bucket.blob(json_filename)
    json_blob.upload_from_string(json.dumps(prediction_result), content_type="application/json")
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(prediction_result, f, indent=2)

    result_message = f"Processed {path} from {BUCKET_NAME}, predicted '{predicted_class}' with confidence {confidence:.4f}."
    print(result_message)
    return result_message, 200

def is_audio(blob_name):
    return blob_name.lower().endswith(AUDIO_EXTENSIONS)

def already_downloaded(blob_name):
    local_path = os.path.join(DOWNLOAD_DIR, os.path.basename(blob_name))
    return os.path.exists(local_path)

def download_blob(blob):
    local_path = os.path.join(DOWNLOAD_DIR, os.path.basename(blob.name))
    blob.download_to_filename(local_path)
    print(f"Downloaded: {blob.name} -> {local_path}")
    if local_path.endswith('.raw'):
        predict(local_path)

def check_and_download_new_files():
    blobs = list(bucket.list_blobs())
    for blob in blobs:
        if is_audio(blob.name) and not already_downloaded(blob.name):
            download_blob(blob)



if __name__ == '__main__':
    print("Monitoring GCS bucket for new audio files...")
    while True:
        check_and_download_new_files()
        time.sleep(CHECK_INTERVAL)
