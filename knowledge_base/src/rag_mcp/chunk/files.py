"""发现知识库文件。"""

from pathlib import Path


def search_files(
    roots: list[Path], *, suffixes: tuple[str, ...] = (".md", ".txt")
) -> list[Path]:
    """递归查找普通文件，后缀不区分大小写；返回排序、去重的绝对路径。

    任意根目录无效时抛出异常，不返回部分结果。
    """
    roots = [root.expanduser().resolve() for root in roots]
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"{root} 不存在")
        if not root.is_dir():
            raise NotADirectoryError(f"{root} 不是目录")

    suffixes = tuple(suffix.lower() for suffix in suffixes)
    files: set[Path] = set()
    for root in sorted(set(roots)):
        for file in root.rglob("*"):
            if file.suffix.lower() in suffixes and file.is_file():
                files.add(file.resolve())
    return sorted(files)


def search_md_files(roots: list[Path]) -> list[Path]:
    """只查找 Markdown 文件，保留原有的发现入口。"""
    return search_files(roots, suffixes=(".md",))
