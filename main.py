import streamlit as st
import requests
import os
import json
import base64
from pathlib import Path
from mistralai import Mistral, DocumentURLChunk, ImageURLChunk, TextChunk
from mistralai.models import OCRResponse
from PIL import Image
import io

# Set page configuration
st.set_page_config(
    page_title="Mistral OCR Document Processor",
    page_icon="📄",
    layout="wide"
)

st.title("Mistral OCR Document Processor")
st.write("Upload a PDF or image file (JPEG, PNG) or take a photo to process with Mistral's OCR service")


# Function to replace image placeholders in markdown with base64-encoded images
def replace_images_in_markdown(markdown_str: str, images_dict: dict) -> str:
    """
    Replace image placeholders in markdown with base64-encoded images.

    Args:
        markdown_str: Markdown text containing image placeholders
        images_dict: Dictionary mapping image IDs to base64 strings

    Returns:
        Markdown text with images replaced by base64 data
    """
    for img_name, base64_str in images_dict.items():
        markdown_str = markdown_str.replace(
            f"![{img_name}]({img_name})", f"![{img_name}]({base64_str})"
        )
    return markdown_str


# Function to combine OCR text and images into a single markdown document
def get_combined_markdown(ocr_response: OCRResponse) -> str:
    """
    Combine OCR text and images into a single markdown document.

    Args:
        ocr_response: Response from OCR processing containing text and images

    Returns:
        Combined markdown string with embedded images
    """
    markdowns: list[str] = []
    # Extract images from page
    for page in ocr_response.pages:
        image_data = {}
        for img in page.images:
            image_data[img.id] = img.image_base64
        # Replace image placeholders with actual images
        markdowns.append(replace_images_in_markdown(page.markdown, image_data))

    return "\n\n".join(markdowns)


# Function to convert image to base64
def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


# Get API key from secrets or user input
def get_api_key():
    # Try to get API key from secrets
    try:
        return st.secrets["mistral_api_key"]
    except:
        # If not available in secrets, return empty string
        return ""


# API key input with default from secrets if available
default_api_key = get_api_key()
user_api_key = st.text_input(
    "Enter your Mistral API key:",
    value="",
    type="password",
    help="Enter your Mistral API key or configure it in st.secrets['mistral_api_key']"
)

# Use the provided API key or fall back to secrets
api_key = user_api_key if user_api_key else default_api_key

if not api_key:
    st.warning("Please provide a Mistral API key to use this application.")
    st.stop()

# Create tabs for different input methods
input_tab1, input_tab2 = st.tabs(["Upload Document", "Take Photo"])

with input_tab1:
    # File uploader with size limit of 50MB
    uploaded_file = st.file_uploader("Choose a PDF or image file (max 50MB)", type=["pdf", "jpeg", "jpg", "png"])

    if uploaded_file is not None:
        # Check file size (50MB = 50 * 1024 * 1024 bytes)
        file_size_limit = 50 * 1024 * 1024  # 50MB in bytes
        file_size = len(uploaded_file.getvalue())

        if file_size > file_size_limit:
            st.error(f"File size exceeds the 50MB limit. Your file is {file_size / (1024 * 1024):.2f}MB.")
        else:
            # Save the uploaded file temporarily
            with st.spinner("Saving uploaded file..."):
                temp_file_path = Path(f"temp_{uploaded_file.name}")
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getvalue())
                st.success(f"File uploaded: {uploaded_file.name} ({file_size / (1024 * 1024):.2f}MB)")

            # Display preview for image files
            file_extension = uploaded_file.name.split('.')[-1].lower()
            if file_extension in ['jpeg', 'jpg', 'png']:
                st.image(uploaded_file, caption="Uploaded Image", use_container_width=True)

            # Process button
            if st.button("Process Document with OCR", key="process_document"):
                try:
                    with st.spinner(f"Processing {file_extension.upper()} with Mistral OCR..."):
                        # Initialize Mistral client
                        client = Mistral(api_key=api_key)

                        # Verify file exists
                        assert temp_file_path.is_file()

                        # Upload file to Mistral's OCR service
                        mistral_uploaded_file = client.files.upload(
                            file={
                                "file_name": temp_file_path.stem,
                                "content": temp_file_path.read_bytes(),
                            },
                            purpose="ocr",
                        )

                        # Get URL for the uploaded file
                        signed_url = client.files.get_signed_url(file_id=mistral_uploaded_file.id, expiry=1)

                        # Process document with OCR, including embedded images
                        document_response = client.ocr.process(
                            document=DocumentURLChunk(document_url=signed_url.url),
                            model="mistral-ocr-latest",
                            include_image_base64=True
                        )

                        # Convert response to JSON format for display
                        response_dict = json.loads(document_response.model_dump_json())

                        # Display results
                        st.subheader("OCR Results")

                        # Create tabs for different views
                        tab1, tab2 = st.tabs(["Markdown View", "JSON Response"])

                        with tab1:
                            # Display combined markdowns and images
                            combined_markdown = get_combined_markdown(document_response)
                            st.markdown(combined_markdown, unsafe_allow_html=True)

                        with tab2:
                            # Display raw JSON response
                            st.json(response_dict)

                        st.success("Document processing completed!")

                    # Clean up the temporary file
                    os.remove(temp_file_path)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
                    # Clean up the temporary file in case of error
                    if temp_file_path.exists():
                        os.remove(temp_file_path)

with input_tab2:
    st.write("Take a photo with your camera")

    # Camera input
    camera_image = st.camera_input("Take a picture")

    if camera_image is not None:
        # Display the captured image
        st.image(camera_image, caption="Captured Image", use_container_width=True)

        # Process button for camera image
        if st.button("Process Image with OCR", key="process_image"):
            try:
                with st.spinner("Processing image with Mistral OCR..."):
                    # Initialize Mistral client
                    client = Mistral(api_key=api_key)

                    # Open the image and convert to base64
                    image = Image.open(camera_image)
                    base64_image = image_to_base64(image)

                    # Process image with OCR using base64 encoding
                    image_response = client.ocr.process(
                        model="mistral-ocr-latest",
                        document={
                            "type": "image_url",
                            "image_url": f"data:image/jpeg;base64,{base64_image}"
                        },
                        include_image_base64=True
                    )

                    # Convert response to JSON format for display
                    response_dict = json.loads(image_response.model_dump_json())

                    # Display results
                    st.subheader("OCR Results")

                    # Create tabs for different views
                    tab1, tab2 = st.tabs(["Markdown View", "JSON Response"])

                    with tab1:
                        # Display combined markdowns and images
                        combined_markdown = get_combined_markdown(image_response)
                        st.markdown(combined_markdown, unsafe_allow_html=True)

                    with tab2:
                        # Display raw JSON response
                        st.json(response_dict)

                    st.success("Image processing completed!")

            except Exception as e:
                st.error(f"An error occurred: {str(e)}")

# Add some information about the app
st.sidebar.title("About")
st.sidebar.info(
    "This app uses Mistral AI's OCR service to extract text and images from PDF documents, "
    "image files (JPEG, PNG), or photos taken with your camera. Upload a document or take a photo, "
    "click 'Process', and view the extracted content in markdown format."
)

# Add API key configuration information
st.sidebar.title("API Key Configuration")
st.sidebar.info(
    "You can provide your Mistral API key in two ways:\n"
    "1. Enter it directly in the text field\n"
    "2. Set it in your Streamlit secrets.toml file as:\n"
    "```\n"
    "mistral_api_key = 'your-api-key-here'\n"
    "```"
)

# Add requirements information
st.sidebar.title("Requirements")
st.sidebar.code("pip install mistralai streamlit pillow")