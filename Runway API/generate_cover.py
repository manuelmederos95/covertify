import os
import time
from runwayml import RunwayML, TaskFailedError

# 1. Initialize the client
# Ensure you have 'export RUNWAYML_API_SECRET="your_key"' in your terminal
client = RunwayML()

def generate_animated_cover(image_url, prompt):
    try:
        print(f"🚀 Starting generation for: {prompt}")
        
        # 2. Create the Image-to-Video task
        # We use gen3a_turbo for the best speed/cost ratio
        task = client.image_to_video.create(
            model='gen3a_turbo',
            prompt_image=image_url,
            prompt_text=prompt,
            ratio="1280:768", # You will later crop this with FFmpeg
            duration=5        # Standard 5-second loop
        )
        
        task_id = task.id
        print(f"⏳ Task created (ID: {task_id}). Waiting for completion...")

        # 3. Poll for the result
        while True:
            task = client.tasks.retrieve(task_id)
            if task.status == 'SUCCEEDED':
                print("✅ Generation Complete!")
                return task.output[0] # This is the URL to your video
            elif task.status == 'FAILED':
                print(f"❌ Task failed: {task.failure_reason}")
                return None
            
            time.sleep(5) # Wait 5 seconds before checking again
            
    except TaskFailedError as e:
        print(f"API Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

# --- TEST RUN ---
if __name__ == "__main__":
    # Replace with a real URL of your cover art (must be public for this test)
    import base64

def file_to_data_uri(file_path):
    with open(file_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{data}"

# Use a local file on your computer
    TEST_IMAGE = file_to_data_uri("/Users/manuelmederos/Desktop/Covertify/NadieCover-3.jpg")
    TEST_PROMPT = "Subtle cinematic motion, slow zoom in, floating dust particles, high quality"
    
    video_url = generate_animated_cover(TEST_IMAGE, TEST_PROMPT)
    if video_url:
        print(f"🔗 Your animated cover is ready: {video_url}")