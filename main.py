import os
from flask import Flask, request
from cloudevents.http import CloudEvent # Not strictly needed if `request.json` is used
import json
import tempfile
import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
import base64
from scipy.signal import resample
from google.cloud import storage # Import for GCS interaction
import csv

#os.environ['CUDA_VISIBLE_DEVICES'] = '-1' # This tells TensorFlow to not use any GPU
#os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0' 
print("GPUs:", tf.config.list_physical_devices('GPU'))

# --- YAMNet Model Loading (unchanged) ---
yamnet_model = hub.load('https://tfhub.dev/google/yamnet/1')
class_map_path = yamnet_model.class_map_path().numpy().decode()

with tf.io.gfile.GFile(class_map_path) as f:
    reader = csv.reader(f)
    next(reader)  # Skip header
    class_names = [row[2] for row in reader]  # Use display_name column

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")

# Initialize GCS client (needed for local testing if you mock GCS)
# Or, if you're truly mocking, you might pass a mock client into your function.
# For simplicity, we'll assume a real client for now if you have GCS credentials set up.
# If you don't want to hit real GCS, you'll need to mock `google.cloud.storage`.
storage_client = storage.Client(project=PROJECT_ID)


# This will be your entry point function for the Functions Framework
def process_yamnet_event(request):
    """
    HTTP Cloud Function that processes CloudEvents from Pub/Sub or Cloud Storage.
    Args:
        request (flask.Request): The request object.
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`.
    """
    try:
        event_data = request.json
        if not event_data:
            raise ValueError("No JSON data received in the request.")

        # Determine event type from headers or content
        event_type = request.headers.get("ce-type")
        
        bucket_name = None
        file_name = None

        if event_type == "google.cloud.pubsub.message":
            pubsub_message = event_data.get('message', {})
            data_b64 = pubsub_message.get('data')
            if data_b64:
                payload = json.loads(base64.b64decode(data_b64).decode('utf-8'))
                bucket_name = payload.get('bucket')
                file_name = payload.get('file_name')
            else:
                # Fallback if 'data' field is missing, maybe direct message body
                payload = event_data
                bucket_name = payload.get('bucket')
                file_name = payload.get('file_name')

        elif event_type == "google.cloud.storage.object.v1.finalized":
            storage_data = event_data.get('data', {})
            bucket_name = storage_data.get('bucket')
            file_name = storage_data.get('name')
        else:
            # Handle other event types or a generic payload assuming direct bucket/file_name
            bucket_name = event_data.get('bucket')
            file_name = event_data.get('file_name')

        if not bucket_name or not file_name:
            return "Missing 'bucket' or 'file_name' in event data.", 400

        print(f"Received event for bucket: {bucket_name}, file: {file_name}")

        if not file_name.endswith(".raw"):
            print(f"Skipping non-raw file: {file_name}")
            return f"Skipped: {file_name} is not a .raw file", 200 # Return 200 for successful skip

        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_name)

        # Download the raw file to temp
        with tempfile.NamedTemporaryFile(delete=False, suffix=".raw") as temp_raw:
            blob.download_to_filename(temp_raw.name)
            temp_raw_path = temp_raw.name # Store path for cleanup if needed

        try:
            # Convert raw -> numpy array 
            raw_data = np.fromfile(temp_raw_path, dtype=np.int16)
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
                "file": file_name,
                "predicted_class": predicted_class,
                "confidence": round(confidence, 4)
            }

            json_filename = file_name.replace(".raw", "_prediction.json")
            json_blob = bucket.blob(json_filename)
            json_blob.upload_from_string(json.dumps(prediction_result), content_type="application/json")
            
            result_message = f"Processed {file_name} from {bucket_name}, predicted '{predicted_class}' with confidence {confidence:.4f}."
            print(result_message)
            return result_message, 200
        finally:
            # Clean up the temporary file
            os.remove(temp_raw_path)

    except Exception as e:
        print(f"Error processing event: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        return f"Error: {e}", 500

# When running with functions-framework, it calls process_yamnet_event directly.
# The Flask app boilerplate below is primarily for when you run the app directly
# or for potential deployment as a generic Cloud Run service (not as a Cloud Function).
# For testing with functions-framework, this __main__ block is not used.
if __name__ == '__main__':
    # This block is for direct Flask app execution, not for functions-framework
    app = Flask(__name__) # Define app here if only running in __main__
    @app.route('/', methods=['POST'])
    def wrapper_handle_event():
        return process_yamnet_event(request)

    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True) # debug=True for local development