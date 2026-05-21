import os
import shutil
import tempfile
from typing import List
from git import Repo
import pathspec
from loguru import logger
from app.domain.knowledge.repository import DocumentEntity
from langchain_text_splitters import RecursiveCharacterTextSplitter


class GitRepositoryParser:
    """
    Git 仓库解析器：负责克隆仓库、过滤文件并提取文本
    """

    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 200):
        self.temp_base_dir = os.path.join(tempfile.gettempdir(), "kita_git_repos")
        os.makedirs(self.temp_base_dir, exist_ok=True)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )

    def _is_binary(self, file_path: str) -> bool:
        """检查是否为二进制文件"""
        try:
            with open(file_path, 'tr') as check_file:
                check_file.read(1024)
                return False
        except UnicodeDecodeError:
            return True

    def parse_repo(self, repo_url: str, branch: str = "main") -> List[DocumentEntity]:
        """
        克隆并解析 Git 仓库
        """
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        local_path = tempfile.mkdtemp(dir=self.temp_base_dir, prefix=f"{repo_name}_")
        
        documents = []
        try:
            logger.info(f"正在克隆仓库: {repo_url} (branch: {branch}) 到 {local_path}")
            Repo.clone_from(repo_url, local_path, branch=branch, depth=1)
            
            # 解析 .gitignore
            gitignore_path = os.path.join(local_path, ".gitignore")
            spec = None
            if os.path.exists(gitignore_path):
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    spec = pathspec.PathSpec.from_lines("gitwildmatch", f.readlines())
            
            # 遍历文件
            for root, dirs, files in os.walk(local_path):
                # 排除 .git 目录
                if ".git" in dirs:
                    dirs.remove(".git")
                
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, local_path)
                    
                    # 检查是否匹配 .gitignore
                    if spec and spec.match_file(relative_path):
                        continue
                    
                    # 排除常见的二进制/图片后缀
                    if file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar.gz', '.pyc')):
                        continue
                        
                    if self._is_binary(full_path):
                        continue
                    
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            if not content.strip():
                                continue
                            
                            # 分块
                            chunks = self.text_splitter.split_text(content)
                            for i, chunk in enumerate(chunks):
                                documents.append(DocumentEntity(
                                    content=chunk,
                                    metadata={
                                        "source": f"git:{repo_name}",
                                        "file_path": relative_path,
                                        "repo_url": repo_url,
                                        "chunk": i
                                    }
                                ))
                    except Exception as e:
                        logger.warning(f"无法读取文件 {relative_path}: {str(e)}")
            
            logger.info(f"仓库解析完成，共提取 {len(documents)} 个文档分块")
            return documents
            
        finally:
            # 清理临时目录
            if os.path.exists(local_path):
                shutil.rmtree(local_path, ignore_errors=True)
                logger.info(f"临时目录已清理: {local_path}")
