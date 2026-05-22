# engine/vector.py
"""
Enterprise Vector Inversion Coordinate Transformation & Compilation Engine.
Normalizes CropBox, MediaBox, and rotation matrix offsets using PyMuPDF (fitz).
Calculates precise PostScript Point intersections (Pt) from fractional coordinates.
"""

import os
from typing import Dict, List, Any
import fitz # PyMuPDF
from arabic.engine import reshape_and_bidi, ensure_arabic_font

class PDFVectorCompiler:
    def __init__(self, source_pdf_path: str):
        if not os.path.exists(source_pdf_path):
            raise FileNotFoundError(f"Source PDF not found at path: {source_pdf_path}")
        self.source_path = source_pdf_path
        self._font_path = ensure_arabic_font()

    def inspect_page_dimensions(self, page_index: int) -> Dict[str, Any]:
        """
        Reads original media boxes and rotation angles.
        Provides normalized widths and heights.
        """
        doc = fitz.open(self.source_path)
        try:
            if page_index < 0 or page_index >= len(doc):
                raise IndexError("Page index out of boundaries.")
                
            page = doc[page_index]
            rect = page.rect
            rotation = page.rotation # 0, 90, 180, 270 degrees
            
            # Extract basic metrics
            return {
                "width": rect.width,
                "height": rect.height,
                "rotation": rotation,
                "media_box": list(page.media_box),
                "crop_box": list(page.crop_box)
            }
        finally:
            doc.close()

    def translate_percentages_to_points(
        self, 
        x_pct: float, 
        y_pct: float, 
        pdf_width: float, 
        pdf_height: float,
        rotation: int = 0
    ) -> tuple[float, float]:
        """
        Translates fractional screen coordinates (0-100%) into absolute PostScript Points,
        inverting the Y-axis to account for PDF bottom-left vs web top-left differences.
        Also resolves layout quadrants under custom 90, 180, 270 engine rotations.
        """
        # Clamp inputs to safe regions [0.0, 100.0]
        x_pct = max(0.0, min(100.0, x_pct))
        y_pct = max(0.0, min(100.0, y_pct))

        # Core Translation
        raw_x = (x_pct / 100.0) * pdf_width
        raw_y = pdf_height - ((y_pct / 100.0) * pdf_height)

        # Handle Rotation transforms
        if rotation == 90:
            return raw_y, raw_x
        elif rotation == 180:
            return pdf_width - raw_x, pdf_height - raw_y
        elif rotation == 270:
            return pdf_height - raw_y, pdf_width - raw_x
            
        return raw_x, raw_y

    def compile_filled_document(
        self, 
        payload: List[Dict[str, Any]], 
        output_pdf_path: str
    ) -> bool:
        """
        Accepts dynamic field inputs. Translates and draws aligned RTL/LTR texts.
        Each payload element should be:
        {
            "page": int,
            "x_pct": float,
            "y_pct": float,
            "value": str,
            "font_size": float (optional, defaults to 10.0),
            "font_color": list (optional [R, G, B], defaults to [0, 0, 0])
        }
        """
        doc = fitz.open(self.source_path)
        try:
            for field in payload:
                page_idx = field.get("page", 0)
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                    
                page = doc[page_idx]
                rect = page.rect
                rotation = page.rotation
                
                # Fetch text configuration
                raw_text = str(field.get("value", ""))
                font_size = float(field.get("font_size", 10.0))
                color = field.get("font_color", [0.0, 0.0, 0.0]) # Black by default
                
                # Dynamic coordinate translation using vector alignment math
                absolute_x, absolute_y = self.translate_percentages_to_points(
                    x_pct=float(field.get("x_pct", 0.0)),
                    y_pct=float(field.get("y_pct", 0.0)),
                    pdf_width=rect.width,
                    pdf_height=rect.height,
                    rotation=rotation
                )
                
                # Pre-process text through isolated Arabic reshaping RTL loop
                final_text = reshape_and_bidi(raw_text)
                
                # Draw text using PyMuPDF drawing coordinates
                # PyMuPDF draw_text expects top-left baseline of characters in its coordinate space
                # To prevent inverted drawing of shapes, we insert text using registerFont
                page.insert_font(
                    fontname="ArabicFont",
                    fontfile=self._font_path
                )
                
                page.insert_text(
                    fitz.Point(absolute_x, absolute_y),
                    final_text,
                    fontsize=font_size,
                    fontname="ArabicFont",
                    color=tuple(color)
                )
                
            doc.save(output_pdf_path, garbage=3, deflate=True)
            return True
            
        except Exception as e:
            raise RuntimeError(f"Failed to compile PDF: {str(e)}")
        finally:
            doc.close()
