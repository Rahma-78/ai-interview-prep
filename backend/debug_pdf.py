#!/usr/bin/env python3
"""
Debug script to test PDF extraction
"""
import os
import PyPDF2
import traceback

def test_pdf_extraction(pdf_path):
    """Test PDF extraction with detailed error handling"""
    print(f"Testing PDF extraction for: {pdf_path}")
    print(f"File exists: {os.path.exists(pdf_path)}")
    print(f"File size: {os.path.getsize(pdf_path)} bytes")
    
    try:
        # Try to open the file
        with open(pdf_path, 'rb') as file:
            print("File opened successfully")
            
            # Try to create PDF reader
            try:
                reader = PyPDF2.PdfReader(file)
                print(f"PDF reader created successfully")
                print(f"Number of pages: {len(reader.pages)}")
                
                # Extract text from each page
                total_text = ""
                for i, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text()
                        print(f"Page {i+1}: {len(page_text)} characters")
                        total_text += page_text + "\n"
                    except Exception as page_error:
                        print(f"Error extracting page {i+1}: {page_error}")
                
                if total_text.strip():
                    print(f"Successfully extracted {len(total_text)} characters total")
                    print("First 200 characters:")
                    print(repr(total_text[:200]))
                    return total_text
                else:
                    print("No text extracted from PDF")
                    return None
                    
            except Exception as reader_error:
                print(f"Error creating PDF reader: {reader_error}")
                traceback.print_exc()
                return None
                
    except Exception as open_error:
        print(f"Error opening file: {open_error}")
        traceback.print_exc()
        return None

if __name__ == "__main__":
    pdf_path = "Rahma Ashraf AlShafi'i.pdf"
    result = test_pdf_extraction(pdf_path)
    
    if result:
        print("\nPDF extraction successful!")
    else:
        print("\nPDF extraction failed!")