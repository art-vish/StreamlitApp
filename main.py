import streamlit as st
import requests
import os
import json
import base64
from pathlib import Path
from mistralai import Mistral, DocumentURLChunk, ImageURLChunk, TextChunk
from mistralai.models import OCRResponse

# Set page configuration
st.set_page_config(
    page_title="Mistral OCR PDF Processor",
    page_icon="📄",
    layout="wide"
)

st.title("Mistral OCR PDF Processor")
st.write("Upload a PDF file to process it with Mistral's OCR service")


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


# API key input with default value that can be changed
api_key = st.text_input("Enter your Mistral API key:", value="", type="password")

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
    if st.button("Process PDF with OCR"):
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
                    # Display raw JSON response (limited to first 1000 chars for preview)
                    st.json(response_dict)

                st.success("PDF processing completed!")

            # Clean up the temporary file
            os.remove(temp_file_path)

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            # Clean up the temporary file in case of error
            if temp_file_path.exists():
                os.remove(temp_file_path)

# Add some information about the app
st.sidebar.title("About")
st.sidebar.info(
    "This app uses Mistral AI's OCR service to extract text and images from PDF documents. "
    "Upload a PDF file, click 'Process', and view the extracted content in markdown format."
)
