from pathlib import Path

from docx import Document
from pypdf import PdfReader

RESUME_DIR = Path(__file__).resolve().parents[2] / "data" / "resumes"


def read_pdf(path: Path) -> str:
    """Extract text from every page of a PDF resume."""
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def read_docx(path: Path) -> str:
    """Extract paragraph text from a DOCX resume."""
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()


def read_resume(file_path: str) -> str:
    """Read a PDF, DOCX, or UTF-8 TXT resume from disk."""
    path = Path(file_path).expanduser()

    if not path.exists():
        raise FileNotFoundError(f"简历不存在：{path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        content = read_pdf(path)
    elif suffix == ".docx":
        content = read_docx(path)
    elif suffix == ".txt":
        content = path.read_text(encoding="utf-8").strip()
    else:
        raise ValueError("仅支持 PDF、DOCX 和 TXT 简历")

    if not content:
        raise ValueError(f"没有从简历中提取到文本：{path}")

    return content


def resolve_resume_name(resume_name: str) -> Path:
    """Resolve a resume file name inside the fixed resume directory."""
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(resume_name).name
    if not name:
        raise ValueError("请提供简历文件名")

    exact_path = RESUME_DIR / name
    if exact_path.is_file():
        return exact_path

    stem = Path(name).stem.lower()
    matches = [
        path
        for path in RESUME_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".pdf", ".docx", ".txt"}
        and path.stem.lower() == stem
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"固定简历目录中没有找到：{name}")
    raise ValueError(f"存在多个同名简历，请补充扩展名：{name}")


def read_resume_by_name(resume_name: str) -> str:
    """Read a resume by file name from data/resumes only."""
    return read_resume(str(resolve_resume_name(resume_name)))
