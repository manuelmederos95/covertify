# Covertify - Image to Video Generator

A web application that transforms images into stunning AI-generated videos using the Runway API.

## Features

- Upload images (PNG, JPG, JPEG, GIF, WEBP)
- Custom video prompts for motion and style
- Adjustable video duration (5-10 seconds)
- Real-time video generation progress
- Automatic generation of 3 platform-specific formats:
  - **Spotify Canvas**: 9:16 vertical (1080x1920)
  - **Apple Music Standard**: 1:1 square (3840x3840)
  - **Apple Music Listening Mode**: 3:4 portrait (2048x2732)
- Preview and download all generated videos
- Beautiful, responsive UI with drag-and-drop support

## Prerequisites

- Python 3.9 or higher
- Runway API key
- FFmpeg (for video processing)

## Installation

1. Clone or navigate to the project directory:
```bash
cd /Users/manuelmederos/Desktop/Covertify
```

2. Create and activate a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up your Runway API key:
```bash
export RUNWAYML_API_SECRET="your_runway_api_key_here"
```

Or create a `.env` file with:
```
RUNWAYML_API_SECRET=your_runway_api_key_here
```

## Running the Application

1. Start the Flask server:
```bash
python app.py
```

2. Open your browser and navigate to:
```
http://localhost:8080
```

## Usage

1. **Upload an Image**: Click the upload area or drag and drop an image
2. **Enter a Prompt**: Describe the motion and style you want (e.g., "Subtle cinematic motion, slow zoom in, floating dust particles, high quality")
3. **Set Duration**: Choose video duration (5-10 seconds)
4. **Generate**: Click "Generate Video" and wait for processing (may take several minutes)
5. **Download**: Preview and download all 3 platform-specific videos:
   - Spotify Canvas (9:16 vertical)
   - Apple Music Standard View (1:1 square)
   - Apple Music Full Screen Mobile (3:4 portrait)

## Project Structure

```
Covertify/
├── app.py                      # Main Flask application
├── templates/
│   └── index.html             # Web interface
├── uploads/                    # Uploaded images (auto-created)
├── Result/                     # Generated videos (auto-created)
├── Runway API/
│   ├── generate_cover.py      # Runway API integration
│   ├── process_video.py       # Video processing utilities
│   └── apiKey.txt             # API key storage
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## API Endpoints

- `GET /` - Main web interface
- `POST /upload` - Upload image and generate video
- `GET /download/<filename>` - Download generated video
- `GET /preview/<filename>` - Preview video in browser

## Runway API Integration

The application uses the Runway Gen-3 Alpha Turbo model for image-to-video generation:

- **Model**: `gen3a_turbo`
- **Ratio**: 1280:768
- **Duration**: 5-10 seconds
- **Input**: Base64-encoded images

## Tips for Best Results

1. Use high-quality images (at least 1280x768)
2. Craft detailed prompts describing the desired motion
3. Start with 5-second videos for faster generation
4. Use descriptive keywords: "cinematic", "slow motion", "zoom", "pan", etc.

## Troubleshooting

- **API Key Error**: Make sure `RUNWAYML_API_SECRET` is set in environment variables
- **File Upload Error**: Check file size (max 16MB) and format (PNG, JPG, JPEG, GIF, WEBP)
- **Video Generation Failed**: Check your Runway API credits and usage limits
- **Port Already in Use**: Change the port in `app.py` (default is 5000)

## License

This project is for educational and demonstration purposes.

## Credits

- Built with Flask and Runway API
- UI inspired by modern web design principles
