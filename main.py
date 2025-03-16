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
    page_title="Mistral OCR PDF Processor",
    page_icon="📄",
    layout="wide"
)

st.title("Mistral OCR PDF Processor")
st.write("Upload a PDF file or take a photo to process with Mistral's OCR service")


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
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode()


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
input_tab1, input_tab2 = st.tabs(["Upload PDF", "Take Photo"])

with input_tab1:
    # File uploader
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

    if uploaded_file is not None:
        # Save the uploaded file temporarily
        with st.spinner("Saving uploaded file..."):
            temp_file_path = Path(f"temp_{uploaded_file.name}")
            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            st.success(f"File uploaded: {uploaded_file.name}")

        # Process button
        if st.button("Process PDF with OCR", key="process_pdf"):
            try:
                with st.spinner("Processing PDF with Mistral OCR..."):
                    # Initialize Mistral client
                    client = Mistral(api_key=api_key)

                    # Verify PDF file exists
                    pdf_file = temp_file_path
                    assert pdf_file.is_file()

                    # Upload PDF file to Mistral's OCR service
                    mistral_uploaded_file = client.files.upload(
                        file={
                            "file_name": pdf_file.stem,
                            "content": pdf_file.read_bytes(),
                        },
                        purpose="ocr",
                    )

                    # Get URL for the uploaded file
                    signed_url = client.files.get_signed_url(file_id=mistral_uploaded_file.id, expiry=1)

                    # Process PDF with OCR, including embedded images
                    pdf_response = client.ocr.process(
                        document=DocumentURLChunk(document_url=signed_url.url),
                        model="mistral-ocr-latest",
                        include_image_base64=True
                    )

                    # Convert response to JSON format for display
                    response_dict = json.loads(pdf_response.model_dump_json())

                    # Display results
                    st.subheader("OCR Results")

                    # Create tabs for different views
                    tab1, tab2 = st.tabs(["Markdown View", "JSON Response"])

                    with tab1:
                        # Display combined markdowns and images
                        combined_markdown = get_combined_markdown(pdf_response)
                        st.markdown(combined_markdown, unsafe_allow_html=True)

                    with tab2:
                        # Display raw JSON response
                        st.json(response_dict)

                    st.success("PDF processing completed!")

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
        st.image(camera_image, caption="Captured Image", use_column_width=True)

        # Process button for camera image
        if st.button("Process Image with OCR", key="process_image"):
            try:
                with st.spinner("Processing image with Mistral OCR..."):
                    # Initialize Mistral client
                    client = Mistral(api_key=api_key)

                    # Open the image
                    image = Image.open(camera_image)

                    # Save the image temporarily
                    temp_image_path = Path("temp_camera_image.jpg")
                    image.save(temp_image_path)

                    # Upload image file to Mistral's OCR service
                    mistral_uploaded_file = client.files.upload(
                        file={
                            "file_name": "camera_image",
                            "content": temp_image_path.read_bytes(),
                        },
                        purpose="ocr",
                    )

                    # Get URL for the uploaded file
                    signed_url = client.files.get_signed_url(file_id=mistral_uploaded_file.id, expiry=1)

                    # Process image with OCR, including embedded images
                    image_response = client.ocr.process(
                        document=DocumentURLChunk(document_url=signed_url.url),
                        model="mistral-ocr-latest",
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

                # Clean up the temporary file
                os.remove(temp_image_path)

            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                # Clean up the temporary file in case of error
                if Path("temp_camera_image.jpg").exists():
                    os.remove("temp_camera_image.jpg")

# Add some information about the app
st.sidebar.title("About")
st.sidebar.info(
    "This app uses Mistral AI's OCR service to extract text and images from PDF documents "
    "or photos taken with your camera. Upload a PDF file or take a photo, click 'Process', "
    "and view the extracted content in markdown format."
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