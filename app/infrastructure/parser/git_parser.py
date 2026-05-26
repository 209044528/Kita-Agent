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
        """
        检查是否为二进制文件。
        通过检查文件前 1024 字节中是否包含 Null Byte (\0) 来判断。
        这是检测二进制文件最稳妥的方法。
        """
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                return b'\0' in chunk
        except Exception:
            return True

    def _normalize_url(self, repo_url: str, branch: str) -> tuple[str, str]:
        """
        标准化 GitHub URL。如果是浏览器地址（如 .../tree/develop），
        则提取真正的 .git 地址和分支。
        """
        repo_url = repo_url.strip()
        if not repo_url:
            return repo_url, branch

        # 处理 GitHub 网页链接
        if "github.com" in repo_url:
            # 移除结尾的斜杠
            repo_url = repo_url.rstrip("/")
            
            # 如果包含 /tree/ 或 /blob/
            for indicator in ["/tree/", "/blob/"]:
                if indicator in repo_url:
                    parts = repo_url.split(indicator)
                    base_url = parts[0] + ".git"
                    # 只有当用户没有显式指定非默认分支时，才从 URL 提取
                    url_branch = parts[1].split("/")[0]
                    # 如果用户传的是默认的 "main" 或 "master"，且 URL 里有明确分支，则以 URL 为准
                    if branch in ["main", "master"] and url_branch:
                        branch = url_branch
                    return base_url, branch
            
            # 确保以 .git 结尾
            if not repo_url.endswith(".git"):
                repo_url += ".git"
                
        return repo_url, branch

    def parse_repo(self, repo_url: str, branch: str = "main") -> List[DocumentEntity]:
        """
        克隆并解析 Git 仓库
        """
        # 标准化 URL 和分支
        repo_url, branch = self._normalize_url(repo_url, branch)
        
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
                    gitignore_content = f.read()
                    logger.info(f"读取到 .gitignore 内容:\n{gitignore_content}")
                    spec = pathspec.PathSpec.from_lines("gitwildmatch", gitignore_content.splitlines())
            
            # 遍历文件
            for root, dirs, files in os.walk(local_path):
                # 排除 .git 目录
                if ".git" in dirs:
                    dirs.remove(".git")
                
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, local_path)
                    file_lower = file.lower()
                    
                    # 检查是否匹配 .gitignore
                    if spec and spec.match_file(relative_path):
                        logger.info(f"跳过文件 (Gitignore 匹配): {relative_path}")
                        continue
                    
                    # 1. 后缀黑名单 (强制排除，大小写不敏感)
                    if file_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.zip', '.tar.gz', '.pyc', '.exe', '.dll', '.so')):
                        logger.info(f"跳过文件 (排除后缀): {relative_path}")
                        continue

                    # 2. 后缀白名单 (强制接受文本，直接跳过二进制探测)
                    text_extensions = ('.py', '.md', '.txt', '.toml', '.json', '.yml', '.yaml', '.gitignore', '.js', '.css', '.html', '.sh')
                    is_text_file = file_lower.endswith(text_extensions)
                        
                    # 3. 如果不在白名单中，才进行二进制探测
                    if not is_text_file and self._is_binary(full_path):
                        logger.info(f"跳过文件 (二进制探测): {relative_path}")
                        continue
                    
                    try:
                        # 显式使用 utf-8 编码，并增加错误容错
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                            # 移除 PostgreSQL 不支持的 Null Byte
                            content = content.replace("\x00", "")
                            
                            if not content.strip():
                                logger.debug(f"跳过文件 (内容为空): {relative_path}")
                                continue
                            
                            logger.info(f"正在处理文件: {relative_path} ({len(content)} 字节)")
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
