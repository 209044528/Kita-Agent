from pathlib import Path
from loguru import logger
from pypdf import PdfReader
from docx import Document
from unstructured.partition.auto import partition


class DocumentParserService:
    """
    通用文档解析服务，支持 PDF、Word、TXT 等格式
    使用 unstructured 库进行文档解析和文本提取
    """

    @staticmethod
    def parse_document_to_text(file_path: str) -> str:
        """
        解析文档文件为纯文本字符串

        Args:
            file_path: 文档文件的本地路径

        Returns:
            解析后的纯文本内容

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件格式
            Exception: 解析过程中的其他错误
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_extension = path.suffix.lower()

        try:
            if file_extension in {".txt", ".md", ".json", ".yaml", ".yml"}:
                return DocumentParserService._parse_txt(file_path)
            elif file_extension == ".pdf":
                return DocumentParserService._parse_pdf(file_path)
            elif file_extension == ".docx":
                return DocumentParserService._parse_word(file_path)
            elif file_extension == ".doc":
                return DocumentParserService._parse_with_unstructured(file_path)
            else:
                return DocumentParserService._parse_with_unstructured(file_path)
        except Exception as e:
            logger.error(f"解析文档失败 {file_path}: {str(e)}")
            raise

    @staticmethod
    def _parse_txt(file_path: str) -> str:
        """解析纯文本文件"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    @staticmethod
    def _parse_pdf(file_path: str) -> str:
        """解析 PDF 文件"""
        reader = PdfReader(file_path)
        text_parts = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        return "\n\n".join(text_parts)

    @staticmethod
    def _parse_word(file_path: str) -> str:
        """解析 Word 文档"""
        doc = Document(file_path)
        text_parts = []

        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)

        return "\n\n".join(text_parts)

    @staticmethod
    def _parse_with_unstructured(file_path: str) -> str:
        """使用 unstructured 库解析文档（通用方法）"""
        elements = partition(filename=file_path)
        text_parts = [str(element) for element in elements]

        return "\n\n".join(text_parts)
