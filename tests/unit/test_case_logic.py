import pytest
from app.routes.case import allowed_file

@pytest.mark.parametrize("filename, expected", [
    ("test.pdf", True),
    ("document.docx", True),
    ("image.jpg", True),
    ("archive.zip", True),
    ("script.js", False),
    ("no_extension", False),
    (".bashrc", False),
    ("test.PDF", True),
])
def test_allowed_file(filename, expected):
    """
    GIVEN a set of filenames
    WHEN the allowed_file function is called
    THEN check that it correctly identifies allowed and disallowed file types
    """
    assert allowed_file(filename) == expected 