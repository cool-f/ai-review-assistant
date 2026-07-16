from review_assistant.infrastructure.documents.text_extractor import TextExtractor


def test_chunking_preserves_pdf_or_slide_page_markers() -> None:
    chunks = TextExtractor.chunk_text(
        "[[PAGE:1]]\nFirst page paragraph.\n\n"
        "Still on page one.\n\n"
        "[[PAGE:2]]\nSecond page paragraph."
    )

    assert [chunk["page_number"] for chunk in chunks] == [1, 1, 2]
    assert all("[[PAGE:" not in chunk["content"] for chunk in chunks)
