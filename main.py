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
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import re
from datetime import datetime

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
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


# Function to translate text using Mistral API
def translate_text(text, target_language, client):
    """
    Translate text to the target language using Mistral's text model.

    Args:
        text: Text to translate
        target_language: Target language for translation
        client: Mistral client instance

    Returns:
        Translated text
    """
    prompt = f"Translate the following text to {target_language}. Preserve the formatting and structure as much as possible:\n\n{text}"

    response = client.chat.complete(
        model="mistral-small-latest",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content


# Function to extract tables from markdown
def extract_tables_from_markdown(markdown_text):
    """Extract tables and surrounding text from markdown."""
    # Split the markdown by table markers
    parts = re.split(r'(\n\|.*\|.*\n(?:\|.*\|.*\n)+)', markdown_text)

    result = []
    i = 0
    while i < len(parts):
        if i < len(parts) and not parts[i].strip().startswith('|'):
            # This is text content
            if parts[i].strip():
                result.append({"type": "text", "content": parts[i].strip()})

        # Check if we have a table part
        if i < len(parts) and '|' in parts[i]:
            table_text = parts[i].strip()
            # Extract table rows
            rows = [row for row in table_text.split('\n') if row.strip().startswith('|')]

            # Skip separator row (contains :--:, :-- or --:)
            header_rows = []
            data_rows = []

            for j, row in enumerate(rows):
                if ':--' in row or '--:' in row or '---' in row:
                    header_rows = rows[:j]
                    data_rows = rows[j + 1:]
                    break

            if not header_rows and not data_rows:
                # No separator found, treat first row as header
                header_rows = [rows[0]] if rows else []
                data_rows = rows[1:] if len(rows) > 1 else []

            # Parse the table
            headers = [cell.strip() for cell in header_rows[0].split('|')[1:-1]] if header_rows else []
            data = []
            for row in data_rows:
                cells = [cell.strip() for cell in row.split('|')[1:-1]]
                data.append(cells)

            result.append({
                "type": "table",
                "headers": headers,
                "data": data
            })

        i += 1

    return result


# Function to add table to Word document
def add_table_to_document(doc, table_data):
    """Add a table to the Word document."""
    headers = table_data["headers"]
    data = table_data["data"]

    # Create table
    rows_count = len(data) + 1  # +1 for header
    cols_count = max(len(headers), max([len(row) for row in data]) if data else 0)

    table = doc.add_table(rows=rows_count, cols=cols_count)
    table.style = 'Table Grid'

    # Add headers
    header_row = table.rows[0]
    for i, header in enumerate(headers):
        if i < cols_count:
            cell = header_row.cells[i]
            cell.text = header
            # Make headers bold
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True

    # Add data
    for i, row_data in enumerate(data):
        row = table.rows[i + 1]  # +1 to skip header
        for j, cell_data in enumerate(row_data):
            if j < cols_count:
                cell = row.cells[j]
                cell.text = cell_data


# Function to add text to Word document
def add_text_to_document(doc, text_data):
    """Add text content to the Word document."""
    lines = text_data["content"].split('\n')
    for line in lines:
        if line.startswith('#'):
            # Count the number of # to determine heading level
            level = len(line) - len(line.lstrip('#'))
            text = line.lstrip('# ')
            doc.add_heading(text, level=level)
        else:
            if line.strip():  # Only add non-empty lines
                doc.add_paragraph(line)


# Function to convert markdown to Word document
def markdown_to_docx(markdown_text):
    """Convert markdown text to a Word document and return bytes."""
    doc = Document()

    # Extract content from markdown
    content_parts = extract_tables_from_markdown(markdown_text)

    # Process each part
    for part in content_parts:
        if part["type"] == "text":
            add_text_to_document(doc, part)
        elif part["type"] == "table":
            add_table_to_document(doc, part)
            # Add a small space after table
            doc.add_paragraph()

    # Save the document to a bytes buffer instead of a file
    docx_bytes = io.BytesIO()
    doc.save(docx_bytes)
    docx_bytes.seek(0)

    return docx_bytes.getvalue()


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

            # Translation options
            st.subheader("Translation Options")
            enable_translation = st.checkbox("Translate OCR results", value=False)
            target_language = st.selectbox(
                "Select target language",
                ["English", "Spanish", "French", "German", "Italian", "Portuguese", "Chinese", "Japanese", "Russian",
                 "Arabic"],
                disabled=not enable_translation
            )

            # Process button
            if st.button("Process Document with OCR", key="process_document"):
                try:
                    with st.spinner(f"Processing {file_extension.upper()} with Mistral OCR..."):
                        # Initialize Mistral client
                        client = Mistral(api_key=api_key)

                        # Verify file exists
                        assert temp_file_path.is_file()

                        # Process document with OCR based on file type
                        if file_extension in ['jpeg', 'jpg', 'png']:
                            # For images, use ImageURLChunk
                            # First, convert the image to base64
                            with open(temp_file_path, "rb") as image_file:
                                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

                            # Process image with OCR
                            document_response = client.ocr.process(
                                document=ImageURLChunk(image_url=f"data:image/{file_extension};base64,{base64_image}"),
                                model="mistral-ocr-latest",
                                include_image_base64=True
                            )
                        else:
                            # For PDFs, use the file upload approach
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

                        # Get combined markdown
                        combined_markdown = get_combined_markdown(document_response)

                        # Extract text without images for translation
                        text_only = "\n\n".join([page.markdown for page in document_response.pages])

                        # Translate if requested
                        translated_markdown = None
                        if enable_translation:
                            with st.spinner(f"Translating text to {target_language}..."):
                                translated_text = translate_text(text_only, target_language, client)
                                translated_markdown = f"## Translated Text ({target_language})\n\n{translated_text}"

                        # Display results
                        st.subheader("OCR Results")

                        # Create tabs for different views
                        if enable_translation:
                            tab1, tab2, tab3 = st.tabs(
                                ["Original Content", "JSON Response", f"Translated to {target_language}"])

                            with tab1:
                                # Export to Word button
                                if st.button("Export Original Text to Word", key="export_original_tab1"):
                                    with st.spinner("Converting to Word document..."):
                                        try:
                                            # Get document as bytes
                                            docx_bytes = markdown_to_docx(text_only)

                                            # Create download button
                                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                            st.download_button(
                                                label="📥 Download Word Document",
                                                data=docx_bytes,
                                                file_name=f"ocr_result_{timestamp}.docx",
                                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                key="download_original_tab1"
                                            )
                                            st.success("Document ready for download!")
                                        except Exception as e:
                                            st.error(f"Error creating Word document: {str(e)}")

                                # Display original markdowns and images
                                st.markdown(combined_markdown, unsafe_allow_html=True)

                            with tab2:
                                # Display raw JSON response
                                st.json(response_dict)

                            with tab3:
                                # Export translated text to Word button
                                if st.button("Export Translated Text to Word", key="export_translated_tab3"):
                                    with st.spinner("Converting translated text to Word document..."):
                                        try:
                                            # Get document as bytes
                                            translated_text_only = translated_text if translated_text else ""
                                            docx_bytes = markdown_to_docx(translated_text_only)

                                            # Create download button
                                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                            st.download_button(
                                                label="📥 Download Translated Word Document",
                                                data=docx_bytes,
                                                file_name=f"translated_{timestamp}.docx",
                                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                key="download_translated_tab3"
                                            )
                                            st.success("Translated document ready for download!")
                                        except Exception as e:
                                            st.error(f"Error creating translated Word document: {str(e)}")

                                # Display translated text
                                st.markdown(translated_markdown)
                        else:
                            tab1, tab2, tab3 = st.tabs(["Markdown View", "JSON Response", "Translate On Demand"])

                            with tab1:
                                # Export to Word button
                                if st.button("Export to Word Document", key="export_word_tab1"):
                                    with st.spinner("Converting to Word document..."):
                                        try:
                                            # Get document as bytes
                                            docx_bytes = markdown_to_docx(text_only)

                                            # Create download button
                                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                            st.download_button(
                                                label="📥 Download Word Document",
                                                data=docx_bytes,
                                                file_name=f"ocr_result_{timestamp}.docx",
                                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                key="download_word_tab1"
                                            )
                                            st.success("Document ready for download!")
                                        except Exception as e:
                                            st.error(f"Error creating Word document: {str(e)}")

                                # Display combined markdowns and images
                                st.markdown(combined_markdown, unsafe_allow_html=True)

                            with tab2:
                                # Display raw JSON response
                                st.json(response_dict)

                            with tab3:
                                # On-demand translation
                                st.subheader("Translate Text On Demand")
                                on_demand_language = st.selectbox(
                                    "Select target language for translation",
                                    ["English", "Spanish", "French", "German", "Italian", "Portuguese", "Chinese",
                                     "Japanese", "Russian", "Arabic"]
                                )

                                if st.button("Translate Now"):
                                    with st.spinner(f"Translating text to {on_demand_language}..."):
                                        on_demand_translation = translate_text(text_only, on_demand_language, client)
                                        st.markdown(
                                            f"## Translated Text ({on_demand_language})\n\n{on_demand_translation}")

                                        # Add export button for on-demand translation
                                        if st.button("Export This Translation to Word", key="export_on_demand"):
                                            with st.spinner("Converting to Word document..."):
                                                try:
                                                    # Get document as bytes
                                                    docx_bytes = markdown_to_docx(on_demand_translation)

                                                    # Create download button
                                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                                    st.download_button(
                                                        label=f"📥 Download {on_demand_language} Word Document",
                                                        data=docx_bytes,
                                                        file_name=f"translated_{on_demand_language}_{timestamp}.docx",
                                                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                        key="download_on_demand"
                                                    )
                                                    st.success("Translated document ready for download!")
                                                except Exception as e:
                                                    st.error(f"Error creating translated Word document: {str(e)}")

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

        # Translation options
        st.subheader("Translation Options")
        enable_translation = st.checkbox("Translate OCR results", value=False, key="camera_translate")
        target_language = st.selectbox(
            "Select target language",
            ["English", "Spanish", "French", "German", "Italian", "Portuguese", "Chinese", "Japanese", "Russian",
             "Arabic"],
            disabled=not enable_translation,
            key="camera_language"
        )

        # Process button for camera image
        if st.button("Process Image with OCR", key="process_image"):
            try:
                with st.spinner("Processing image with Mistral OCR..."):
                    # Initialize Mistral client
                    client = Mistral(api_key=api_key)

                    # Convert the camera image to base64
                    base64_image = base64.b64encode(camera_image.getvalue()).decode('utf-8')

                    # Process image with OCR using ImageURLChunk with image_url
                    image_response = client.ocr.process(
                        document=ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}"),
                        model="mistral-ocr-latest",
                        include_image_base64=True
                    )

                    # Convert response to JSON format for display
                    response_dict = json.loads(image_response.model_dump_json())

                    # Get combined markdown
                    combined_markdown = get_combined_markdown(image_response)

                    # Extract text without images for translation
                    text_only = "\n\n".join([page.markdown for page in image_response.pages])

                    # Translate if requested
                    translated_markdown = None
                    if enable_translation:
                        with st.spinner(f"Translating text to {target_language}..."):
                            translated_text = translate_text(text_only, target_language, client)
                            translated_markdown = f"## Translated Text ({target_language})\n\n{translated_text}"

                    # Display results
                    st.subheader("OCR Results")

                    # Create tabs for different views
                    if enable_translation:
                        tab1, tab2, tab3 = st.tabs(
                            ["Original Content", "JSON Response", f"Translated to {target_language}"])

                        with tab1:
                            # Export to Word button
                            if st.button("Export Original Text to Word", key="camera_export_original_tab1"):
                                with st.spinner("Converting to Word document..."):
                                    try:
                                        # Get document as bytes
                                        docx_bytes = markdown_to_docx(text_only)

                                        # Create download button
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        st.download_button(
                                            label="📥 Download Word Document",
                                            data=docx_bytes,
                                            file_name=f"camera_ocr_{timestamp}.docx",
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            key="camera_download_original_tab1"
                                        )
                                        st.success("Document ready for download!")
                                    except Exception as e:
                                        st.error(f"Error creating Word document: {str(e)}")

                            # Display original markdowns and images
                            st.markdown(combined_markdown, unsafe_allow_html=True)

                        with tab2:
                            # Display raw JSON response
                            st.json(response_dict)

                        with tab3:
                            # Export translated text to Word button
                            if st.button("Export Translated Text to Word", key="camera_export_translated_tab3"):
                                with st.spinner("Converting translated text to Word document..."):
                                    try:
                                        # Get document as bytes
                                        translated_text_only = translated_text if translated_text else ""
                                        docx_bytes = markdown_to_docx(translated_text_only)

                                        # Create download button
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        st.download_button(
                                            label="📥 Download Translated Word Document",
                                            data=docx_bytes,
                                            file_name=f"camera_translated_{timestamp}.docx",
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            key="camera_download_translated_tab3"
                                        )
                                        st.success("Translated document ready for download!")
                                    except Exception as e:
                                        st.error(f"Error creating translated Word document: {str(e)}")

                            # Display translated text
                            st.markdown(translated_markdown)
                    else:
                        tab1, tab2, tab3 = st.tabs(["Markdown View", "JSON Response", "Translate On Demand"])

                        with tab1:
                            # Export to Word button
                            if st.button("Export to Word Document", key="camera_export_word_tab1"):
                                with st.spinner("Converting to Word document..."):
                                    try:
                                        # Get document as bytes
                                        docx_bytes = markdown_to_docx(text_only)

                                        # Create download button
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        st.download_button(
                                            label="📥 Download Word Document",
                                            data=docx_bytes,
                                            file_name=f"camera_ocr_{timestamp}.docx",
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            key="camera_download_word_tab1"
                                        )
                                        st.success("Document ready for download!")
                                    except Exception as e:
                                        st.error(f"Error creating Word document: {str(e)}")

                            # Display combined markdowns and images
                            st.markdown(combined_markdown, unsafe_allow_html=True)

                        with tab2:
                            # Display raw JSON response
                            st.json(response_dict)

                        with tab3:
                            # On-demand translation
                            st.subheader("Translate Text On Demand")
                            on_demand_language = st.selectbox(
                                "Select target language for translation",
                                ["English", "Spanish", "French", "German", "Italian", "Portuguese", "Chinese",
                                 "Japanese", "Russian", "Arabic"],
                                key="camera_on_demand_language"
                            )

                            if st.button("Translate Now", key="camera_translate_now"):
                                with st.spinner(f"Translating text to {on_demand_language}..."):
                                    on_demand_translation = translate_text(text_only, on_demand_language, client)
                                    st.markdown(f"## Translated Text ({on_demand_language})\n\n{on_demand_translation}")

                                    # Add export button for on-demand translation
                                    if st.button("Export This Translation to Word", key="camera_export_on_demand"):
                                        with st.spinner("Converting to Word document..."):
                                            try:
                                                # Get document as bytes
                                                docx_bytes = markdown_to_docx(on_demand_translation)

                                                # Create download button
                                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                                st.download_button(
                                                    label=f"📥 Download {on_demand_language} Word Document",
                                                    data=docx_bytes,
                                                    file_name=f"camera_translated_{on_demand_language}_{timestamp}.docx",
                                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                    key="camera_download_on_demand"
                                                )
                                                st.success("Translated document ready for download!")
                                            except Exception as e:
                                                st.error(f"Error creating translated Word document: {str(e)}")

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
st.sidebar.code("pip install mistralai streamlit pillow python-docx")